#!/usr/bin/env python3
"""R16.5 Opportunity Recovery.

Freeze D55 breakout + trend + S2/T6/H30 geometry.
Only recover opportunity by relaxing regime gates:
- ADX: 20 / 25 / 30
- breadth: 45% / 50% / 55%
- BTC mode:
  STRICT = close>EMA200, EMA50>EMA200, 7d ret>0
  SOFT   = close>EMA200 and 7d ret>0
  NONE   = no BTC hard veto

Selection is based ONLY on development data < 2026-07-01.
July/August are diagnostics and already consumed; they do not select the variant.
No ML.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_5_opportunity_recovery")
OUT.mkdir(parents=True,exist_ok=True)
DEV_END=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
JUL_END=int(pd.Timestamp("2026-08-01T00:00:00Z").timestamp()*1000)
AUG_END=int(pd.Timestamp("2026-09-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016; STRESS_COST=.0021
STOP_ATR=2.; TARGET_ATR=6.; HOLD=30
ADXES=[20,25,30]; BREADTHS=[.45,.50,.55]; MODES=["STRICT","SOFT","NONE"]
SEED=1650
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def load(sym):
    x=pd.read_csv(ROOT/f"{sym}.csv.gz")
    for c in ["open_time","open","high","low","close","volume"]: x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    h,l,c=x.high,x.low,x.close; pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14); up=h.diff(); dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x["atr"]=atr; x["adx"]=rma(dx,14)
    x["ema50"]=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x["ema200"]=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x["ret42"]=c/c.shift(42)-1
    x["hi55"]=h.shift(1).rolling(55,min_periods=55).max()
    return x

F={s:load(s) for s in SYMBOLS}
parts=[]
for s,z in F.items():
    ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),index=z.open_time.astype("int64"),name=s)
    parts.append(ser[~ser.index.duplicated()])
breadth=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
btc=F["BTCUSDT"].set_index("open_time")
CTX=pd.DataFrame(index=breadth.index)
CTX["breadth"]=breadth
CTX["btc_strict"]=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0)).reindex(CTX.index).fillna(False)
CTX["btc_soft"]=((btc.close>btc.ema200)&(btc.ret42>0)).reindex(CTX.index).fillna(False)

# Precompute D55+trend candidates and their full trade outcome once per symbol/cost.
def raw_candidates(sym,cost):
    z=F[sym]; c=z.close; prev=c.shift()
    sig=(c>z.hi55)&(prev<=z.hi55.shift())&(z.ema50>z.ema200)
    rows=[]; last_exit=-1
    for i in np.flatnonzero(np.asarray(sig.fillna(False))):
        if i<=last_exit or i>=len(z)-1: continue
        ts=int(z.open_time.iloc[i])
        if ts not in CTX.index: continue
        atr=float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr<=0: continue
        ei=i+1; entry=float(z.open.iloc[ei]); stop=entry-STOP_ATR*atr; target=entry+TARGET_ATR*atr
        end=min(ei+HOLD-1,len(z)-1); exit_px=float(z.close.iloc[end]); xi=end; reason="TIME"
        for j in range(ei,end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=lo<=stop;ht=hi>=target
            if hs and ht: exit_px=stop;xi=j;reason="STOP_AMBIGUOUS";break
            if hs: exit_px=stop;xi=j;reason="STOP";break
            if ht: exit_px=target;xi=j;reason="TARGET";break
        gross=(exit_px-entry)/entry
        rows.append({"symbol":sym,"signal_time":ts,"entry_time":int(z.open_time.iloc[ei]),"exit_time":int(z.open_time.iloc[xi]),
                     "adx":float(z.adx.iloc[i]),"breadth":float(CTX.loc[ts,"breadth"]),
                     "btc_strict":bool(CTX.loc[ts,"btc_strict"]),"btc_soft":bool(CTX.loc[ts,"btc_soft"]),
                     "net_pct":gross-2*cost,"reason":reason})
        last_exit=xi
    return rows

BASE=pd.DataFrame(sum((raw_candidates(s,BASE_COST) for s in SYMBOLS),[]))
STRESS=pd.DataFrame(sum((raw_candidates(s,STRESS_COST) for s in SYMBOLS),[]))

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def boot_week(d,n=1200):
    if len(d)<30:return 0.
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit="ms",utc=True)
    x["week"]=(dt-dt.dt.weekday.astype("timedelta64[D]")).dt.floor("D")
    w=x.groupby("week").net_pct.sum().to_numpy(float)
    rng=np.random.default_rng(SEED); vals=[rng.choice(w,len(w),replace=True).mean() for _ in range(n)]
    return float((np.asarray(vals)>0).mean())

def stats(d,period_end=DEV_END):
    d=d[d.entry_time<period_end].copy()
    if d.empty:return {"trades":0}
    r=d.net_pct.to_numpy(float);dt=pd.to_datetime(d.entry_time,unit="ms",utc=True)
    qavg=d.assign(q=dt.dt.to_period("Q").astype(str)).groupby("q").net_pct.mean()
    yavg=d.assign(y=dt.dt.year).groupby("y").net_pct.mean()
    months=dt.dt.to_period("M").astype(str)
    all_months=pd.period_range("2024-01","2026-06",freq="M").astype(str)
    active=set(months)
    sy=d.groupby("symbol").net_pct.sum();pos=sy.clip(lower=0)
    return {"trades":int(len(d)),"avg":float(r.mean()),"pf":pf(r),"win_rate":float((r>0).mean()),
            "positive_quarter_rate":float((qavg>0).mean()),"all_years_positive":bool((yavg>0).all()),
            "weekly_prob_positive":boot_week(d),
            "active_month_rate":float(sum(m in active for m in all_months)/len(all_months)),
            "median_trades_active_month":float(pd.Series(months).value_counts().median()),
            "max_positive_symbol_share":float(pos.max()/pos.sum()) if pos.sum()>0 else 1.}

def gate(df,adx,br,mode):
    m=(df.adx>=adx)&(df.breadth>=br)
    if mode=="STRICT":m&=df.btc_strict
    elif mode=="SOFT":m&=df.btc_soft
    return df[m].copy()

rows=[]
for adx in ADXES:
  for br in BREADTHS:
    for mode in MODES:
      b=gate(BASE,adx,br,mode); s=gate(STRESS,adx,br,mode)
      mb=stats(b);ms=stats(s)
      passed=bool(mb.get("trades",0)>=400 and mb.get("pf",0)>=1.15 and ms.get("pf",0)>=1.10 and
                  mb.get("avg",0)>0 and ms.get("avg",0)>0 and mb.get("positive_quarter_rate",0)>=.65 and
                  mb.get("all_years_positive",False) and mb.get("weekly_prob_positive",0)>=.95 and
                  mb.get("max_positive_symbol_share",1)<=.25)
      # diagnostics after dev period, not selection inputs
      july=gate(BASE[(BASE.entry_time>=DEV_END)&(BASE.entry_time<JUL_END)],adx,br,mode)
      aug=gate(BASE[(BASE.entry_time>=JUL_END)&(BASE.entry_time<AUG_END)],adx,br,mode)
      rows.append({"variant":f"A{adx}_B{int(br*100)}_{mode}","adx":adx,"breadth":br,"btc_mode":mode,
                   **{f"base_{k}":v for k,v in mb.items()},**{f"stress_{k}":v for k,v in ms.items()},
                   "passes_gate":passed,"july_signals":int(len(july)),"august_signals":int(len(aug))})
R=pd.DataFrame(rows)
# select highest activity among robust passers, then stress PF / base PF
passed=R[R.passes_gate].sort_values(["base_active_month_rate","stress_pf","base_pf","base_trades"],ascending=False)
if len(passed): selected=passed.iloc[0]
else: selected=R.sort_values(["base_active_month_rate","stress_pf"],ascending=False).iloc[0]
R.sort_values(["passes_gate","base_active_month_rate","stress_pf"],ascending=[False,False,False]).to_csv(OUT/"gate_grid.csv",index=False)
summary={
 "version":"R16.5",
 "purpose":"recover trading opportunity without changing D55 or S2/T6/H30",
 "variants":int(len(R)),
 "strict_pass_count":int(R.passes_gate.sum()),
 "selected":selected.to_dict(),
 "top10":R.sort_values(["passes_gate","base_active_month_rate","stress_pf"],ascending=[False,False,False]).head(10).to_dict("records"),
 "selection_uses_data_before":"2026-07-01",
 "july_august_used_for_selection":False,
 "validation_note":"July and August are already consumed diagnostics. A changed rule requires a new untouched validation period before deployment.",
 "no_ml":True
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
