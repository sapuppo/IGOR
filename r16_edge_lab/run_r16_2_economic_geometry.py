#!/usr/bin/env python3
"""R16.2 - Economic Geometry

Freezes the proven R16.1 signal:
LONG + Donchian55 breakout + EMA50>EMA200 + ADX>=30 + BTC trend + breadth>=55%.

Only the economic layer is varied:
- stop ATR: 2.0 / 2.5 / 3.0
- target ATR: 4.0 / 5.0 / 6.0
- max hold: 20 / 30 / 40 x 4h bars

Then portfolio sizing is tested only on geometry variants that pass robustness gates:
- risk per trade: 0.25% / 0.50% / 0.75% equity
- max simultaneous positions: 5 / 8 / 10
- notional cap per position: 25% equity

No ML. No data >= 2026-07-01. Outer holdout remains sealed.
"""
from __future__ import annotations
import json, heapq
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_2_economic_geometry")
OUT.mkdir(parents=True,exist_ok=True)

BASE_COST=.0016
STRESS_COST=.0021
END_MS=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
SEED=1620
START_CAP=10_000.0

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

STOPS=[2.0,2.5,3.0]
TARGETS=[4.0,5.0,6.0]
HOLDS=[20,30,40]
RISKS=[.0025,.005,.0075]
MAXPOS=[5,8,10]
NOTIONAL_CAP=.25

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
    x["hi55"]=h.shift(1).rolling(55,min_periods=55).max()
    return x

print("Loading frames...",flush=True)
F={s:load(s) for s in SYMBOLS}

# Breadth / BTC context, same R16.1 definition.
cols=[]
for sym,z in F.items():
    q=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),
                index=z.open_time.astype("int64"),name=sym)
    cols.append(q[~q.index.duplicated()])
breadth=pd.concat(cols,axis=1).mean(axis=1,skipna=True)
btc=F["BTCUSDT"].set_index("open_time")
btc_up=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0))
CTX=pd.DataFrame({"breadth":breadth})
CTX["btc_up"]=btc_up.reindex(CTX.index).fillna(False)

# Freeze signal set once.
SIGNALS={}
for sym,z in F.items():
    c=z.close; prev=c.shift(1)
    m=(c>z.hi55)&(prev<=z.hi55.shift())&(z.ema50>z.ema200)&(z.adx>=30)
    idx=[]
    for i in np.flatnonzero(np.asarray(m.fillna(False))):
        ts=int(z.open_time.iloc[i])
        if ts in CTX.index and bool(CTX.loc[ts,"btc_up"]) and float(CTX.loc[ts,"breadth"])>=.55:
            idx.append(i)
    SIGNALS[sym]=idx

