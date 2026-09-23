#!/usr/bin/env python3
"""R15.7 - Event Economic Backtest.

Uses R15.6 event model and raw Binance 15m candles.
CALIB (2026Q1): chooses stop/target/max-hold only.
TEST  (2026Q2): untouched economic evaluation.
OUTER_HOLDOUT >= 2026-07-01 is never backtested.

Execution:
- signal known at event candle close;
- enter NEXT 15m candle open;
- ATR levels frozen from signal candle;
- conservative intrabar rule: if stop & target both hit, stop wins;
- base one-way cost = 0.16%; stress = 0.21%;
- max 10 simultaneous positions, 10% equity per position, no same-symbol overlap.
"""
from __future__ import annotations
import json, math, heapq, gc
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

EVROOT=Path("r15_regime_lab/model_r15_6/events")
MODELROOT=Path("r15_regime_lab/model_r15_6")
RAW=Path("r15_regime_lab/history/15m")
OUT=Path("r15_regime_lab/backtest_r15_7")
OUT.mkdir(parents=True,exist_ok=True)

FOLLOW_ID=2
FOLLOW_THRESHOLD=0.45  # frozen by R15.6 CALIB
BASE_COST=0.0016
STRESS_COST=0.0021
START_CAPITAL=10_000.0
MAX_POSITIONS=10
SLOT_FRAC=0.10
BAR_MS=900_000

STOPS=[1.0,1.25,1.5,1.75,2.0,2.5]
TARGETS=[1.25,1.5,1.75,2.0,2.5,3.0,3.5]
HOLDS=[16,24,32]  # 4h, 6h, 8h

manifest=json.loads((MODELROOT/"feature_manifest.json").read_text())
FEATURES=manifest["features"]
EVENT_TYPES=manifest["event_types"]
clf=lgb.Booster(model_file=str(MODELROOT/"event_outcome_model.txt"))

def load_events(split):
    parts=[]
    for p in sorted(EVROOT.glob("*.parquet")):
        d=pd.read_parquet(p)
        d=d[d["split"].eq(split)].copy()
        if len(d):
            d["symbol"]=p.stem
            parts.append(d)
    x=pd.concat(parts,ignore_index=True)
    # Rebuild context features used by R15.6 model.
    x["event_direction_feature"]=x.event_direction.astype("float32")
    x["event_strength_feature"]=x.event_strength.astype("float32")
    for et in EVENT_TYPES:
        x["evt_"+et]=(x.event_type==et).astype("int8")
    for f in FEATURES:
        if f not in x.columns:x[f]=np.nan
    X=x[FEATURES].astype("float32").replace([np.inf,-np.inf],np.nan)
    p=clf.predict(X,num_iteration=clf.best_iteration)
    x["p_failure"]=p[:,0]; x["p_mixed"]=p[:,1]; x["p_follow"]=p[:,2]
    return x

