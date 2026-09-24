#!/usr/bin/env python3
"""R16.6 Multi-Tier Opportunity Engine

Frozen economic core:
- LONG only
- Donchian 55 breakout
- EMA50 > EMA200
- stop 2 ATR
- target 6 ATR
- max hold 30 x 4h bars
- max 5 simultaneous positions
- 25% notional cap

Hierarchical signal tiers:
CORE      : ADX>=30, breadth>=55%, BTC STRICT, risk 0.25%
STANDARD  : ADX>=25, breadth>=45%, BTC STRICT, risk 0.20%
EXPANSION : ADX>=20, breadth>=45%, BTC SOFT,   risk 0.10%

A candidate is assigned to the highest tier it qualifies for.
Re-entry suppression is applied only after a candidate is actually accepted by the tier engine.

Selection / robustness uses only data < 2026-07-01.
July and August 2026 are diagnostics only; already consumed and not used to tune this policy.
No ML.
"""
from __future__ import annotations
import json, heapq
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_6_multi_tier")
OUT.mkdir(parents=True,exist_ok=True)

DEV_END=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
JUL_END=int(pd.Timestamp("2026-08-01T00:00:00Z").timestamp()*1000)
AUG_END=int(pd.Timestamp("2026-09-01T00:00:00Z").timestamp()*1000)

BASE_COST=.0016
STRESS_COST=.0021
STOP_ATR=2.0
TARGET_ATR=6.0
HOLD=30
START_CAP=10_000.0
MAX_POS=5
NOTIONAL_CAP=.25
SEED=1660

TIERS=[
    {"name":"CORE","adx":30.0,"breadth":.55,"btc":"STRICT","risk":.0025},
    {"name":"STANDARD","adx":25.0,"breadth":.45,"btc":"STRICT","risk":.0020},
    {"name":"EXPANSION","adx":20.0,"breadth":.45,"btc":"SOFT","risk":.0010},
]

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def load(sym):
    x=pd.read_csv(ROOT/f"{sym}.csv.gz")
    for c in ["open_time","open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    h,l,c=x.high,x.low,x.close;pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.0),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.0),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x["atr"]=atr;x["adx"]=rma(dx,14)
    x["ema50"]=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x["ema200"]=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x["ret42"]=c/c.shift(42)-1
    x["hi55"]=h.shift(1).rolling(55,min_periods=55).max()
    return x

print("Loading 4h data...",flush=True)
F={s:load(s) for s in SYMBOLS}

# Causal market context from completed signal candle.
parts=[]
for sym,z in F.items():
    ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),
                  index=z.open_time.astype("int64"),name=sym)
    parts.append(ser[~ser.index.duplicated()])
breadth=pd.concat(parts,axis=1).mean(axis=1,skipna=True)

btc=F["BTCUSDT"].set_index("open_time")
CTX=pd.DataFrame(index=breadth.index)
CTX["breadth"]=breadth
CTX["btc_strict"]=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0)).reindex(CTX.index).fillna(False)
CTX["btc_soft"]=((btc.close>btc.ema200)&(btc.ret42>0)).reindex(CTX.index).fillna(False)

def tier_for(adx,br,strict,soft,policy="MULTI"):
    if policy=="CORE":
        return TIERS[0] if adx>=30 and br>=.55 and strict else None
    if policy=="STANDARD":
        return {"name":"STANDARD","adx":25.0,"breadth":.45,"btc":"STRICT","risk":.0020} if adx>=25 and br>=.45 and strict else None
    if policy=="EXPANSION_ONLY":
        return {"name":"EXPANSION","adx":20.0,"breadth":.45,"btc":"SOFT","risk":.0010} if adx>=20 and br>=.45 and soft else None
    for t in TIERS:
        btc_ok = strict if t["btc"]=="STRICT" else soft
        if adx>=t["adx"] and br>=t["breadth"] and btc_ok:
            return t
    return None

