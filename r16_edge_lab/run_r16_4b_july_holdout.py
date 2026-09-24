#!/usr/bin/env python3
"""R16.4B - July 2026 one-shot holdout check.

Frozen R16.2 champion:
- 4h LONG only
- Donchian 55 breakout
- EMA50 > EMA200
- ADX >= 30
- BTC macro trend up
- market breadth >= 55%
- stop 2 ATR
- target 6 ATR
- max hold 30 x 4h bars
- risk 0.25% equity/trade
- max 5 simultaneous positions
- 25% notional cap

Calendar test:
- fresh start 2026-07-01 00:00 UTC
- no carry-in positions
- only signals inside July
- any position still open at month end is liquidated at final July 4h close
- base and stress costs
- no tuning after seeing result
"""
from __future__ import annotations
import json, heapq
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_4b_july_holdout")
OUT.mkdir(parents=True,exist_ok=True)

START=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
END=int(pd.Timestamp("2026-08-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016
STRESS_COST=.0021
STOP_ATR=2.0
TARGET_ATR=6.0
HOLD=30
START_CAP=10_000.0
RISK=.0025
MAX_POS=5
NOTIONAL_CAP=.25

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def load(sym):
    p=ROOT/f"{sym}.csv.gz"
    x=pd.read_csv(p)
    for c in ["open_time","open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    h,l,c=x.high,x.low,x.close
    pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.0),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.0),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x["atr"]=atr
    x["adx"]=rma(dx,14)
    x["ema50"]=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x["ema200"]=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x["ret42"]=c/c.shift(42)-1
    x["hi55"]=h.shift(1).rolling(55,min_periods=55).max()
    return x

print("Loading frozen universe...",flush=True)
F={s:load(s) for s in SYMBOLS}

# Causal breadth / BTC regime from completed 4h candles.
parts=[]
for sym,z in F.items():
    ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),
                  index=z.open_time.astype("int64"),name=sym)
    parts.append(ser[~ser.index.duplicated()])
breadth=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
btc=F["BTCUSDT"].set_index("open_time")
btc_up=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0))
CTX=pd.DataFrame({"breadth":breadth})
CTX["btc_up"]=btc_up.reindex(CTX.index).fillna(False)

def build_trades(sym,cost):
    z=F[sym]
    c=z.close;prev=c.shift()
    sig=(c>z.hi55)&(prev<=z.hi55.shift())&(z.ema50>z.ema200)&(z.adx>=30)
    rows=[]
    for i in np.flatnonzero(np.asarray(sig.fillna(False))):
        ts=int(z.open_time.iloc[i])
        if not (START<=ts<END): continue
        if i>=len(z)-1: continue
        if ts not in CTX.index or not bool(CTX.loc[ts,"btc_up"]) or float(CTX.loc[ts,"breadth"])<.55: continue
        atr=float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr<=0: continue
        ei=i+1
        entry_time=int(z.open_time.iloc[ei])
        if entry_time>=END: continue
        entry=float(z.open.iloc[ei])
        stop=entry-STOP_ATR*atr
        target=entry+TARGET_ATR*atr
        # calendar month end: do not look at Sep candles
        month_candidates=np.flatnonzero((z.open_time.to_numpy()>=entry_time)&(z.open_time.to_numpy()<END))
        if len(month_candidates)==0: continue
        month_end_i=int(month_candidates[-1])
        natural_end=min(ei+HOLD-1,len(z)-1,month_end_i)
        exit_px=float(z.close.iloc[natural_end]);reason="MONTH_END" if natural_end==month_end_i else "TIME";xi=natural_end
        for j in range(ei,natural_end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
            hs=lo<=stop;ht=hi>=target
            if hs and ht: exit_px=stop;reason="STOP_AMBIGUOUS";xi=j;break
            if hs: exit_px=stop;reason="STOP";xi=j;break
            if ht: exit_px=target;reason="TARGET";xi=j;break
        gross=(exit_px-entry)/entry
        rows.append({
            "symbol":sym,"signal_time":ts,"entry_time":entry_time,"exit_time":int(z.open_time.iloc[xi])+4*3600_000,
            "entry":entry,"exit":exit_px,"atr":atr,"stop_pct":STOP_ATR*atr/entry,
            "gross_pct":gross,"net_pct":gross-2*cost,"reason":reason,
            "breadth":float(CTX.loc[ts,"breadth"])
        })
    return rows

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def portfolio(t):
    if t.empty:return {"start":START_CAP,"end":START_CAP,"return":0.0,"max_dd":0.0,"accepted":0,"rejected":0}
    t=t.sort_values(["entry_time","symbol"]).reset_index(drop=True)
    eq=START_CAP;heap=[];active=set();curve=[eq];uid=0;accepted=[];rejected=0
    def settle(until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap)
            eq+=pnl;active.discard(sym);curve.append(eq)
    for r in t.itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:
            rejected+=1;continue
        stop_pct=max(float(r.stop_pct),1e-6)
        notional=min(eq*NOTIONAL_CAP,eq*RISK/stop_pct)
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol))
        active.add(r.symbol);uid+=1
        z=r._asdict();z["notional"]=notional;z["pnl"]=pnl;accepted.append(z)
    settle(10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {"start":START_CAP,"end":float(eq),"return":float(eq/START_CAP-1),
            "max_dd":float(-dd.min()),"accepted":len(accepted),"rejected":rejected},pd.DataFrame(accepted)

def summarize(t):
    if t.empty:return {"signals":0}
    r=t.net_pct.to_numpy(float)
    return {"signals":int(len(t)),"win_rate":float((r>0).mean()),"avg_net_pct":float(r.mean()),
            "median_net_pct":float(np.median(r)),"profit_factor":pf(r),
            "target_rate":float(t.reason.eq("TARGET").mean()),
            "stop_rate":float(t.reason.str.startswith("STOP").mean()),
            "month_end_rate":float(t.reason.eq("MONTH_END").mean())}

base=[];stress=[]
for sym in SYMBOLS:
    base.extend(build_trades(sym,BASE_COST))
    stress.extend(build_trades(sym,STRESS_COST))
B=pd.DataFrame(base);S=pd.DataFrame(stress)
pb,ab=portfolio(B);ps,ass=portfolio(S)
if len(ab):ab.to_csv(OUT/"accepted_base.csv",index=False)
if len(ass):ass.to_csv(OUT/"accepted_stress.csv",index=False)
B.to_csv(OUT/"all_signals_base.csv",index=False)

summary={
 "version":"R16.4B",
 "test_type":"one-shot July 2026 calendar holdout",
 "period":"2026-07-01..2026-07-31 UTC",
 "fresh_start":True,
 "carry_in_positions":False,
 "forced_month_end_liquidation":True,
 "frozen_strategy":"D55_A30_LONG_BREADTH + S2_T6_H30",
 "portfolio":{"risk_per_trade":RISK,"max_positions":MAX_POS,"notional_cap":NOTIONAL_CAP},
 "base":{"trade_metrics":summarize(B),"portfolio":pb},
 "stress":{"trade_metrics":summarize(S),"portfolio":ps},
 "symbols_traded":sorted(ab.symbol.unique().tolist()) if len(ab) else [],
 "july_holdout_consumed":True,
 "august_holdout_consumed":False,
 "september_holdout_consumed":False,
 "notes":[
   "No parameter was changed after seeing July data.",
   "Only July signals are allowed; open positions are liquidated at the final July 4h close.",
   "No August candle is used for PnL.",
   "This consumes July 2026 as a future tuning holdout."
 ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
