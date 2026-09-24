#!/usr/bin/env python3
"""R16.1 - Trend Breakout Robustness.

Tests whether the R16.0 TB4H55 edge is a robust plateau rather than one lucky point.

No ML. 4h only. Parameter neighborhood:
- Donchian: 40 / 55 / 70
- ADX minimum: 20 / 25 / 30
- fixed economic geometry: stop 2.5 ATR, target 5 ATR, max hold 30 bars

Predeclared regime modes:
- BOTH_NONE: long + short, no market gate
- LONG_ONLY: longs only
- BOTH_BTC: direction must align with BTC 4h macro trend
- BOTH_BREADTH: BTC trend + market breadth confirmation
- LONG_BREADTH: long only + BTC/breadth confirmation

Uses block bootstrap by week, quarter/year diagnostics and overlapping-position portfolio simulation.
No data >= 2026-07-01.
"""
from __future__ import annotations
import json, heapq
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_1_trend_robustness")
OUT.mkdir(parents=True,exist_ok=True)

BASE_COST=.0016
STRESS_COST=.0021
END_MS=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
SEED=1610
START_CAP=10_000.0
MAX_POS=10
SLOT=.10

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']
DONS=[40,55,70]
ADXS=[20,25,30]
MODES=["BOTH_NONE","LONG_ONLY","BOTH_BTC","BOTH_BREADTH","LONG_BREADTH"]

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def load(sym):
    p=ROOT/f"{sym}.csv.gz"
    x=pd.read_csv(p)
    for c in ["open_time","open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time")
    x=x[x.open_time<END_MS].reset_index(drop=True)
    o,h,l,c=x.open,x.high,x.low,x.close
    pc=c.shift()
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
    for n in DONS:
        x[f"hi{n}"]=h.shift(1).rolling(n,min_periods=n).max()
        x[f"lo{n}"]=l.shift(1).rolling(n,min_periods=n).min()
    return x

print("Loading 4h frames...",flush=True)
F={s:load(s) for s in SYMBOLS}

# Market breadth: fraction of available symbols above EMA200.
cols=[]
for sym,z in F.items():
    q=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),index=z.open_time.astype("int64"),name=sym)
    cols.append(q[~q.index.duplicated()])
breadth=pd.concat(cols,axis=1).mean(axis=1,skipna=True)
btc=F["BTCUSDT"].set_index("open_time")
btc_up=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0))
btc_dn=((btc.close<btc.ema200)&(btc.ema50<btc.ema200)&(btc.ret42<0))
context=pd.DataFrame({"breadth":breadth})
context["btc_up"]=btc_up.reindex(context.index).fillna(False)
context["btc_dn"]=btc_dn.reindex(context.index).fillna(False)

def mode_ok(mode,direction,ts):
    if mode=="BOTH_NONE": return True
    if mode=="LONG_ONLY": return direction==1
    if ts not in context.index:return False
    row=context.loc[ts]
    if mode=="BOTH_BTC":
        return bool(row.btc_up) if direction==1 else bool(row.btc_dn)
    if mode=="BOTH_BREADTH":
        return (bool(row.btc_up) and row.breadth>=.55) if direction==1 else (bool(row.btc_dn) and row.breadth<=.45)
    if mode=="LONG_BREADTH":
        return direction==1 and bool(row.btc_up) and row.breadth>=.55
    return False

