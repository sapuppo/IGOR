#!/usr/bin/env python3
"""R15.6 - Event Intelligence.

Converts candle-level R15.3 + R15.5.1 features into non-overlapping market events,
then trains event-quality models.

Key anti-leakage / anti-overcounting rules:
- event triggers use current/past completed candles only;
- higher timeframes were already availability-aligned causally;
- minimum 32 x 15m bars (=8h) between retained events per symbol;
- feature pruning is learned on TRAIN events only;
- CALIB chooses confidence thresholds;
- TEST = 2026Q2 is evaluated once;
- OUTER_HOLDOUT >= 2026-07-01 stays unlabeled and is not evaluated.
"""
from __future__ import annotations
import json, gc, math
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, f1_score, log_loss,
    confusion_matrix, classification_report, roc_auc_score, average_precision_score
)

BASE=Path("r15_regime_lab/processed/symbols")
TECH=Path("r15_regime_lab/technical_expansion/symbols")
OUT=Path("r15_regime_lab/model_r15_6")
EVOUT=OUT/"events"
EVOUT.mkdir(parents=True,exist_ok=True)

SEED=1506
COOLDOWN_BARS=32
OUTCOMES=["FAILURE","MIXED","FOLLOWTHROUGH"]
OUTCOME2ID={x:i for i,x in enumerate(OUTCOMES)}

BASE_FEATURE_PREFIX=("15m_","1h_","4h_","1d_","btc_")
TECH_MARK="_ta_"

def load_symbol(sym):
    b=pd.read_parquet(BASE/f"{sym}.parquet")
    t=pd.read_parquet(TECH/f"{sym}.parquet")
    # Avoid duplicate metadata from expansion artifact.
    tcols=["available_time"]+[c for c in t.columns if TECH_MARK in c]
    d=b.merge(t[tcols],on="available_time",how="left",validate="one_to_one")
    d=d.sort_values("available_time").reset_index(drop=True)
    return d

def event_candidates(d):
    state=d["state_heuristic"].fillna("UNCERTAIN")
    prev_state=state.shift(1)
    # Primary structural triggers.
    choch_up=d.get("15m_ta_choch_up",pd.Series(0,index=d.index)).fillna(0)>0
    choch_dn=d.get("15m_ta_choch_down",pd.Series(0,index=d.index)).fillna(0)>0
    bos_up=d.get("15m_ta_bos_up",pd.Series(0,index=d.index)).fillna(0)>0
    bos_dn=d.get("15m_ta_bos_down",pd.Series(0,index=d.index)).fillna(0)>0
    don_up=d.get("15m_ta_donchian_break20_up_atr",pd.Series(np.nan,index=d.index)).fillna(-999)>0
    don_dn=d.get("15m_ta_donchian_break20_dn_atr",pd.Series(np.nan,index=d.index)).fillna(-999)>0

    squeeze=d.get("15m_ta_squeeze_on",pd.Series(0,index=d.index)).fillna(0)>0
    squeeze_release=squeeze.shift(1).fillna(False)&(~squeeze)&(don_up|don_dn)

    enter_deter=(state=="RANGE_DERIORATING")&(prev_state!="RANGE_DERIORATING")
    enter_trend=(state=="TREND")&(prev_state!="TREND")
    enter_exhaust=(state=="EXHAUSTION")&(prev_state!="EXHAUSTION")

    # One event identity per bar, explicit precedence strongest -> weakest.
    et=np.full(len(d),"",dtype=object)
    edir=np.zeros(len(d),dtype=np.int8)
    strength=np.zeros(len(d),dtype=np.float32)

    def put(mask,name,direction,score):
        nonlocal et,edir,strength
        m=np.asarray(mask.fillna(False))&(et=="")
        et[m]=name
        if np.isscalar(direction): edir[m]=int(direction)
        else: edir[m]=np.asarray(direction,dtype=np.int8)[m]
        if np.isscalar(score): strength[m]=float(score)
        else:
            a=np.asarray(score,dtype=float)
            strength[m]=np.nan_to_num(a[m],nan=0.0,posinf=20.0,neginf=-20.0)

    # CHoCH is highest-priority structural transition.
    put(choch_up,"CHOCH_UP",1,d.get("15m_ta_swing_low_delta_atr",0).abs())
    put(choch_dn,"CHOCH_DOWN",-1,d.get("15m_ta_swing_high_delta_atr",0).abs())
    put(squeeze_release&don_up,"SQUEEZE_BREAK_UP",1,d.get("15m_ta_donchian_break20_up_atr",0))
    put(squeeze_release&don_dn,"SQUEEZE_BREAK_DOWN",-1,d.get("15m_ta_donchian_break20_dn_atr",0))
    put(bos_up,"BOS_UP",1,d.get("15m_ta_donchian_break20_up_atr",0).clip(lower=0))
    put(bos_dn,"BOS_DOWN",-1,d.get("15m_ta_donchian_break20_dn_atr",0).clip(lower=0))
    # Donchian catches breakouts not already classified as BOS.
    put(don_up,"DONCHIAN_UP",1,d.get("15m_ta_donchian_break20_up_atr",0))
    put(don_dn,"DONCHIAN_DOWN",-1,d.get("15m_ta_donchian_break20_dn_atr",0))

    di=d.get("15m_di_spread",pd.Series(0,index=d.index)).fillna(0)
    ema=d.get("15m_ema_sep_atr",pd.Series(0,index=d.index)).fillna(0)
    bias=np.where((di+10*ema)>=0,1,-1).astype(np.int8)
    range_bias=np.where(d.get("15m_range_pos",pd.Series(.5,index=d.index)).fillna(.5)>=.5,1,-1).astype(np.int8)
    put(enter_deter,"RANGE_DETERIORATION",range_bias,d.get("15m_edge_touch20",0))
    put(enter_trend,"TREND_ONSET",bias,d.get("15m_adx14",0))
    put(enter_exhaust,"EXHAUSTION_ONSET",bias,d.get("15m_adx14",0))

    cand=np.flatnonzero(et!="")
    keep=[]
    last=-10**9
    for i in cand:
        if i-last>=COOLDOWN_BARS:
            keep.append(i); last=i
    e=d.iloc[keep].copy()
    e["event_type"]=et[keep]
    e["event_direction"]=edir[keep]
    e["event_strength"]=strength[keep]
    e["event_row_index"]=keep
    return e

