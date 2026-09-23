#!/usr/bin/env python3
"""R15.8 - Economic Trade Intelligence.

Learns trajectory-specific economic heads from causal R15.6 event features.

Targets, all measured from NEXT 15m open and only within next 32 bars (8h):
A hit05_before_loss10 : +0.5 ATR before -1.0 ATR
B hit10_before_loss10 : +1.0 ATR before -1.0 ATR
C giveback_after05    : conditional on A; after +0.5, revisit <=0 ATR before +1.5 ATR
D extend_after10      : conditional on B; after +1.0, reach +2.0 ATR before falling to +0.25 ATR

Same-bar ambiguity is resolved conservatively against the trade.
TRAIN fits models. CALIB selects policy thresholds. TEST is evaluated once.
OUTER_HOLDOUT >= 2026-07-01 is not labeled, trained, calibrated, or backtested.
"""
from __future__ import annotations
import json, math, heapq, gc
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, average_precision_score, log_loss, brier_score_loss

EVROOT=Path("r15_regime_lab/model_r15_6/events")
RAWROOT=Path("r15_regime_lab/history/15m")
MANIFEST=Path("r15_regime_lab/model_r15_6/feature_manifest.json")
OUT=Path("r15_regime_lab/model_r15_8")
OUT.mkdir(parents=True,exist_ok=True)

SEED=1508
HORIZON=32
BASE_COST=0.0016
STRESS_COST=0.0021
START_CAPITAL=10_000.0
MAX_POSITIONS=10
SLOT_FRAC=.10

manifest=json.loads(MANIFEST.read_text())
FEATURES=manifest["features"]
EVENT_TYPES=manifest["event_types"]

RAW={}
def raw(sym):
    if sym not in RAW:
        p=RAWROOT/f"{sym}.csv.gz"
        x=pd.read_csv(p,usecols=["open_time","open","high","low","close"])
        for c in x.columns:x[c]=pd.to_numeric(x[c],errors="coerce")
        RAW[sym]=x.dropna().sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    return RAW[sym]

def load_events(split):
    parts=[]
    for p in sorted(EVROOT.glob("*.parquet")):
        d=pd.read_parquet(p)
        d=d[d["split"].eq(split)].copy()
        if not len(d):continue
        d["symbol"]=p.stem
        d["event_direction_feature"]=d.event_direction.astype("float32")
        d["event_strength_feature"]=d.event_strength.astype("float32")
        for et in EVENT_TYPES:d["evt_"+et]=(d.event_type==et).astype("int8")
        for f in FEATURES:
            if f not in d.columns:d[f]=np.nan
        parts.append(d)
    return pd.concat(parts,ignore_index=True)

def first_touch(fav,adv,up,down,start=0):
    """Conservative first-touch: if both thresholds hit on same candle, down wins."""
    for i in range(start,len(fav)):
        hit_up=fav[i]>=up
        hit_dn=adv[i]>=down
        if hit_up and hit_dn:return -1,i
        if hit_dn:return -1,i
        if hit_up:return 1,i
    return 0,len(fav)-1

def build_path(row):
    x=raw(row.symbol)
    ot=x.open_time.to_numpy()
    pos=np.searchsorted(ot,int(row.available_time))
    if pos>=len(x) or int(x.open_time.iloc[pos])!=int(row.available_time):return None
    event_pos=pos-1
    if event_pos<0:return None
    event_close=float(x.close.iloc[event_pos])
    atr_pct=float(row["15m_atr_pct"])
    if not np.isfinite(atr_pct) or atr_pct<=0:return None
    atr=event_close*atr_pct
    entry=float(x.open.iloc[pos])
    direction=int(row.event_direction)
    if direction not in (-1,1):return None
    end=min(pos+HORIZON-1,len(x)-1)
    w=x.iloc[pos:end+1]
    if len(w)<HORIZON:return None
    if direction>0:
        fav=((w.high-entry)/atr).to_numpy(float)
        adv=((entry-w.low)/atr).to_numpy(float)
        close=((w.close-entry)/atr).to_numpy(float)
    else:
        fav=((entry-w.low)/atr).to_numpy(float)
        adv=((w.high-entry)/atr).to_numpy(float)
        close=((entry-w.close)/atr).to_numpy(float)

    a05,i05=first_touch(fav,adv,.5,1.0)
    a10,i10=first_touch(fav,adv,1.0,1.0)
    a15,i15=first_touch(fav,adv,1.5,1.0)

    give=np.nan
    if a05==1:
        # After +0.5, "giveback" means revisit entry before reaching +1.5.
        # Conservative same-candle ambiguity -> giveback.
        for i in range(i05+1,len(fav)):
            hit_ext=fav[i]>=1.5
            hit_back=(close[i]<=0) or (adv[i]>=0.0 and x.close.iloc[pos+i]*0==0 and False)
            # low/high path relative to entry: adverse >= 0 means always true, so use close<=0
            if hit_ext and hit_back: give=1.0; break
            if hit_back: give=1.0; break
            if hit_ext: give=0.0; break
        if not np.isfinite(give):
            give=float(close[-1]<=0)

    extend=np.nan
    if a10==1:
        for i in range(i10+1,len(fav)):
            hit_ext=fav[i]>=2.0
            # Falling back to +0.25 is approximated conservatively by directional close.
            hit_back=close[i]<=.25
            if hit_ext and hit_back: extend=0.0; break
            if hit_back: extend=0.0; break
            if hit_ext: extend=1.0; break
        if not np.isfinite(extend):
            extend=float(close[-1]>.25)

    return {
      "entry":entry,"atr_abs":atr,
      "y_hit05_before_loss10":float(a05==1),
      "y_hit10_before_loss10":float(a10==1),
      "y_hit15_before_loss10":float(a15==1),
      "y_giveback_after05":give,
      "y_extend_after10":extend,
      "mfe_8h_atr":float(np.max(fav)),
      "mae_8h_atr":float(np.max(adv)),
      "close_8h_atr":float(close[-1]),
    }

