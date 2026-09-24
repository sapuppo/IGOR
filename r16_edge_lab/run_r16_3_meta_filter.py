#!/usr/bin/env python3
"""R16.3 - Meta Filter

Frozen baseline:
Signal: D55_A30_LONG_BREADTH
Geometry: stop 2 ATR / target 6 ATR / max hold 30 x 4h
Portfolio: 0.25% equity risk/trade, max 5 positions, 25% notional cap

ML is ONLY a meta-layer:
- train on completed baseline trades from 2024-2025
- calibrate gate on 2026Q1
- evaluate once on 2026Q2
- no data >= 2026-07-01

Heads:
1) classifier: probability trade net return > 0
2) regressor: expected net return

Final meta score = rank-average of classifier and regressor predictions.
CALIB chooses skip threshold from fixed coverage candidates.
"""
from __future__ import annotations
import json, heapq
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, average_precision_score, mean_absolute_error
from scipy.stats import spearmanr

ROOT=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_3_meta_filter")
OUT.mkdir(parents=True,exist_ok=True)

BASE_COST=.0016
STRESS_COST=.0021
END_MS=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
TRAIN_END=int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp()*1000)
CALIB_END=int(pd.Timestamp("2026-04-01T00:00:00Z").timestamp()*1000)

STOP_ATR=2.0
TARGET_ATR=6.0
HOLD=30
START_CAP=10_000.0
RISK=.0025
MAX_POS=5
NOTIONAL_CAP=.25
SEED=1630

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def rsi14(c):
    d=c.diff();g=rma(d.clip(lower=0),14);l=rma((-d).clip(lower=0),14)
    return 100-(100/(1+g/l.replace(0,np.nan)))

def load(sym):
    p=ROOT/f"{sym}.csv.gz"
    x=pd.read_csv(p)
    for c in ["open_time","open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time")
    x=x[x.open_time<END_MS].reset_index(drop=True)
    h,l,c,v=x.high,x.low,x.close,x.volume
    pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.0),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.0),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x["atr"]=atr;x["adx"]=rma(dx,14)
    x["ema20"]=c.ewm(span=20,adjust=False,min_periods=20).mean()
    x["ema50"]=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x["ema200"]=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x["rsi14"]=rsi14(c)
    x["ret1"]=c.pct_change()
    x["ret6"]=c.pct_change(6)
    x["ret18"]=c.pct_change(18)
    x["ret42"]=c.pct_change(42)
    x["rv18"]=x.ret1.rolling(18,min_periods=12).std()
    x["volz40"]=(v-v.rolling(40,min_periods=30).mean())/v.rolling(40,min_periods=30).std().replace(0,np.nan)
    x["hi55"]=h.shift(1).rolling(55,min_periods=55).max()
    x["lo20"]=l.shift(1).rolling(20,min_periods=20).min()
    x["atr_pct"]=atr/c.replace(0,np.nan)
    x["ema50_200_atr"]=(x.ema50-x.ema200)/atr.replace(0,np.nan)
    x["ema20_50_atr"]=(x.ema20-x.ema50)/atr.replace(0,np.nan)
    x["break_strength"]=(c-x.hi55)/atr.replace(0,np.nan)
    x["dist_low20_atr"]=(c-x.lo20)/atr.replace(0,np.nan)
    return x

print("Loading data...",flush=True)
F={s:load(s) for s in SYMBOLS}

# causal breadth
parts=[]
for sym,z in F.items():
    ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),
                  index=z.open_time.astype("int64"),name=sym)
    parts.append(ser[~ser.index.duplicated()])
B=pd.concat(parts,axis=1)
breadth=B.mean(axis=1,skipna=True)
breadth_slope6=breadth-breadth.shift(6)
breadth_slope18=breadth-breadth.shift(18)
dispersion=pd.DataFrame({sym:pd.Series(z.ret6.values,index=z.open_time.astype("int64")) for sym,z in F.items()}).std(axis=1,skipna=True)

btc=F["BTCUSDT"].set_index("open_time")
btc_up=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0))
CTX=pd.DataFrame(index=breadth.index)
CTX["breadth"]=breadth
CTX["breadth_slope6"]=breadth_slope6
CTX["breadth_slope18"]=breadth_slope18
CTX["dispersion6"]=dispersion.reindex(CTX.index)
CTX["btc_up"]=btc_up.reindex(CTX.index).fillna(False)
for c in ["adx","atr_pct","ret1","ret6","ret18","ret42","rsi14","ema50_200_atr","volz40"]:
    CTX["btc_"+c]=btc[c].reindex(CTX.index)