def simulate_symbol(sym,cost,policy="MULTI"):
    z=F[sym];c=z.close;prev=c.shift()
    breakout=(c>z.hi55)&(prev<=z.hi55.shift())&(z.ema50>z.ema200)
    rows=[];last_exit=-1
    for i in np.flatnonzero(np.asarray(breakout.fillna(False))):
        if i<=last_exit or i>=len(z)-1: continue
        ts=int(z.open_time.iloc[i])
        if ts not in CTX.index: continue
        adx=float(z.adx.iloc[i]);br=float(CTX.loc[ts,"breadth"])
        strict=bool(CTX.loc[ts,"btc_strict"]);soft=bool(CTX.loc[ts,"btc_soft"])
        t=tier_for(adx,br,strict,soft,policy)
        if t is None: continue
        atr=float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr<=0: continue
        ei=i+1;entry=float(z.open.iloc[ei]);stop=entry-STOP_ATR*atr;target=entry+TARGET_ATR*atr
        end=min(ei+HOLD-1,len(z)-1);exit_px=float(z.close.iloc[end]);xi=end;reason="TIME"
        for j in range(ei,end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=lo<=stop;ht=hi>=target
            if hs and ht: exit_px=stop;xi=j;reason="STOP_AMBIGUOUS";break
            if hs: exit_px=stop;xi=j;reason="STOP";break
            if ht: exit_px=target;xi=j;reason="TARGET";break
        gross=(exit_px-entry)/entry
        rows.append({
            "symbol":sym,"tier":t["name"],"risk":t["risk"],
            "signal_time":ts,"entry_time":int(z.open_time.iloc[ei]),"exit_time":int(z.open_time.iloc[xi])+4*3600_000,
            "adx":adx,"breadth":br,"btc_strict":strict,"btc_soft":soft,
            "entry":entry,"atr":atr,"stop_pct":STOP_ATR*atr/entry,
            "gross_pct":gross,"net_pct":gross-2*cost,"reason":reason
        })
        last_exit=xi
    return rows

def engine(cost,policy):
    rows=[]
    for s in SYMBOLS: rows.extend(simulate_symbol(s,cost,policy))
    return pd.DataFrame(rows)

print("Simulating engines...",flush=True)
ENG={}
for costname,cost in [("base",BASE_COST),("stress",STRESS_COST)]:
    for policy in ["CORE","STANDARD","MULTI"]:
        ENG[(costname,policy)]=engine(cost,policy)

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def boot_week(d,n=1500):
    if len(d)<30:return 0.0
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit="ms",utc=True)
    x["week"]=(dt-dt.dt.weekday.astype("timedelta64[D]")).dt.floor("D")
    w=x.groupby("week").net_pct.sum().to_numpy(float)
    if len(w)<10:return 0.0
    rng=np.random.default_rng(SEED)
    vals=np.empty(n)
    for i in range(n): vals[i]=rng.choice(w,len(w),replace=True).mean()
    return float((vals>0).mean())

def trade_stats(d,start=None,end=DEV_END):
    x=d.copy()
    if start is not None:x=x[x.entry_time>=start]
    if end is not None:x=x[x.entry_time<end]
    if x.empty:return {"trades":0}
    r=x.net_pct.to_numpy(float)
    dt=pd.to_datetime(x.entry_time,unit="ms",utc=True)
    q=x.assign(q=dt.dt.to_period("Q").astype(str)).groupby("q").net_pct.mean()
    y=x.assign(y=dt.dt.year).groupby("y").net_pct.mean()
    sy=x.groupby("symbol").net_pct.sum();pos=sy.clip(lower=0)
    months=pd.period_range("2024-01","2026-06",freq="M").astype(str)
    actual=set(dt.dt.to_period("M").astype(str))
    return {
      "trades":int(len(x)),"avg":float(r.mean()),"pf":pf(r),"win_rate":float((r>0).mean()),
      "positive_quarter_rate":float((q>0).mean()),"all_years_positive":bool((y>0).all()),
      "weekly_prob_positive":boot_week(x),
      "active_month_rate":float(sum(m in actual for m in months)/len(months)),
      "median_trades_active_month":float(pd.Series(dt.dt.to_period("M").astype(str)).value_counts().median()),
      "max_positive_symbol_share":float(pos.max()/pos.sum()) if pos.sum()>0 else 1.0,
      "tier_counts":x.tier.value_counts().to_dict() if "tier" in x else {}
    }