def enrich_paths(d,split):
    rows=[]
    for i,row in d.iterrows():
        r=build_path(row)
        rows.append(r if r is not None else {})
    p=pd.DataFrame(rows)
    z=pd.concat([d.reset_index(drop=True),p.reset_index(drop=True)],axis=1)
    z.to_parquet(OUT/f"events_{split.lower()}_economic.parquet",index=False,compression="zstd")
    return z

train=enrich_paths(load_events("TRAIN"),"TRAIN")
calib=enrich_paths(load_events("CALIB"),"CALIB")
test=enrich_paths(load_events("TEST"),"TEST")

# Drop rows without complete forward path.
req=["y_hit05_before_loss10","y_hit10_before_loss10"]
train=train.dropna(subset=req).reset_index(drop=True)
calib=calib.dropna(subset=req).reset_index(drop=True)
test=test.dropna(subset=req).reset_index(drop=True)

for d in [train,calib,test]:
    d[FEATURES]=d[FEATURES].astype("float32").replace([np.inf,-np.inf],np.nan)

HEADS={
 "hit05":{"target":"y_hit05_before_loss10","conditional":None},
 "hit10":{"target":"y_hit10_before_loss10","conditional":None},
 "hit15":{"target":"y_hit15_before_loss10","conditional":None},
 "giveback05":{"target":"y_giveback_after05","conditional":"y_hit05_before_loss10"},
 "extend10":{"target":"y_extend_after10","conditional":"y_hit10_before_loss10"},
}

def mask_for(d,head):
    tgt=HEADS[head]["target"]
    m=d[tgt].notna().to_numpy().copy()
    cond=HEADS[head]["conditional"]
    if cond:m &= d[cond].eq(1).to_numpy()
    return m

def met(y,p):
    return {
      "n":int(len(y)),
      "positive_rate":float(np.mean(y)),
      "roc_auc":float(roc_auc_score(y,p)) if len(np.unique(y))>1 else None,
      "pr_auc":float(average_precision_score(y,p)) if len(np.unique(y))>1 else None,
      "brier":float(brier_score_loss(y,p)),
      "logloss":float(log_loss(y,np.c_[1-p,p],labels=[0,1]))
    }

models={}; probs={"TRAIN":{},"CALIB":{},"TEST":{}}; results={}; importance=[]
for j,h in enumerate(HEADS):
    mt=mask_for(train,h); mc=mask_for(calib,h); me=mask_for(test,h)
    target=HEADS[h]["target"]
    ytr=train.loc[mt,target].astype(int); yca=calib.loc[mc,target].astype(int); yte=test.loc[me,target].astype(int)
    mdl=lgb.LGBMClassifier(
      objective="binary",n_estimators=800,learning_rate=.035,num_leaves=47,
      min_child_samples=80,subsample=.82,subsample_freq=1,colsample_bytree=.78,
      reg_alpha=.20,reg_lambda=1.5,max_bin=127,random_state=SEED+j,n_jobs=4,verbosity=-1)
    mdl.fit(train.loc[mt,FEATURES],ytr,eval_set=[(calib.loc[mc,FEATURES],yca)],
            eval_metric="binary_logloss",
            callbacks=[lgb.early_stopping(60,verbose=False),lgb.log_evaluation(0)])
    # Store all-row probabilities for policy routing.
    probs["TRAIN"][h]=mdl.predict_proba(train[FEATURES])[:,1]
    probs["CALIB"][h]=mdl.predict_proba(calib[FEATURES])[:,1]
    probs["TEST"][h]=mdl.predict_proba(test[FEATURES])[:,1]
    pca=probs["CALIB"][h][mc]; pte=probs["TEST"][h][me]
    results[h]={"best_iteration":int(mdl.best_iteration_),"calib":met(yca,pca),"test":met(yte,pte)}
    mdl.booster_.save_model(str(OUT/f"{h}.txt"))
    gain=mdl.booster_.feature_importance(importance_type="gain")
    for f,g in zip(FEATURES,gain):importance.append({"head":h,"feature":f,"gain":float(g)})
    models[h]=mdl
    print(h,json.dumps(results[h]),flush=True)