def label_events(e):
    # Future labels already blank in R15.3 outer holdout.
    mfe=e["y_mfe_8h_atr"].astype(float)
    mae=e["y_mae_8h_atr"].astype(float)
    ret=e["y_ret_8h_atr"].astype(float)
    direction=e.event_direction.astype(float)
    fav=np.where(direction>0,mfe,mae)
    adv=np.where(direction>0,mae,mfe)
    signed=ret*direction
    e["favorable_8h_atr"]=fav
    e["adverse_8h_atr"]=adv
    e["signed_ret_8h_atr"]=signed

    follow=((signed>=1.0)|((fav>=1.5)&(adv<=1.0)))
    fail=((signed<=-1.0)|((adv>=1.5)&(fav<=1.0)))
    # If both path conditions fire, call it mixed/choppy.
    both=follow&fail
    outcome=np.full(len(e),"MIXED",object)
    outcome[follow&~both]="FOLLOWTHROUGH"
    outcome[fail&~both]="FAILURE"
    # Preserve sealing: no outcomes for outer holdout / unavailable futures.
    unavailable=e["target_path_8h"].isna()|~np.isfinite(signed)
    outcome[unavailable]=None
    e["event_outcome"]=outcome
    clean=(fav>=1.5)&(adv<=1.0)&(signed>0.25)
    e["clean_edge"]=np.where(unavailable,np.nan,clean.astype(float))
    return e

