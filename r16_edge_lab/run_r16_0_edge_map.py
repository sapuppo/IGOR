#!/usr/bin/env python3
"""R16.0 - Simple Edge Map.

Purpose: find out whether any simple, interpretable trading family has a robust
economic edge BEFORE machine learning is allowed to participate.

Data: Binance Spot 1h/4h, 2024-01-01 through 2026-06-30 only.
Execution: next-bar open, causal indicators, no same-symbol overlap.
Costs: 0.16% one-way base, 0.21% one-way stress.

This is discovery/screening, not a final production backtest.
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("r15_regime_lab/history")
OUT=Path("r16_edge_lab/r16_0_edge_map")
OUT.mkdir(parents=True,exist_ok=True)

BASE_COST=.0016
STRESS_COST=.0021
END_MS=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
SEED=1600

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

PRESETS=[
 {"name":"TB4H20","tf":"4h","family":"trend_breakout","don":20,"adx":20,"stop":2.0,"target":4.0,"hold":18},
 {"name":"TB4H55","tf":"4h","family":"trend_breakout","don":55,"adx":25,"stop":2.5,"target":5.0,"hold":30},
 {"name":"PULL1H","tf":"1h","family":"momentum_pullback","adx":18,"stop":1.5,"target":3.0,"hold":24},
 {"name":"PULL4H","tf":"4h","family":"momentum_pullback","adx":20,"stop":2.0,"target":4.0,"hold":18},
 {"name":"SQ1H","tf":"1h","family":"squeeze_breakout","adx":16,"stop":1.5,"target":3.0,"hold":24},
 {"name":"SQ4H","tf":"4h","family":"squeeze_breakout","adx":18,"stop":2.0,"target":4.0,"hold":18},
 {"name":"MR1H","tf":"1h","family":"mean_reversion","adx":18,"z":2.0,"stop":1.5,"target":1.5,"hold":12},
 {"name":"MR1H_STRICT","tf":"1h","family":"mean_reversion","adx":15,"z":2.5,"stop":1.75,"target":1.5,"hold":16},
]

def read(sym,tf):
    p=ROOT/tf/f"{sym}.csv.gz"
    if not p.exists(): return None
    x=pd.read_csv(p)
    for c in ["open_time","open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna(subset=["open_time","open","high","low","close","volume"]).sort_values("open_time").drop_duplicates("open_time")
    x=x[x.open_time<END_MS].reset_index(drop=True)
    return x

def rma(s,n):
    return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def indicators(x):
    z=x.copy()
    o,h,l,c,v=[z[k].astype(float) for k in ["open","high","low","close","volume"]]
    pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff(); dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.0),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.0),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    adx=rma(dx,14)
    ema20=c.ewm(span=20,adjust=False,min_periods=20).mean()
    ema50=c.ewm(span=50,adjust=False,min_periods=50).mean()
    ema200=c.ewm(span=200,adjust=False,min_periods=200).mean()
    d=c.diff(); gain=rma(d.clip(lower=0),14); loss=rma((-d).clip(lower=0),14)
    rsi=100-(100/(1+gain/loss.replace(0,np.nan)))
    mid=c.rolling(20,min_periods=20).mean(); sd=c.rolling(20,min_periods=20).std()
    bbu=mid+2*sd; bbl=mid-2*sd
    bbz=(c-mid)/sd.replace(0,np.nan)
    bbw=(bbu-bbl)/mid.replace(0,np.nan)
    bwq=bbw.shift(1).rolling(120,min_periods=80).quantile(.20)
    volmean=v.rolling(40,min_periods=30).mean()
    volstd=v.rolling(40,min_periods=30).std().replace(0,np.nan)
    volz=(v-volmean)/volstd
    z["atr"]=atr; z["adx"]=adx
    z["ema20"]=ema20; z["ema50"]=ema50; z["ema200"]=ema200
    z["rsi"]=rsi; z["bbz"]=bbz; z["bbw"]=bbw; z["bwq20"]=bwq; z["volz"]=volz
    for n in [20,55]:
        z[f"don_hi_{n}"]=h.shift(1).rolling(n,min_periods=n).max()
        z[f"don_lo_{n}"]=l.shift(1).rolling(n,min_periods=n).min()
    return z

def signals(z,p):
    c=z.close; prev=c.shift(1)
    trend_up=(z.ema50>z.ema200)
    trend_dn=(z.ema50<z.ema200)
    if p["family"]=="trend_breakout":
        n=p["don"]
        long=(c>z[f"don_hi_{n}"])&(prev<=z[f"don_hi_{n}"].shift(1))&trend_up&(z.adx>=p["adx"])
        short=(c<z[f"don_lo_{n}"])&(prev>=z[f"don_lo_{n}"].shift(1))&trend_dn&(z.adx>=p["adx"])
    elif p["family"]=="momentum_pullback":
        long=trend_up&(z.ema20>z.ema50)&(z.adx>=p["adx"])&(prev<=z.ema20.shift(1))&(c>z.ema20)&z.rsi.between(48,68)
        short=trend_dn&(z.ema20<z.ema50)&(z.adx>=p["adx"])&(prev>=z.ema20.shift(1))&(c<z.ema20)&z.rsi.between(32,52)
    elif p["family"]=="squeeze_breakout":
        prev_squeeze=(z.bbw.shift(1)<=z.bwq20.shift(1))
        long=prev_squeeze&(z.bbw>z.bwq20)&(c>z.don_hi_20)&trend_up&(z.adx>=p["adx"])&(z.volz>.5)
        short=prev_squeeze&(z.bbw>z.bwq20)&(c<z.don_lo_20)&trend_dn&(z.adx>=p["adx"])&(z.volz>.5)
    elif p["family"]=="mean_reversion":
        flat=(z.adx<p["adx"])&(((z.ema50-z.ema200).abs()/z.atr.replace(0,np.nan))<2.0)
        long=flat&(z.bbz<=-p["z"])&(z.rsi<35)
        short=flat&(z.bbz>=p["z"])&(z.rsi>65)
    else:
        raise ValueError(p["family"])
    sig=np.zeros(len(z),dtype=np.int8)
    sig[np.asarray(long.fillna(False))]=1
    sig[np.asarray(short.fillna(False))]=-1
    return sig

def simulate_symbol(sym,p,cost):
    x=read(sym,p["tf"])
    if x is None or len(x)<250:return []
    z=indicators(x)
    sig=signals(z,p)
    rows=[]; i=0
    while i<len(z)-1:
        direction=int(sig[i])
        atr=float(z.atr.iloc[i]) if np.isfinite(z.atr.iloc[i]) else np.nan
        if direction==0 or not np.isfinite(atr) or atr<=0:
            i+=1; continue
        entry_i=i+1
        entry=float(z.open.iloc[entry_i])
        stop=entry-direction*p["stop"]*atr
        target=entry+direction*p["target"]*atr
        end=min(entry_i+p["hold"]-1,len(z)-1)
        exit_px=float(z.close.iloc[end]); reason="TIME"; exit_i=end
        for j in range(entry_i,end+1):
            hi=float(z.high.iloc[j]); lo=float(z.low.iloc[j])
            if direction>0:
                hs=lo<=stop; ht=hi>=target
            else:
                hs=hi>=stop; ht=lo<=target
            if hs and ht:
                exit_px=stop;reason="STOP_AMBIGUOUS";exit_i=j;break
            if hs:
                exit_px=stop;reason="STOP";exit_i=j;break
            if ht:
                exit_px=target;reason="TARGET";exit_i=j;break
        gross=direction*(exit_px-entry)/entry
        rows.append({
          "strategy":p["name"],"family":p["family"],"tf":p["tf"],"symbol":sym,
          "direction":direction,"signal_time":int(z.open_time.iloc[i]),
          "entry_time":int(z.open_time.iloc[entry_i]),"exit_time":int(z.open_time.iloc[exit_i]),
          "gross_pct":gross,"net_pct":gross-2*cost,"exit_reason":reason,
          "atr_pct":atr/entry
        })
        # no overlapping position in same symbol/strategy
        i=exit_i+1
    return rows

def pf(r):
    a=np.asarray(r,float); gp=a[a>0].sum(); gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def metrics(d,retcol="net_pct"):
    if d.empty:return {"trades":0}
    r=d[retcol].to_numpy(float)
    return {
      "trades":int(len(d)),"win_rate":float((r>0).mean()),
      "avg":float(r.mean()),"median":float(np.median(r)),
      "pf":pf(r),"sum":float(r.sum())
    }

def quarter(ts):
    d=pd.to_datetime(ts,unit="ms",utc=True)
    return d.dt.to_period("Q").astype(str)

def bootstrap_positive_prob(r,n=1200):
    a=np.asarray(r,float)
    if len(a)<10:return None
    rng=np.random.default_rng(SEED)
    means=[]
    for _ in range(n):
        means.append(rng.choice(a,size=len(a),replace=True).mean())
    return float((np.asarray(means)>0).mean())

all_base=[]; all_stress=[]
for k,p in enumerate(PRESETS,1):
    print(f"[{k}/{len(PRESETS)}] {p['name']}",flush=True)
    for sym in SYMBOLS:
        all_base.extend(simulate_symbol(sym,p,BASE_COST))
        all_stress.extend(simulate_symbol(sym,p,STRESS_COST))

B=pd.DataFrame(all_base); S=pd.DataFrame(all_stress)
B.to_parquet(OUT/"trades_base.parquet",index=False,compression="zstd")
S.to_parquet(OUT/"trades_stress.parquet",index=False,compression="zstd")

summ=[]; folds=[]; symbols=[]; directions=[]
for p in PRESETS:
    name=p["name"]
    b=B[B.strategy==name].copy(); s=S[S.strategy==name].copy()
    if b.empty:
        summ.append({"strategy":name,"family":p["family"],"tf":p["tf"],"trades":0,"passes_screen":False});continue
    b["quarter"]=quarter(b.entry_time); s["quarter"]=quarter(s.entry_time)
    mb=metrics(b); ms=metrics(s); mg=metrics(b,"gross_pct")
    qrows=[]
    for q,g in b.groupby("quarter"):
        m=metrics(g); qrows.append((q,m["trades"],m["avg"],m["pf"],m["sum"]))
        folds.append({"strategy":name,"quarter":q,**m})
    qdf=pd.DataFrame(qrows,columns=["quarter","trades","avg","pf","sum"])
    positive_fold_rate=float((qdf["avg"]>0).mean()) if len(qdf) else 0.0
    median_fold_avg=float(qdf["avg"].median()) if len(qdf) else np.nan

    symstats=[]
    for sym,g in b.groupby("symbol"):
        m=metrics(g); symbols.append({"strategy":name,"symbol":sym,**m})
        symstats.append((sym,m["sum"]))
    pos_by_sym=pd.Series({a:max(v,0) for a,v in symstats},dtype=float)
    max_pos_share=float(pos_by_sym.max()/pos_by_sym.sum()) if pos_by_sym.sum()>0 else 1.0

    for direc,g in b.groupby("direction"):
        directions.append({"strategy":name,"direction":int(direc),**metrics(g)})

    boot=bootstrap_positive_prob(b.net_pct)
    pass_screen=bool(
      mb["trades"]>=100 and mb["avg"]>0 and (mb["pf"] or 0)>1.05 and
      ms["avg"]>=0 and positive_fold_rate>=.60 and (boot or 0)>=.95 and max_pos_share<=.35
    )
    summ.append({
      "strategy":name,"family":p["family"],"tf":p["tf"],
      "trades":mb["trades"],
      "gross_avg_pct":mg["avg"],"gross_pf":mg["pf"],
      "base_avg_net_pct":mb["avg"],"base_pf":mb["pf"],"base_win_rate":mb["win_rate"],
      "stress_avg_net_pct":ms["avg"],"stress_pf":ms["pf"],
      "roundtrip_base_cost":2*BASE_COST,"roundtrip_stress_cost":2*STRESS_COST,
      "break_even_one_way_cost":max(0.0,mg["avg"]/2),
      "positive_quarter_rate":positive_fold_rate,"median_quarter_avg":median_fold_avg,
      "bootstrap_prob_mean_positive":boot,"max_positive_pnl_symbol_share":max_pos_share,
      "passes_screen":pass_screen
    })

SUM=pd.DataFrame(summ).sort_values(["passes_screen","base_avg_net_pct"],ascending=[False,False])
SUM.to_csv(OUT/"strategy_summary.csv",index=False)
pd.DataFrame(folds).to_csv(OUT/"quarter_folds.csv",index=False)
pd.DataFrame(symbols).to_csv(OUT/"per_symbol.csv",index=False)
pd.DataFrame(directions).to_csv(OUT/"long_short.csv",index=False)

passed=SUM[SUM.passes_screen].strategy.tolist()
summary={
  "version":"R16.0",
  "philosophy":"edge first; ML prohibited as primary signal",
  "period_end_exclusive":"2026-07-01T00:00:00Z",
  "timeframes":["1h","4h"],
  "symbols":len(SYMBOLS),
  "strategies_tested":len(PRESETS),
  "costs":{"base_one_way":BASE_COST,"stress_one_way":STRESS_COST},
  "screening_gate":{
    "min_trades":100,"base_avg_net_gt":0,"base_pf_gt":1.05,
    "stress_avg_net_ge":0,"positive_quarter_rate_ge":.60,
    "bootstrap_prob_mean_positive_ge":.95,"max_positive_pnl_symbol_share_le":.35
  },
  "passed":passed,
  "ranked":SUM.to_dict("records"),
  "outer_holdout_opened":False,
  "notes":[
    "Presets are predeclared simple hypotheses, not ML-generated signals.",
    "Q2 2026 is development data because R15 already inspected it.",
    "No data on or after 2026-07-01 is used.",
    "Shorts are research-only on Spot candles; production shorting would require a short-capable venue and its actual costs.",
    "A positive discovery result would still require a separate robustness stage before outer holdout."
  ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