for sp,d in [("TRAIN",train),("CALIB",calib),("TEST",test)]:
    for h in HEADS:d["p_"+h]=probs[sp][h]

pd.DataFrame(importance).sort_values(["head","gain"],ascending=[True,False]).to_csv(OUT/"feature_importance_by_head.csv",index=False)

# ---------- Economic policy simulator ----------
def simulate_trade(row,policy,cost):
    x=raw(row.symbol)
    ot=x.open_time.to_numpy()
    pos=np.searchsorted(ot,int(row.available_time))
    if pos>=len(x) or int(x.open_time.iloc[pos])!=int(row.available_time):return None
    event_pos=pos-1
    entry=float(x.open.iloc[pos]); atr=float(row.atr_abs); direction=int(row.event_direction)
    end=min(pos+HORIZON-1,len(x)-1)
    # Initial 1 ATR hard risk; adaptive protection is the whole point.
    stop_atr=-1.0
    realized=0.0
    remaining=1.0
    stage=0
    exit_reason="TIME"
    exit_i=end
    last_px=float(x.close.iloc[end])

    def net_leg(ret_atr,frac):
        # convert ATR units to percentage via atr/entry, then subtract proportional roundtrip cost.
        gross=ret_atr*(atr/entry)*frac
        return gross - 2*cost*frac

    pnl=0.0
    for i in range(pos,end+1):
        hi=float(x.high.iloc[i]); lo=float(x.low.iloc[i]); cl=float(x.close.iloc[i])
        if direction>0:
            fav=(hi-entry)/atr; adv=(entry-lo)/atr; close_atr=(cl-entry)/atr
        else:
            fav=(entry-lo)/atr; adv=(hi-entry)/atr; close_atr=(entry-cl)/atr

        # Hard/protected stop. Conservative: stop evaluated before profit milestones.
        if close_atr<=stop_atr or adv>=(-stop_atr if stop_atr<0 else 0):
            # For positive stop, use close-based conservative approximation to avoid claiming intrabar ordering.
            if stop_atr>0 and close_atr>stop_atr:
                pass
            else:
                pnl+=net_leg(stop_atr,remaining)
                remaining=0; exit_reason="STOP_PROTECTED" if stop_atr>=0 else "STOP"; exit_i=i; break

        # +0.5 ATR state
        if stage<1 and fav>=.5:
            stage=1
            if row.p_giveback05>=policy["giveback_threshold"]:
                stop_atr=max(stop_atr,policy["protect_atr"])

        # +1.0 ATR state
        if stage<2 and fav>=1.0:
            stage=2
            if row.p_extend10<policy["extend_threshold"]:
                pnl+=net_leg(1.0,remaining); remaining=0; exit_reason="EXIT_AT_1"; exit_i=i; break
            else:
                frac=policy["partial_at_1"]
                if frac>0:
                    pnl+=net_leg(1.0,frac); remaining-=frac
                stop_atr=max(stop_atr,policy["runner_stop_atr"])

        # runner extension target
        if stage>=2 and remaining>0 and fav>=policy["runner_target_atr"]:
            pnl+=net_leg(policy["runner_target_atr"],remaining)
            remaining=0; exit_reason="RUNNER_TARGET"; exit_i=i; break

    if remaining>0:
        cl=float(x.close.iloc[end])
        final_atr=direction*(cl-entry)/atr
        pnl+=net_leg(final_atr,remaining)
        exit_reason="TIME"; exit_i=end
    return {
      "symbol":row.symbol,"event_type":row.event_type,"direction":direction,
      "entry_time":int(row.available_time),"exit_time":int(x.open_time.iloc[exit_i])+900_000,
      "net_pct":float(pnl),"exit_reason":exit_reason,
      "p_hit10":float(row.p_hit10),"p_giveback05":float(row.p_giveback05),"p_extend10":float(row.p_extend10)
    }

def basic(t):
    if not len(t):return {"trades":0}
    r=t.net_pct.to_numpy(float); gp=r[r>0].sum(); gl=-r[r<0].sum()
    return {"trades":int(len(t)),"win_rate":float((r>0).mean()),"avg_net_pct":float(r.mean()),
            "median_net_pct":float(np.median(r)),"profit_factor":float(gp/gl) if gl>0 else None}