FEATURES=[
 "adx","atr_pct","ret1","ret6","ret18","ret42","rv18","rsi14","volz40",
 "ema50_200_atr","ema20_50_atr","break_strength","dist_low20_atr",
 "rel_ret6_btc","rel_ret18_btc","rel_ret42_btc",
 "breadth","breadth_slope6","breadth_slope18","dispersion6",
 "btc_adx","btc_atr_pct","btc_ret1","btc_ret6","btc_ret18","btc_ret42",
 "btc_rsi14","btc_ema50_200_atr","btc_volz40"
]

def baseline_trades(sym,cost):
    z=F[sym];c=z.close;prev=c.shift()
    signal=(c>z.hi55)&(prev<=z.hi55.shift())&(z.ema50>z.ema200)&(z.adx>=30)
    rows=[];last_exit=-1
    for i in np.flatnonzero(np.asarray(signal.fillna(False))):
        if i<=last_exit or i>=len(z)-1: continue
        ts=int(z.open_time.iloc[i])
        if ts not in CTX.index:continue
        ctx=CTX.loc[ts]
        if not bool(ctx.btc_up) or float(ctx.breadth)<.55:continue
        atr=float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr<=0:continue
        ei=i+1;entry=float(z.open.iloc[ei]);stop=entry-STOP_ATR*atr;target=entry+TARGET_ATR*atr
        end=min(ei+HOLD-1,len(z)-1);exit_px=float(z.close.iloc[end]);reason="TIME";xi=end
        for j in range(ei,end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
            hs=lo<=stop;ht=hi>=target
            if hs and ht:exit_px=stop;reason="STOP_AMBIGUOUS";xi=j;break
            if hs:exit_px=stop;reason="STOP";xi=j;break
            if ht:exit_px=target;reason="TARGET";xi=j;break
        gross=(exit_px-entry)/entry
        row={
          "symbol":sym,"signal_time":ts,"entry_time":int(z.open_time.iloc[ei]),"exit_time":int(z.open_time.iloc[xi]),
          "entry":entry,"atr":atr,"stop_pct":STOP_ATR*atr/entry,
          "gross_pct":gross,"net_pct":gross-2*cost,"reason":reason
        }
        # asset features at signal
        for f in ["adx","atr_pct","ret1","ret6","ret18","ret42","rv18","rsi14","volz40",
                  "ema50_200_atr","ema20_50_atr","break_strength","dist_low20_atr"]:
            row[f]=float(z[f].iloc[i]) if np.isfinite(z[f].iloc[i]) else np.nan
        row["rel_ret6_btc"]=row["ret6"]-float(ctx.btc_ret6)
        row["rel_ret18_btc"]=row["ret18"]-float(ctx.btc_ret18)
        row["rel_ret42_btc"]=row["ret42"]-float(ctx.btc_ret42)
        for f in ["breadth","breadth_slope6","breadth_slope18","dispersion6",
                  "btc_adx","btc_atr_pct","btc_ret1","btc_ret6","btc_ret18","btc_ret42",
                  "btc_rsi14","btc_ema50_200_atr","btc_volz40"]:
            row[f]=float(ctx[f]) if np.isfinite(ctx[f]) else np.nan
        rows.append(row);last_exit=xi
    return rows

base=[]
stress=[]
for sym in SYMBOLS:
    base.extend(baseline_trades(sym,BASE_COST))
    stress.extend(baseline_trades(sym,STRESS_COST))
D=pd.DataFrame(base)
DS=pd.DataFrame(stress)
D=D.sort_values("entry_time").reset_index(drop=True)
DS=DS.sort_values("entry_time").reset_index(drop=True)

def split_of(t):
    if t<TRAIN_END:return "TRAIN"
    if t<CALIB_END:return "CALIB"
    return "TEST"
D["split"]=[split_of(x) for x in D.entry_time]
DS["split"]=[split_of(x) for x in DS.entry_time]
D["y_win"]=(D.net_pct>0).astype(int)
D["y_net"]=D.net_pct.clip(-.25,.35)

print(D.groupby("split").size().to_dict(),flush=True)

X=D[FEATURES].replace([np.inf,-np.inf],np.nan).astype("float32")
tr=D.split.eq("TRAIN");ca=D.split.eq("CALIB");te=D.split.eq("TEST")

clf=lgb.LGBMClassifier(
    objective="binary",n_estimators=500,learning_rate=.025,num_leaves=7,max_depth=3,
    min_child_samples=25,colsample_bytree=.80,subsample=.85,subsample_freq=1,
    reg_alpha=.5,reg_lambda=2.0,random_state=SEED,n_jobs=4,verbosity=-1)
clf.fit(X[tr],D.loc[tr,"y_win"],eval_set=[(X[ca],D.loc[ca,"y_win"])],
        eval_metric="binary_logloss",callbacks=[lgb.early_stopping(50,verbose=False),lgb.log_evaluation(0)])

reg=lgb.LGBMRegressor(
    objective="huber",n_estimators=500,learning_rate=.025,num_leaves=7,max_depth=3,
    min_child_samples=25,colsample_bytree=.80,subsample=.85,subsample_freq=1,
    reg_alpha=.5,reg_lambda=2.0,random_state=SEED+1,n_jobs=4,verbosity=-1)
reg.fit(X[tr],D.loc[tr,"y_net"],eval_set=[(X[ca],D.loc[ca,"y_net"])],
        eval_metric="l1",callbacks=[lgb.early_stopping(50,verbose=False),lgb.log_evaluation(0)])

D["p_win"]=clf.predict_proba(X)[:,1]
D["pred_net"]=reg.predict(X)

# Rank-average scores independently by split to avoid scale drift.
D["score"]=np.nan
for sp,g in D.groupby("split"):
    idx=g.index
    rw=g.p_win.rank(pct=True)
    rr=g.pred_net.rank(pct=True)
    D.loc[idx,"score"]=.5*rw+.5*rr

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def metrics(d,col="net_pct"):
    if d.empty:return {"trades":0}
    r=d[col].to_numpy(float)
    return {"trades":int(len(d)),"avg":float(r.mean()),"median":float(np.median(r)),
            "pf":pf(r),"win_rate":float((r>0).mean())}

def portfolio(d,risk_mult_col=None,cost_stress=False):
    if d.empty:return {"end":START_CAP,"return":0.0,"max_dd":0.0,"accepted":0,"rejected":0}
    eq=START_CAP;heap=[];active=set();curve=[eq];uid=0;accepted=0;rejected=0
    def settle(until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;active.discard(sym);curve.append(eq)
    for r in d.sort_values(["entry_time","score"],ascending=[True,False]).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:
            rejected+=1;continue
        mult=float(getattr(r,risk_mult_col)) if risk_mult_col else 1.0
        stop_pct=max(float(r.stop_pct),1e-6)
        notional=min(eq*NOTIONAL_CAP,eq*RISK*mult/stop_pct)
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));active.add(r.symbol);uid+=1;accepted+=1
    settle(10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {"end":float(eq),"return":float(eq/START_CAP-1),"max_dd":float(-dd.min()),
            "accepted":accepted,"rejected":rejected}

# Model diagnostics
def diagnostics(mask):
    y=D.loc[mask,"y_win"].to_numpy()
    p=D.loc[mask,"p_win"].to_numpy()
    pred=D.loc[mask,"pred_net"].to_numpy()
    actual=D.loc[mask,"net_pct"].to_numpy()
    return {
      "n":int(mask.sum()),
      "classifier_roc_auc":float(roc_auc_score(y,p)) if len(np.unique(y))>1 else None,
      "classifier_pr_auc":float(average_precision_score(y,p)) if len(np.unique(y))>1 else None,
      "reg_mae":float(mean_absolute_error(actual,pred)),
      "reg_spearman":float(spearmanr(actual,pred,nan_policy="omit").statistic)
    }

# CALIB gate candidates by score percentile / coverage.
cal=D[ca].copy()
coverages=[1.0,.80,.70,.60,.50,.40]
gate_rows=[]
for cov in coverages:
    if cov>=1:thr=-np.inf
    else:thr=float(cal.score.quantile(1-cov))
    sub=cal[cal.score>=thr]
    m=metrics(sub)
    # reward expectancy and PF while keeping coverage; minimum 40%.
    obj=m["avg"] + .0005*max(0,(m["pf"] or 0)-1) + .0002*cov
    gate_rows.append({"coverage_target":cov,"threshold":thr,"actual_coverage":len(sub)/len(cal),**m,"objective":obj})
G=pd.DataFrame(gate_rows).sort_values(["objective","pf"],ascending=False)
G.to_csv(OUT/"calib_gate_grid.csv",index=False)

# Rule: do not allow filter unless CALIB improves baseline PF AND avg with >=40% coverage.
base_cal=metrics(cal)
eligible=G[(G.trades>=max(20,int(.40*len(cal))))&(G.avg>=base_cal["avg"])&(G.pf>=base_cal["pf"])]
if len(eligible):
    chosen=eligible.iloc[0]
else:
    chosen=G[G.coverage_target.eq(1.0)].iloc[0]
threshold=float(chosen.threshold)

# Risk tier from same CALIB distribution; only active if filtering passed.
filter_active=bool(np.isfinite(threshold))
cal_selected=cal[cal.score>=threshold] if filter_active else cal
# high score gets normal risk; lower accepted tier gets half risk
hi_thr=float(cal_selected.score.quantile(.60)) if filter_active and len(cal_selected)>10 else -np.inf

def apply_policy(df):
    z=df.copy()
    if filter_active:
        z=z[z.score>=threshold].copy()
    z["risk_mult"]=np.where(z.score>=hi_thr,1.0,.5) if filter_active else 1.0
    return z

test=D[te].copy()
test_policy=apply_policy(test)
test_base=test.copy()

# exact stress TEST rows aligned by symbol+entry
keycols=["symbol","entry_time"]
test_stress=DS[DS.split.eq("TEST")].merge(test_policy[keycols+["score","risk_mult"]],on=keycols,how="inner")

# Ensure portfolio function sees score
if "score" not in test_stress:test_stress["score"]=0.0

summary={
 "version":"R16.3",
 "baseline":"D55_A30_LONG_BREADTH + S2_T6_H30",
 "features":FEATURES,
 "splits":{
   "train":"2024-01-01..2025-12-31",
   "calib":"2026-01-01..2026-03-31",
   "test":"2026-04-01..2026-06-30"
 },
 "rows":D.groupby("split").size().to_dict(),
 "model_diagnostics":{"calib":diagnostics(ca),"test":diagnostics(te)},
 "calib_baseline":base_cal,
 "calib_gate_selected":chosen.to_dict(),
 "filter_active":filter_active,
 "threshold":threshold if np.isfinite(threshold) else None,
 "high_risk_threshold":hi_thr if np.isfinite(hi_thr) else None,
 "test":{
   "baseline_trade_metrics":metrics(test_base),
   "meta_trade_metrics":metrics(test_policy),
   "baseline_portfolio":portfolio(test_base),
   "meta_portfolio":portfolio(test_policy,"risk_mult"),
   "meta_stress_trade_metrics":metrics(test_stress),
   "meta_stress_portfolio":portfolio(test_stress,"risk_mult")
 },
 "comparison":{
   "trade_avg_delta":float(metrics(test_policy)["avg"]-metrics(test_base)["avg"]),
   "pf_delta":float((metrics(test_policy)["pf"] or 0)-(metrics(test_base)["pf"] or 0)),
   "portfolio_return_delta":float(portfolio(test_policy,"risk_mult")["return"]-portfolio(test_base)["return"]),
   "max_dd_delta":float(portfolio(test_policy,"risk_mult")["max_dd"]-portfolio(test_base)["max_dd"])
 },
 "advancement_rule":"Meta-filter advances only if TEST preserves positive expectancy and improves PF or drawdown without materially reducing portfolio return.",
 "outer_holdout_opened":False,
 "notes":[
   "ML cannot create trades; it only filters/sizes deterministic baseline trades.",
   "All features are computed on completed signal candles only.",
   "Gate threshold is selected on CALIB only.",
   "Q2 2026 is development validation because it has been inspected by prior R15 research.",
   "No data >= 2026-07-01 is used."
 ]
}

# Feature importance
imp=pd.DataFrame({
 "feature":FEATURES,
 "clf_gain":clf.booster_.feature_importance(importance_type="gain"),
 "reg_gain":reg.booster_.feature_importance(importance_type="gain")
}).sort_values("clf_gain",ascending=False)
imp.to_csv(OUT/"feature_importance.csv",index=False)
D.to_parquet(OUT/"baseline_trades_scored.parquet",index=False,compression="zstd")
test_policy.to_csv(OUT/"test_meta_trades.csv",index=False)
test_stress.to_csv(OUT/"test_meta_stress_trades.csv",index=False)
clf.booster_.save_model(str(OUT/"meta_classifier.txt"))
reg.booster_.save_model(str(OUT/"meta_regressor.txt"))
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