def extract_all():
    audit=[]; paths=[]
    for p in sorted(BASE.glob("*.parquet")):
        sym=p.stem
        d=load_symbol(sym)
        e=label_events(event_candidates(d))
        e["symbol"]=sym
        # Keep all causal feature columns; outer holdout labels remain blank.
        fcols=[c for c in e.columns if c.startswith(BASE_FEATURE_PREFIX) or TECH_MARK in c]
        meta=["symbol","ts","available_time","split","event_type","event_direction","event_strength",
              "event_row_index","event_outcome","clean_edge","favorable_8h_atr","adverse_8h_atr","signed_ret_8h_atr"]
        e=e[meta+fcols]
        dest=EVOUT/f"{sym}.parquet"
        e.to_parquet(dest,index=False,compression="zstd")
        audit.append({
          "symbol":sym,"candles":len(d),"events":len(e),
          "train_events":int((e["split"]=="TRAIN").sum()),
          "calib_events":int((e["split"]=="CALIB").sum()),
          "test_events":int((e["split"]=="TEST").sum()),
          "outer_holdout_events":int((e["split"]=="OUTER_HOLDOUT").sum())
        })
        print(f"EVENTS {sym}: {len(e):,}",flush=True)
        del d,e; gc.collect()
    A=pd.DataFrame(audit); A.to_csv(OUT/"event_audit.csv",index=False)
    return A

def load_events(split):
    parts=[]
    for p in sorted(EVOUT.glob("*.parquet")):
        d=pd.read_parquet(p)
        d=d[(d["split"]==split)&d["event_outcome"].notna()]
        if len(d):parts.append(d)
    return pd.concat(parts,ignore_index=True)

def prune_features(train):
    candidates=[c for c in train.columns if c.startswith(BASE_FEATURE_PREFIX) or TECH_MARK in c]
    stats=[]
    keep=[]
    for c in candidates:
        x=pd.to_numeric(train[c],errors="coerce")
        miss=float(x.isna().mean())
        nun=int(x.nunique(dropna=True))
        stats.append({"feature":c,"missing_rate":miss,"nunique":nun})
        if miss<=.30 and nun>1:keep.append(c)
    pd.DataFrame(stats).to_csv(OUT/"feature_quality_train.csv",index=False)

    # Correlation pruning on TRAIN only. Use bounded sample for speed/stability.
    s=train[keep]
    if len(s)>120000:s=s.sample(120000,random_state=SEED)
    s=s.astype("float32").replace([np.inf,-np.inf],np.nan)
    corr=s.corr().abs()
    drop=set(); pairs=[]
    names=list(corr.columns)
    for j in range(1,len(names)):
        cj=names[j]
        for i in range(j):
            ci=names[i]
            v=corr.iat[i,j]
            if np.isfinite(v) and v>=.985:
                pairs.append({"keep_candidate":ci,"drop_candidate":cj,"abs_corr":float(v)})
                drop.add(cj); break
    pd.DataFrame(pairs).to_csv(OUT/"correlation_prune_train.csv",index=False)
    final=[c for c in keep if c not in drop]
    return final,drop

def add_event_features(d,event_types):
    x=d.copy()
    x["event_direction_feature"]=x.event_direction.astype("float32")
    x["event_strength_feature"]=x.event_strength.astype("float32")
    for et in event_types:
        x["evt_"+et]=(x.event_type==et).astype("int8")
    return x

A=extract_all()
train=load_events("TRAIN")
calib=load_events("CALIB")
test=load_events("TEST")
features,pruned=prune_features(train)
event_types=sorted(train.event_type.unique().tolist())
extra=["event_direction_feature","event_strength_feature"]+["evt_"+e for e in event_types]
train=add_event_features(train,event_types); calib=add_event_features(calib,event_types); test=add_event_features(test,event_types)
features_all=features+extra

for d in [train,calib,test]:
    d[features_all]=d[features_all].astype("float32").replace([np.inf,-np.inf],np.nan)

# -------- multiclass event outcome --------
ytr=train.event_outcome.map(OUTCOME2ID).astype(int)
yca=calib.event_outcome.map(OUTCOME2ID).astype(int)
yte=test.event_outcome.map(OUTCOME2ID).astype(int)

clf=lgb.LGBMClassifier(
    objective="multiclass",n_estimators=900,learning_rate=.035,num_leaves=47,
    min_child_samples=80,subsample=.82,subsample_freq=1,colsample_bytree=.78,
    reg_alpha=.20,reg_lambda=1.5,max_bin=127,random_state=SEED,n_jobs=4,verbosity=-1
)
clf.fit(train[features_all],ytr,eval_set=[(calib[features_all],yca)],
        eval_metric="multi_logloss",
        callbacks=[lgb.early_stopping(60,verbose=False),lgb.log_evaluation(0)])