def simulate_symbol(sym,stop_atr,target_atr,hold,cost):
    z=F[sym];rows=[];last_exit=-1
    for i in SIGNALS[sym]:
        if i<=last_exit or i>=len(z)-1: continue
        atr=float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr<=0: continue
        ei=i+1; entry=float(z.open.iloc[ei])
        stop=entry-stop_atr*atr
        target=entry+target_atr*atr
        end=min(ei+hold-1,len(z)-1)
        exit_px=float(z.close.iloc[end]);reason="TIME";xi=end
        for j in range(ei,end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
            hs=lo<=stop;ht=hi>=target
            if hs and ht: exit_px=stop;reason="STOP_AMBIGUOUS";xi=j;break
            if hs: exit_px=stop;reason="STOP";xi=j;break
            if ht: exit_px=target;reason="TARGET";xi=j;break
        gross=(exit_px-entry)/entry
        rows.append({
            "symbol":sym,"entry_time":int(z.open_time.iloc[ei]),"exit_time":int(z.open_time.iloc[xi]),
            "entry":entry,"atr":atr,"stop_atr":stop_atr,"target_atr":target_atr,"hold":hold,
            "gross_pct":gross,"net_pct":gross-2*cost,"reason":reason,
            "stop_pct":stop_atr*atr/entry
        })
        last_exit=xi
    return rows

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def weekly_block_prob(d,n=1500):
    if d.empty:return None
    x=d.copy()
    dt=pd.to_datetime(x.entry_time,unit="ms",utc=True)
    x["week"]=(dt-dt.dt.weekday.astype("timedelta64[D]")).dt.floor("D")
    w=x.groupby("week").net_pct.sum().to_numpy(float)
    if len(w)<12:return None
    rng=np.random.default_rng(SEED);vals=np.empty(n)
    for i in range(n): vals[i]=rng.choice(w,size=len(w),replace=True).mean()
    return float((vals>0).mean())

def summarize(d):
    if d.empty:return {}
    r=d.net_pct.to_numpy(float)
    dt=pd.to_datetime(d.entry_time,unit="ms",utc=True)
    q=dt.dt.to_period("Q").astype(str); y=dt.dt.year
    qavg=d.assign(q=q).groupby("q").net_pct.mean()
    yavg=d.assign(y=y).groupby("y").net_pct.mean()
    sy=d.groupby("symbol").net_pct.sum();pos=sy.clip(lower=0)
    conc=float(pos.max()/pos.sum()) if pos.sum()>0 else 1.0
    return {
      "trades":int(len(d)),"avg":float(r.mean()),"median":float(np.median(r)),"pf":pf(r),
      "win_rate":float((r>0).mean()),"positive_quarter_rate":float((qavg>0).mean()),
      "median_quarter_avg":float(qavg.median()),"all_years_positive":bool((yavg>0).all()),
      "weekly_block_prob_positive":weekly_block_prob(d),
      "max_positive_symbol_share":conc,
      "target_rate":float(d.reason.eq("TARGET").mean()),
      "stop_rate":float(d.reason.str.startswith("STOP").mean()),
      "time_rate":float(d.reason.eq("TIME").mean())
    }

BASE_TRADES={}
STRESS_TRADES={}
geom_rows=[]
for st in STOPS:
  for tp in TARGETS:
    for h in HOLDS:
      key=f"S{st}_T{tp}_H{h}"
      print("GEOM",key,flush=True)
      b=[];s=[]
      for sym in SYMBOLS:
        b.extend(simulate_symbol(sym,st,tp,h,BASE_COST))
        s.extend(simulate_symbol(sym,st,tp,h,STRESS_COST))
      B=pd.DataFrame(b);S=pd.DataFrame(s)
      BASE_TRADES[key]=B;STRESS_TRADES[key]=S
      mb=summarize(B);ms=summarize(S)
      passes=bool(
        mb.get("trades",0)>=300 and mb.get("pf",0)>1.15 and mb.get("avg",0)>0 and
        ms.get("pf",0)>1.10 and ms.get("avg",0)>0 and
        mb.get("positive_quarter_rate",0)>=.70 and mb.get("all_years_positive",False) and
        (mb.get("weekly_block_prob_positive") or 0)>=.95 and
        mb.get("max_positive_symbol_share",1)<=.25
      )
      geom_rows.append({"geometry":key,"stop":st,"target":tp,"hold":h,
                        **{f"base_{k}":v for k,v in mb.items()},
                        **{f"stress_{k}":v for k,v in ms.items()},
                        "passes_geometry_gate":passes})

G=pd.DataFrame(geom_rows).sort_values(["passes_geometry_gate","base_avg"],ascending=[False,False])
G.to_csv(OUT/"geometry_grid.csv",index=False)

# Plateau = fraction of the 27 geometries that survive costs and robust evidence.
plateau={
  "variants":int(len(G)),
  "base_positive_fraction":float((G.base_avg>0).mean()),
  "stress_positive_fraction":float((G.stress_avg>0).mean()),
  "base_pf_gt_1_fraction":float((G.base_pf>1).mean()),
  "strict_geometry_pass_count":int(G.passes_geometry_gate.sum()),
  "median_base_avg":float(G.base_avg.median()),
  "median_base_pf":float(G.base_pf.median()),
  "median_stress_avg":float(G.stress_avg.median()),
  "median_weekly_block_prob":float(G.base_weekly_block_prob_positive.median())
}

# Portfolio risk sizing only on passing geometry; if none, top robust candidate only.
eligible=G[G.passes_geometry_gate].copy()
if eligible.empty: eligible=G.head(1).copy()

def portfolio(d,risk,maxpos):
    if d.empty:return {}
    t=d.sort_values("entry_time").reset_index(drop=True)
    eq=START_CAP;heap=[];active=set();curve=[eq];uid=0;accepted=0;rejected=0
    def settle(until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;active.discard(sym);curve.append(eq)
    for r in t.itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=maxpos or r.symbol in active:
            rejected+=1;continue
        stop_pct=max(float(r.stop_pct),1e-6)
        notional=min(eq*NOTIONAL_CAP, eq*risk/stop_pct)
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));active.add(r.symbol);uid+=1;accepted+=1
    settle(10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {"end":float(eq),"return":float(eq/START_CAP-1),"max_dd":float(-dd.min()),
            "accepted":accepted,"rejected":rejected}

port_rows=[]
for gr in eligible.itertuples(index=False):
    key=gr.geometry
    for risk in RISKS:
      for mp in MAXPOS:
        pb=portfolio(BASE_TRADES[key],risk,mp)
        ps=portfolio(STRESS_TRADES[key],risk,mp)
        # Advancement gate emphasizes survival, not max return.
        passp=bool(pb.get("return",0)>0 and ps.get("return",0)>0 and
                   pb.get("max_dd",1)<=.20 and ps.get("max_dd",1)<=.25)
        port_rows.append({"geometry":key,"risk_per_trade":risk,"max_positions":mp,
                          **{f"base_{k}":v for k,v in pb.items()},
                          **{f"stress_{k}":v for k,v in ps.items()},
                          "passes_portfolio_gate":passp})
P=pd.DataFrame(port_rows).sort_values(
    ["passes_portfolio_gate","base_max_dd","base_return"],
    ascending=[False,True,False]
)
P.to_csv(OUT/"portfolio_sizing_grid.csv",index=False)

# Prefer robust geometry by median-like proximity, not raw best PnL:
# among passing geometries choose highest weekly probability then lowest DD will be evaluated in R16.3.
passing=G[G.passes_geometry_gate]
best_geom=(passing.sort_values(["base_weekly_block_prob_positive","stress_pf","base_avg"],ascending=False).iloc[0]
           if len(passing) else G.iloc[0])
best_key=str(best_geom.geometry)
best_ports=P[(P.geometry==best_key)&P.passes_portfolio_gate]
if len(best_ports):
    # conservative selection: smallest DD; then lower risk; then return.
    best_port=best_ports.sort_values(["base_max_dd","risk_per_trade","base_return"],ascending=[True,True,False]).iloc[0].to_dict()
else:
    best_port=P[P.geometry==best_key].sort_values("base_max_dd").iloc[0].to_dict()

summary={
 "version":"R16.2",
 "signal_frozen":"D55_A30_LONG_BREADTH",
 "geometry_neighborhood":{"stop_atr":STOPS,"target_atr":TARGETS,"hold_4h_bars":HOLDS},
 "portfolio_neighborhood":{"risk_per_trade":RISKS,"max_positions":MAXPOS,"notional_cap":NOTIONAL_CAP},
 "geometry_plateau":plateau,
 "geometry_gate_passed":G[G.passes_geometry_gate].geometry.tolist(),
 "top_geometry":G.head(10).to_dict("records"),
 "selected_geometry_for_next_stage":best_key,
 "selected_conservative_portfolio":best_port,
 "outer_holdout_opened":False,
 "notes":[
  "The R16.1 entry signal and regime gate are frozen.",
  "No ML is used.",
  "Selection rewards parameter plateaus and robustness, not the single highest historical return.",
  "No data >= 2026-07-01 is used."
 ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