def portfolio(d,start=None,end=DEV_END):
    x=d.copy()
    if start is not None:x=x[x.entry_time>=start]
    if end is not None:x=x[x.entry_time<end]
    if x.empty:return {"start":START_CAP,"end":START_CAP,"return":0.0,"max_dd":0.0,"accepted":0,"rejected":0,"tier_accepted":{}}
    x=x.sort_values(["entry_time","tier","symbol"]).reset_index(drop=True)
    eq=START_CAP;heap=[];active=set();curve=[eq];uid=0;accepted=0;rejected=0;tieracc={}
    def settle(until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;active.discard(sym);curve.append(eq)
    for r in x.itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:
            rejected+=1;continue
        stop_pct=max(float(r.stop_pct),1e-6)
        risk=float(r.risk)
        notional=min(eq*NOTIONAL_CAP,eq*risk/stop_pct)
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));active.add(r.symbol);uid+=1;accepted+=1
        tieracc[r.tier]=tieracc.get(r.tier,0)+1
    settle(10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {"start":START_CAP,"end":float(eq),"return":float(eq/START_CAP-1),
            "max_dd":float(-dd.min()),"accepted":accepted,"rejected":rejected,"tier_accepted":tieracc}

rows=[]
for policy in ["CORE","STANDARD","MULTI"]:
    b=ENG[("base",policy)];s=ENG[("stress",policy)]
    mb=trade_stats(b);ms=trade_stats(s)
    pb=portfolio(b);ps=portfolio(s)
    passed=bool(
      mb.get("trades",0)>=400 and mb.get("pf",0)>=1.15 and ms.get("pf",0)>=1.10 and
      mb.get("positive_quarter_rate",0)>=.65 and mb.get("all_years_positive",False) and
      mb.get("weekly_prob_positive",0)>=.95 and mb.get("max_positive_symbol_share",1)<=.25 and
      pb.get("return",0)>0 and ps.get("return",0)>0 and pb.get("max_dd",1)<=.20 and ps.get("max_dd",1)<=.25
    )
    july_b=trade_stats(b,DEV_END,JUL_END);aug_b=trade_stats(b,JUL_END,AUG_END)
    july_p=portfolio(b,DEV_END,JUL_END);aug_p=portfolio(b,JUL_END,AUG_END)
    rows.append({
      "policy":policy,
      "base_stats":mb,"stress_stats":ms,
      "base_portfolio":pb,"stress_portfolio":ps,
      "passes_gate":passed,
      "july_diag":{"trades":july_b,"portfolio":july_p},
      "august_diag":{"trades":aug_b,"portfolio":aug_p}
    })

# Extra monthly return table for MULTI development.
m=ENG[("base","MULTI")].copy()
m=m[m.entry_time<DEV_END]
m["month"]=pd.to_datetime(m.entry_time,unit="ms",utc=True).dt.to_period("M").astype(str)
month_rows=[]
for mo,g in m.groupby("month"):
    p=portfolio(g,start=None,end=None)
    month_rows.append({"month":mo,"signals":len(g),"portfolio_return":p["return"],"max_dd":p["max_dd"],"tier_counts":json.dumps(g.tier.value_counts().to_dict())})
pd.DataFrame(month_rows).to_csv(OUT/"multi_monthly.csv",index=False)

# Persist trades.
for (costname,policy),df in ENG.items():
    if len(df): df.to_parquet(OUT/f"{costname}_{policy.lower()}_trades.parquet",index=False,compression="zstd")

summary={
 "version":"R16.6",
 "architecture":"hierarchical CORE/STANDARD/EXPANSION opportunity engine",
 "tiers":TIERS,
 "frozen_geometry":{"donchian":55,"stop_atr":STOP_ATR,"target_atr":TARGET_ATR,"hold_4h_bars":HOLD},
 "portfolio":{"max_positions":MAX_POS,"notional_cap":NOTIONAL_CAP},
 "results":rows,
 "development_cutoff":"2026-07-01",
 "july_august_used_for_selection":False,
 "note":"July/August diagnostics are already consumed and cannot serve as fresh validation.",
 "no_ml":True
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