pca=clf.predict_proba(calib[features_all]); pte=clf.predict_proba(test[features_all])
pred=pte.argmax(axis=1)
multi={
 "accuracy":float(accuracy_score(yte,pred)),
 "balanced_accuracy":float(balanced_accuracy_score(yte,pred)),
 "macro_f1":float(f1_score(yte,pred,average="macro")),
 "weighted_f1":float(f1_score(yte,pred,average="weighted")),
 "logloss":float(log_loss(yte,pte,labels=[0,1,2])),
 "best_iteration":int(clf.best_iteration_)
}
pd.DataFrame(confusion_matrix(yte,pred,labels=[0,1,2]),index=OUTCOMES,columns=OUTCOMES).to_csv(OUT/"event_confusion_test.csv")
pd.DataFrame(classification_report(yte,pred,target_names=OUTCOMES,output_dict=True,zero_division=0)).T.to_csv(OUT/"event_classification_test.csv")
clf.booster_.save_model(str(OUT/"event_outcome_model.txt"))

# Calib-only confidence gate for FOLLOWTHROUGH probability.
follow_id=OUTCOME2ID["FOLLOWTHROUGH"]
base_ca=float((yca==follow_id).mean())
curve=[]
for th in np.arange(.30,.81,.025):
    m=pca[:,follow_id]>=th
    if m.sum()<100:
        curve.append({"threshold":float(th),"n":int(m.sum()),"coverage":float(m.mean()),"precision":None,"lift":None,"utility":-999})
        continue
    prec=float((yca[m].to_numpy()==follow_id).mean())
    cov=float(m.mean()); lift=prec/base_ca if base_ca>0 else np.nan
    # reward precision lift while retaining some coverage
    utility=(prec-base_ca)*math.sqrt(cov)
    curve.append({"threshold":float(th),"n":int(m.sum()),"coverage":cov,"precision":prec,"lift":lift,"utility":float(utility)})
C=pd.DataFrame(curve); C.to_csv(OUT/"followthrough_gate_calib.csv",index=False)
eligible=C[(C.coverage>=.05)&C.precision.notna()]
if len(eligible):
    gate=float(eligible.sort_values("utility",ascending=False).iloc[0].threshold)
else: gate=.50

sel=pte[:,follow_id]>=gate
base_test=float((yte==follow_id).mean())
selected={
 "threshold_from_calib":gate,
 "selected_events":int(sel.sum()),
 "coverage":float(sel.mean()),
 "followthrough_rate_selected":float((yte[sel].to_numpy()==follow_id).mean()) if sel.any() else None,
 "followthrough_rate_all":base_test,
 "lift":float(((yte[sel].to_numpy()==follow_id).mean())/base_test) if sel.any() and base_test>0 else None,
 "positive_signed_return_rate":float((test.loc[sel,"signed_ret_8h_atr"]>0).mean()) if sel.any() else None,
 "mean_signed_ret_atr":float(test.loc[sel,"signed_ret_8h_atr"].mean()) if sel.any() else None,
 "median_signed_ret_atr":float(test.loc[sel,"signed_ret_8h_atr"].median()) if sel.any() else None,
 "median_favorable_atr":float(test.loc[sel,"favorable_8h_atr"].median()) if sel.any() else None,
 "median_adverse_atr":float(test.loc[sel,"adverse_8h_atr"].median()) if sel.any() else None
}

# -------- strict clean-edge binary head --------
def edge_metrics(y,p):
    return {
      "roc_auc":float(roc_auc_score(y,p)) if len(np.unique(y))>1 else None,
      "pr_auc":float(average_precision_score(y,p)) if len(np.unique(y))>1 else None,
      "positive_rate":float(np.mean(y))
    }

etr=train.clean_edge.astype(int); eca=calib.clean_edge.astype(int); ete=test.clean_edge.astype(int)
edge=lgb.LGBMClassifier(
  objective="binary",n_estimators=800,learning_rate=.035,num_leaves=47,min_child_samples=80,
  subsample=.82,subsample_freq=1,colsample_bytree=.78,reg_alpha=.2,reg_lambda=1.5,
  max_bin=127,random_state=SEED+1,n_jobs=4,verbosity=-1)
edge.fit(train[features_all],etr,eval_set=[(calib[features_all],eca)],eval_metric="binary_logloss",
         callbacks=[lgb.early_stopping(60,verbose=False),lgb.log_evaluation(0)])