def load_raw(sym):
    p=RAW/f"{sym}.csv.gz"
    x=pd.read_csv(p,usecols=["open_time","open","high","low","close","volume"])
    for c in ["open_time","open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    return x.dropna().sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)

RAW_CACHE={}
def raw(sym):
    if sym not in RAW_CACHE:RAW_CACHE[sym]=load_raw(sym)
    return RAW_CACHE[sym]

def one_trade(ev,stop_atr,target_atr,max_bars,cost):
    x=raw(ev["symbol"])
    # Event candle closes at available_time. Next candle opens at same timestamp.
    pos=np.searchsorted(x.open_time.to_numpy(),int(ev["available_time"]))
    if pos>=len(x) or int(x.open_time.iloc[pos])!=int(ev["available_time"]):
        return None
    event_pos=pos-1
    if event_pos<0:return None
    event_close=float(x.close.iloc[event_pos])
    atr_pct=float(ev.get("15m_atr_pct",np.nan))
    if not np.isfinite(atr_pct) or atr_pct<=0:return None
    atr=event_close*atr_pct
    entry=float(x.open.iloc[pos])
    direction=int(ev["event_direction"])
    if direction not in (-1,1):return None
    stop=entry-direction*stop_atr*atr
    target=entry+direction*target_atr*atr
    end=min(pos+max_bars-1,len(x)-1)
    exit_px=float(x.close.iloc[end]); reason="TIME"; exit_i=end
    for i in range(pos,end+1):
        hi=float(x.high.iloc[i]); lo=float(x.low.iloc[i])
        if direction>0:
            hit_stop=lo<=stop; hit_target=hi>=target
        else:
            hit_stop=hi>=stop; hit_target=lo<=target
        if hit_stop and hit_target:
            exit_px=stop; reason="STOP_AMBIGUOUS"; exit_i=i; break
        if hit_stop:
            exit_px=stop; reason="STOP"; exit_i=i; break
        if hit_target:
            exit_px=target; reason="TARGET"; exit_i=i; break
    gross=direction*(exit_px-entry)/entry
    net=gross-2*cost
    return {
      "symbol":ev["symbol"],"event_type":ev["event_type"],"direction":direction,
      "signal_time":int(ev["available_time"]-BAR_MS),"entry_time":int(x.open_time.iloc[pos]),
      "exit_time":int(x.open_time.iloc[exit_i])+BAR_MS,
      "entry":entry,"exit":exit_px,"atr_abs":atr,
      "stop_atr":stop_atr,"target_atr":target_atr,"max_bars":max_bars,
      "gross_pct":gross,"cost_pct":2*cost,"net_pct":net,"exit_reason":reason,
      "p_follow":float(ev["p_follow"]),"p_failure":float(ev["p_failure"]),"p_mixed":float(ev["p_mixed"])
    }

def trade_set(events,params,cost,filter_ai=True,long_only=False):
    st,tp,h=params
    d=events
    if filter_ai:d=d[d.p_follow>=FOLLOW_THRESHOLD]
    if long_only:d=d[d.event_direction>0]
    rows=[]
    for _,ev in d.iterrows():
        r=one_trade(ev,st,tp,h,cost)
        if r is not None:rows.append(r)
    return pd.DataFrame(rows)

def basic_metrics(t):
    if t.empty:return {"trades":0}
    r=t.net_pct.to_numpy()
    gp=float(r[r>0].sum()); gl=float(-r[r<0].sum())
    return {
      "trades":int(len(t)),"win_rate":float((r>0).mean()),
      "avg_net_pct":float(r.mean()),"median_net_pct":float(np.median(r)),
      "gross_profit_pct_sum":gp,"gross_loss_pct_sum":gl,
      "profit_factor":float(gp/gl) if gl>0 else None,
      "raw_compound_return":float(np.prod(1+r)-1),
      "target_rate":float(t.exit_reason.eq("TARGET").mean()),
      "stop_rate":float(t.exit_reason.str.startswith("STOP").mean()),
      "time_exit_rate":float(t.exit_reason.eq("TIME").mean())
    }

def calibrate(calib):
    rows=[]
    # AI gate fixed from prior R15.6 calibration; only exits are calibrated here.
    for st in STOPS:
      for tp in TARGETS:
        for h in HOLDS:
          t=trade_set(calib,(st,tp,h),BASE_COST,True,False)
          m=basic_metrics(t)
          if m.get("trades",0)<100:continue
          # Expectancy first, with small PF tie-breaker. No TEST information.
          pf=m["profit_factor"] if m["profit_factor"] is not None else 99
          score=m["avg_net_pct"] + 0.00005*min(pf,3)
          rows.append({"stop_atr":st,"target_atr":tp,"max_bars":h,"score":score,**m})
    g=pd.DataFrame(rows).sort_values(["score","profit_factor","trades"],ascending=False)
    g.to_csv(OUT/"calibration_exit_grid.csv",index=False)
    b=g.iloc[0]
    return (float(b.stop_atr),float(b.target_atr),int(b.max_bars)),b.to_dict()

def portfolio(t,start=START_CAPITAL,max_positions=MAX_POSITIONS,slot_frac=SLOT_FRAC):
    if t.empty:return pd.DataFrame(),{"start":start,"end":start,"return":0.0,"max_dd":0.0,"accepted":0,"rejected_capacity":0}
    trades=t.sort_values(["entry_time","p_follow"],ascending=[True,False]).reset_index(drop=True)
    equity=start
    open_heap=[] # (exit_time, id, pnl_abs, symbol, notional)
    active_symbols=set()
    curve=[{"time":int(trades.entry_time.min()),"equity":equity}]
    accepted=[]; rej=0; uid=0
    def settle(until):
        nonlocal equity
        while open_heap and open_heap[0][0]<=until:
            ex,ident,pnl,sym,notional=heapq.heappop(open_heap)
            equity+=pnl
            active_symbols.discard(sym)
            curve.append({"time":int(ex),"equity":equity})
    for row in trades.itertuples(index=False):
        settle(int(row.entry_time))
        if len(open_heap)>=max_positions or row.symbol in active_symbols:
            rej+=1; continue
        notional=equity*slot_frac
        pnl=notional*float(row.net_pct)
        heapq.heappush(open_heap,(int(row.exit_time),uid,pnl,row.symbol,notional))
        active_symbols.add(row.symbol)
        rr=row._asdict(); rr.update({"notional":notional,"pnl":pnl,"equity_at_entry":equity})
        accepted.append(rr); uid+=1
    settle(10**30)
    ec=pd.DataFrame(curve).sort_values("time")
    peak=ec.equity.cummax()
    dd=ec.equity/peak-1
    metrics={
      "start":start,"end":float(equity),"return":float(equity/start-1),
      "max_dd":float(-dd.min()),"accepted":len(accepted),"rejected_capacity":rej,
      "max_positions":max_positions,"slot_fraction":slot_frac
    }
    return pd.DataFrame(accepted),metrics

def scenario(events,params,cost,filter_ai,long_only,name):
    t=trade_set(events,params,cost,filter_ai,long_only)
    pt,pm=portfolio(t)
    bm=basic_metrics(pt if not pt.empty else t)
    result={"name":name,"cost_one_way":cost,"filter_ai":filter_ai,"long_only":long_only,
            "trade_metrics":bm,"portfolio":pm}
    if not pt.empty:
        pt.to_csv(OUT/f"{name}_trades.csv",index=False)
        # concentration
        c=pt.groupby("event_type").agg(trades=("net_pct","size"),avg_net=("net_pct","mean"),sum_net=("net_pct","sum")).sort_values("trades",ascending=False)
        c.to_csv(OUT/f"{name}_by_event_type.csv")
    return result

calib=load_events("CALIB")
test=load_events("TEST")
params,calib_best=calibrate(calib)
print("CALIB BEST",params,json.dumps(calib_best,default=float),flush=True)

scenarios=[]
scenarios.append(scenario(test,params,BASE_COST,True,False,"ai_directional_base"))
scenarios.append(scenario(test,params,STRESS_COST,True,False,"ai_directional_stress"))
scenarios.append(scenario(test,params,BASE_COST,False,False,"all_events_control"))
scenarios.append(scenario(test,params,BASE_COST,True,True,"ai_long_only_spot"))
scenarios.append(scenario(test,params,STRESS_COST,True,True,"ai_long_only_spot_stress"))

summary={
 "version":"R15.7",
 "period_test":"2026-04-01..2026-06-30",
 "execution":"next 15m open after signal; conservative stop-first if stop and target touch same candle",
 "capital":START_CAPITAL,"max_positions":MAX_POSITIONS,"slot_fraction":SLOT_FRAC,
 "followthrough_threshold":FOLLOW_THRESHOLD,
 "costs":{"base_one_way":BASE_COST,"stress_one_way":STRESS_COST},
 "calibration":{"period":"2026Q1","best_exit_params":{"stop_atr":params[0],"target_atr":params[1],"max_bars":params[2]},"best_metrics":calib_best},
 "scenarios":scenarios,
 "outer_holdout_opened":False,
 "outer_holdout_start":"2026-07-01T00:00:00Z",
 "notes":[
   "Short scenario is directional research using Binance Spot candles; live short execution would require margin/futures or another short-capable venue.",
   "Long-only scenario is the directly Spot-compatible variant.",
   "No TEST parameter tuning. Exit parameters chosen on CALIB only.",
   "OUTER_HOLDOUT is untouched."
 ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