def simulate(sym,don,adx,mode,cost):
    z=F[sym]; c=z.close; prev=c.shift()
    long=(c>z[f"hi{don}"])&(prev<=z[f"hi{don}"].shift())&(z.ema50>z.ema200)&(z.adx>=adx)
    short=(c<z[f"lo{don}"])&(prev>=z[f"lo{don}"].shift())&(z.ema50<z.ema200)&(z.adx>=adx)
    sig=np.zeros(len(z),dtype=np.int8)
    sig[np.asarray(long.fillna(False))]=1; sig[np.asarray(short.fillna(False))]=-1
    rows=[];i=0
    while i<len(z)-1:
        d=int(sig[i]);atr=float(z.atr.iloc[i]) if np.isfinite(z.atr.iloc[i]) else np.nan
        ts=int(z.open_time.iloc[i])
        if d==0 or not np.isfinite(atr) or atr<=0 or not mode_ok(mode,d,ts):
            i+=1;continue
        ei=i+1;entry=float(z.open.iloc[ei]);stop=entry-d*2.5*atr;target=entry+d*5.0*atr
        end=min(ei+30-1,len(z)-1); exit_px=float(z.close.iloc[end]);reason="TIME";xi=end
        for j in range(ei,end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
            hs=(lo<=stop) if d>0 else (hi>=stop)
            ht=(hi>=target) if d>0 else (lo<=target)
            if hs and ht: exit_px=stop;reason="STOP_AMBIGUOUS";xi=j;break
            if hs: exit_px=stop;reason="STOP";xi=j;break
            if ht: exit_px=target;reason="TARGET";xi=j;break
        gross=d*(exit_px-entry)/entry
        rows.append({"symbol":sym,"don":don,"adx":adx,"mode":mode,"direction":d,
                     "signal_time":ts,"entry_time":int(z.open_time.iloc[ei]),"exit_time":int(z.open_time.iloc[xi]),
                     "gross_pct":gross,"net_pct":gross-2*cost,"reason":reason})
        i=xi+1
    return rows

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def portfolio(t):
    if t.empty:return {"return":0.0,"max_dd":0.0,"end":START_CAP,"accepted":0,"rejected":0}
    t=t.sort_values(["entry_time"],ascending=True)
    eq=START_CAP;heap=[];active=set();curve=[eq];uid=0;acc=0;rej=0
    def settle(until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;active.discard(sym);curve.append(eq)
    for r in t.itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:
            rej+=1;continue
        notional=eq*SLOT;pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));active.add(r.symbol);uid+=1;acc+=1
    settle(10**30)
    a=np.asarray(curve);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {"return":float(eq/START_CAP-1),"max_dd":float(-dd.min()),"end":float(eq),"accepted":acc,"rejected":rej}

def block_boot_week(t,n=1500):
    if t.empty:return None
    x=t.copy()
    dt=pd.to_datetime(x.entry_time,unit="ms",utc=True)
    x["week"]=(dt-dt.dt.weekday.astype("timedelta64[D]")).dt.floor("D")
    weekly=x.groupby("week").net_pct.sum().to_numpy(float)
    if len(weekly)<12:return None
    rng=np.random.default_rng(SEED)
    vals=np.empty(n)
    for i in range(n):vals[i]=rng.choice(weekly,size=len(weekly),replace=True).mean()
    return float((vals>0).mean())