def trade_policy(events,policy,cost):
    d=events[events.p_hit10>=policy["entry_threshold"]]
    rows=[]
    for row in d.itertuples(index=False):
        r=simulate_trade(row,policy,cost)
        if r:rows.append(r)
    return pd.DataFrame(rows)

def portfolio(t):
    if t.empty:return {"start":START_CAPITAL,"end":START_CAPITAL,"return":0.0,"max_dd":0.0,"accepted":0},pd.DataFrame()
    t=t.sort_values(["entry_time","p_hit10"],ascending=[True,False]).reset_index(drop=True)
    eq=START_CAPITAL; heap=[]; active=set(); accepted=[]; curve=[eq]; uid=0
    def settle(until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap); eq+=pnl; active.discard(sym); curve.append(eq)
    rejected=0
    for r in t.itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POSITIONS or r.symbol in active:
            rejected+=1; continue
        notional=eq*SLOT_FRAC; pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol)); active.add(r.symbol)
        z=r._asdict();z["notional"]=notional;z["pnl"]=pnl;accepted.append(z);uid+=1
    settle(10**30)
    arr=np.asarray(curve,float); peak=np.maximum.accumulate(arr); dd=arr/peak-1
    return {"start":START_CAPITAL,"end":float(eq),"return":float(eq/START_CAPITAL-1),
            "max_dd":float(-dd.min()),"accepted":len(accepted),"rejected":rejected},pd.DataFrame(accepted)

# CALIB-only policy search.
entry_grid=[.50,.55,.60,.65,.70,.75]
give_grid=[.50,.60,.70]
extend_grid=[.45,.55,.65]
protect_grid=[0.0,.25]
partial_grid=[.0,.5]
runner_target_grid=[1.5,2.0,2.5]
runner_stop_grid=[.25,.5]
grid=[]
best=None
for ent in entry_grid:
  for give in give_grid:
    for ext in extend_grid:
      for protect in protect_grid:
        for partial in partial_grid:
          for rt in runner_target_grid:
            for rs in runner_stop_grid:
              if rs>=rt:continue
              pol={"entry_threshold":ent,"giveback_threshold":give,"extend_threshold":ext,
                   "protect_atr":protect,"partial_at_1":partial,
                   "runner_target_atr":rt,"runner_stop_atr":rs}
              tr=trade_policy(calib,pol,BASE_COST)
              if len(tr)<120:continue
              m=basic(tr)
              # optimize average net expectancy, PF as tie-breaker; no TEST data.
              pfv=m["profit_factor"] or 0
              score=m["avg_net_pct"]+.00005*min(pfv,3)
              rec={**pol,**m,"score":score};grid.append(rec)
              if best is None or (score,pfv,len(tr))>(best[0],best[1],best[2]):
                  best=(score,pfv,len(tr),pol,m)
G=pd.DataFrame(grid).sort_values(["score","profit_factor"],ascending=False)
G.to_csv(OUT/"calib_policy_grid.csv",index=False)
if best is None:raise RuntimeError("No eligible CALIB policy")
policy=best[3]; calib_metrics=best[4]

def eval_scenario(name,cost):
    tr=trade_policy(test,policy,cost)
    pm,acc=portfolio(tr)
    tm=basic(acc if len(acc) else tr)
    if len(acc):acc.to_csv(OUT/f"{name}_trades.csv",index=False)
    return {"name":name,"cost_one_way":cost,"trade_metrics":tm,"portfolio":pm}

test_base=eval_scenario("economic_ai_base",BASE_COST)
test_stress=eval_scenario("economic_ai_stress",STRESS_COST)

summary={
 "version":"R15.8",
 "architecture":"economic trajectory heads + stateful management policy",
 "features":len(FEATURES),
 "train_events":int(len(train)),"calib_events":int(len(calib)),"test_events":int(len(test)),
 "heads":results,
 "policy_calibration":{"period":"2026Q1","policy":policy,"metrics":calib_metrics},
 "test_scenarios":[test_base,test_stress],
 "comparison_r15_7":{"base_return":-0.1293130984180254,"base_pf":0.5649379797942097,
                     "long_only_return":-0.05926221100274398},
 "outer_holdout_opened":False,
 "outer_holdout_start":"2026-07-01T00:00:00Z",
 "notes":[
   "All trajectory targets use only forward candles during training-label construction.",
   "Features remain causal and available at event time.",
   "Policy thresholds and management parameters are selected on CALIB only.",
   "TEST is evaluated after policy freeze and is now development validation, not a virgin final holdout.",
   "OUTER_HOLDOUT remains sealed."
 ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