eca_p=edge.predict_proba(calib[features_all])[:,1]; ete_p=edge.predict_proba(test[features_all])[:,1]
edge_result={"calib":edge_metrics(eca,eca_p),"test":edge_metrics(ete,ete_p),"best_iteration":int(edge.best_iteration_)}
# decile lift on TEST, ranking metric rather than threshold tuning.
q=np.quantile(ete_p,.90); top=ete_p>=q
edge_result["test_top_decile"]={
  "n":int(top.sum()),"coverage":float(top.mean()),
  "clean_edge_rate":float(ete[top].mean()) if top.any() else None,
  "baseline_clean_edge_rate":float(ete.mean()),
  "lift":float(ete[top].mean()/ete.mean()) if top.any() and ete.mean()>0 else None,
  "mean_signed_ret_atr":float(test.loc[top,"signed_ret_8h_atr"].mean()) if top.any() else None
}
edge.booster_.save_model(str(OUT/"clean_edge_model.txt"))

# Per-event-type diagnostics on TEST.
rows=[]
for et,g in test.groupby("event_type"):
    idx=g.index.to_numpy()
    # test index is RangeIndex after concat; if not, align using positions
    pos=test.index.get_indexer(idx)
    pp=pte[pos]
    pr=pp.argmax(axis=1)
    yy=g.event_outcome.map(OUTCOME2ID).astype(int).to_numpy()
    rows.append({
      "event_type":et,"n":len(g),
      "followthrough_rate":float((g.event_outcome=="FOLLOWTHROUGH").mean()),
      "failure_rate":float((g.event_outcome=="FAILURE").mean()),
      "accuracy":float((pr==yy).mean()),
      "balanced_accuracy":float(balanced_accuracy_score(yy,pr)) if len(np.unique(yy))>1 else np.nan,
      "mean_signed_ret_atr":float(g.signed_ret_8h_atr.mean())
    })
pd.DataFrame(rows).sort_values("n",ascending=False).to_csv(OUT/"per_event_type_test.csv",index=False)

# Feature importance
imp=pd.DataFrame({"feature":features_all,
                  "gain":clf.booster_.feature_importance(importance_type="gain"),
                  "split":clf.booster_.feature_importance(importance_type="split")}).sort_values("gain",ascending=False)
imp.to_csv(OUT/"feature_importance.csv",index=False)

counts={}
for sp,d in [("TRAIN",train),("CALIB",calib),("TEST",test)]:
    counts[sp]={"events":int(len(d)),"outcomes":d.event_outcome.value_counts().astype(int).to_dict(),
                "event_types":d.event_type.value_counts().astype(int).to_dict()}

summary={
 "version":"R15.6",
 "architecture":"non-overlapping causal market-event intelligence",
 "cooldown_bars_15m":COOLDOWN_BARS,
 "cooldown_hours":COOLDOWN_BARS*.25,
 "raw_candles":int(A.candles.sum()),
 "all_events":int(A.events.sum()),
 "train_events":int(len(train)),"calib_events":int(len(calib)),"test_events":int(len(test)),
 "outer_holdout_events":int(A.outer_holdout_events.sum()),
 "feature_pool_before_prune":int(len([c for c in train.columns if c.startswith(BASE_FEATURE_PREFIX) or TECH_MARK in c])),
 "features_after_train_only_prune":int(len(features)),
 "event_context_features":int(len(extra)),
 "pruned_high_correlation_or_quality":int(len(pruned)),
 "counts":counts,
 "event_outcome_test":multi,
 "followthrough_selection_test":selected,
 "clean_edge_model":edge_result,
 "outer_holdout_opened":False,
 "outer_holdout_start":"2026-07-01T00:00:00Z",
 "leakage_controls":[
   "event triggers are causal",
   "8h cooldown reduces overlapping event labels",
   "feature pruning learned on TRAIN only",
   "threshold selected on CALIB only",
   "TEST is 2026Q2",
   "OUTER_HOLDOUT outcomes are blank and unused"
 ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
(OUT/"feature_manifest.json").write_text(json.dumps({"features":features_all,"event_types":event_types,"outcomes":OUTCOMES},indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
print("\nTOP FEATURES\n"+imp.head(35).to_string(index=False),flush=True)