rows=[];folds=[];years=[];dirs=[]
for don in DONS:
  for adx in ADXS:
    for mode in MODES:
      key=f"D{don}_A{adx}_{mode}"
      print(key,flush=True)
      base=[];stress=[]
      for sym in SYMBOLS:
        base.extend(simulate(sym,don,adx,mode,BASE_COST))
        stress.extend(simulate(sym,don,adx,mode,STRESS_COST))
      b=pd.DataFrame(base);s=pd.DataFrame(stress)
      if b.empty:continue
      dt=pd.to_datetime(b.entry_time,unit="ms",utc=True)
      b["quarter"]=dt.dt.to_period("Q").astype(str);b["year"]=dt.dt.year
      dts=pd.to_datetime(s.entry_time,unit="ms",utc=True)
      s["quarter"]=dts.dt.to_period("Q").astype(str);s["year"]=dts.dt.year

      r=b.net_pct.to_numpy();rs=s.net_pct.to_numpy();rg=b.gross_pct.to_numpy()
      qavg=b.groupby("quarter").net_pct.mean()
      yavg=b.groupby("year").net_pct.mean()
      for q,g in b.groupby("quarter"):
          folds.append({"variant":key,"quarter":q,"trades":len(g),"avg":float(g.net_pct.mean()),"pf":pf(g.net_pct)})
      for y,g in b.groupby("year"):
          years.append({"variant":key,"year":int(y),"trades":len(g),"avg":float(g.net_pct.mean()),"pf":pf(g.net_pct)})
      for d,g in b.groupby("direction"):
          dirs.append({"variant":key,"direction":int(d),"trades":len(g),"avg":float(g.net_pct.mean()),"pf":pf(g.net_pct)})
      pm=portfolio(b)
      wp=block_boot_week(b)

      # concentration of positive sum by symbol
      sy=b.groupby("symbol").net_pct.sum()
      sypos=sy.clip(lower=0)
      conc=float(sypos.max()/sypos.sum()) if sypos.sum()>0 else 1.0
      all_year_positive=bool((yavg>0).all()) if len(yavg)>=3 else False
      pass_gate=bool(
        len(b)>=300 and r.mean()>0 and (pf(r) or 0)>1.05 and
        rs.mean()>0 and (pf(rs) or 0)>1.02 and
        (qavg>0).mean()>=.70 and (wp or 0)>=.95 and
        all_year_positive and pm["return"]>0 and pm["max_dd"]<=.25 and conc<=.30
      )
      rows.append({
        "variant":key,"don":don,"adx":adx,"mode":mode,"trades":len(b),
        "gross_avg":float(rg.mean()),"base_avg":float(r.mean()),"base_pf":pf(r),
        "stress_avg":float(rs.mean()),"stress_pf":pf(rs),
        "positive_quarter_rate":float((qavg>0).mean()),"median_quarter_avg":float(qavg.median()),
        "all_years_positive":all_year_positive,"weekly_block_prob_positive":wp,
        "portfolio_return":pm["return"],"portfolio_max_dd":pm["max_dd"],
        "portfolio_end":pm["end"],"portfolio_accepted":pm["accepted"],
        "max_positive_symbol_share":conc,"passes_gate":pass_gate
      })

R=pd.DataFrame(rows).sort_values(["passes_gate","base_avg"],ascending=[False,False])
R.to_csv(OUT/"variants.csv",index=False)
pd.DataFrame(folds).to_csv(OUT/"quarters.csv",index=False)
pd.DataFrame(years).to_csv(OUT/"years.csv",index=False)
pd.DataFrame(dirs).to_csv(OUT/"directions.csv",index=False)

# Plateau diagnostics: how many parameter neighbors in each mode are positive under stress?
plateau=[]
for mode,g in R.groupby("mode"):
    plateau.append({
      "mode":mode,"variants":len(g),
      "stress_positive_fraction":float((g.stress_avg>0).mean()),
      "base_pf_gt_1_fraction":float((g.base_pf>1).mean()),
      "median_base_avg":float(g.base_avg.median()),
      "median_stress_avg":float(g.stress_avg.median()),
      "median_positive_quarter_rate":float(g.positive_quarter_rate.median()),
      "gate_pass_count":int(g.passes_gate.sum())
    })
P=pd.DataFrame(plateau).sort_values("median_base_avg",ascending=False)
P.to_csv(OUT/"plateau_by_mode.csv",index=False)

summary={
  "version":"R16.1",
  "purpose":"test robustness of 4h trend-breakout edge without ML",
  "variants":len(R),
  "parameter_neighborhood":{"donchian":DONS,"adx":ADXS,"stop_atr":2.5,"target_atr":5.0,"hold_bars":30},
  "modes":MODES,
  "costs":{"base_one_way":BASE_COST,"stress_one_way":STRESS_COST},
  "strict_passed":R[R.passes_gate].variant.tolist(),
  "top10":R.head(10).to_dict("records"),
  "plateau":P.to_dict("records"),
  "outer_holdout_opened":False,
  "notes":[
    "Weekly block bootstrap is used to reduce false independence across correlated altcoin trades.",
    "2024-2026H1 is development data; no data >= 2026-07-01 is used.",
    "This stage tests a plateau and simple regime gating, not a single optimized point.",
    "No ML is used."
  ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
