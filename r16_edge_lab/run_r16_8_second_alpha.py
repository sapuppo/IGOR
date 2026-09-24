#!/usr/bin/env python3
"""R16.8 - Second Alpha Engine Map

Goal: find an economically independent second engine that can complement the frozen R16 CORE.
The 20%/month portfolio objective is treated as a project target, NOT something forced into model selection.

Development only: data < 2026-07-01.
July/August 2026 are not used.
No ML.

Predeclared independent long-only 1h families:
1) MOM_BREAKOUT: 1h Donchian breakout + EMA trend + ADX.
2) PULLBACK_CONT: trend continuation after controlled pullback.
3) FLUSH_REVERSAL: capitulation/reversal proxy after sharp 6h selloff + volume shock.

Trade geometry is fixed per family and includes base/stress costs.
We rank candidates by robust economics and low weekly PnL correlation with frozen CORE.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT1=Path("r15_regime_lab/history/1h")
ROOT4=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_8_second_alpha")
OUT.mkdir(parents=True,exist_ok=True)

DEV_END=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016
STRESS_COST=.0021
SEED=1680
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def add_indicators(x):
    h,l,c,v=x.high,x.low,x.close,x.volume
    pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x["atr"]=atr;x["adx"]=rma(dx,14)
    x["ema20"]=c.ewm(span=20,adjust=False,min_periods=20).mean()
    x["ema50"]=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x["ema100"]=c.ewm(span=100,adjust=False,min_periods=100).mean()
    x["ema200"]=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x["rsi14"]=100-(100/(1+rma(c.diff().clip(lower=0),14)/rma((-c.diff()).clip(lower=0),14).replace(0,np.nan)))
    x["ret1"]=c.pct_change()
    x["ret3"]=c.pct_change(3)
    x["ret6"]=c.pct_change(6)
    x["ret24"]=c.pct_change(24)
    x["ret72"]=c.pct_change(72)
    x["volz48"]=(v-v.rolling(48,min_periods=36).mean())/v.rolling(48,min_periods=36).std().replace(0,np.nan)
    x["body_pos"]=(c-l)/(h-l).replace(0,np.nan)
    for n in [24,48,72]:
        x[f"hi{n}"]=h.shift(1).rolling(n,min_periods=n).max()
    return x

def load(root,sym):
    x=pd.read_csv(root/f"{sym}.csv.gz")
    for c in ["open_time","open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time")
    x=x[x.open_time<DEV_END].reset_index(drop=True)
    return add_indicators(x)

print("Loading 1h frames...",flush=True)
F1={s:load(ROOT1,s) for s in SYMBOLS}

# Frozen CORE reconstructed on 4h only for weekly PnL correlation benchmark.
print("Loading 4h frames for CORE benchmark...",flush=True)
F4={s:load(ROOT4,s) for s in SYMBOLS}

# 4h breadth / BTC strict context
parts=[]
for sym,z in F4.items():
    ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),index=z.open_time.astype("int64"),name=sym)
    parts.append(ser[~ser.index.duplicated()])
breadth4=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
btc4=F4["BTCUSDT"].set_index("open_time")
ctx4=pd.DataFrame({"breadth":breadth4})
ctx4["btc_strict"]=((btc4.close>btc4.ema200)&(btc4.ema50>btc4.ema200)&(btc4.ret24>0)).reindex(ctx4.index).fillna(False)

def simulate_long(z,signal,stop_atr,target_atr,hold,cost,sym):
    rows=[];last_exit=-1
    idxs=np.flatnonzero(np.asarray(signal.fillna(False)))
    for i in idxs:
        if i<=last_exit or i>=len(z)-1: continue
        atr=float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr<=0: continue
        ei=i+1;entry=float(z.open.iloc[ei]);stop=entry-stop_atr*atr;target=entry+target_atr*atr
        end=min(ei+hold-1,len(z)-1);px=float(z.close.iloc[end]);xi=end;reason="TIME"
        for j in range(ei,end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=lo<=stop;ht=hi>=target
            if hs and ht:px=stop;xi=j;reason="STOP_AMBIGUOUS";break
            if hs:px=stop;xi=j;reason="STOP";break
            if ht:px=target;xi=j;reason="TARGET";break
        gross=(px-entry)/entry
        rows.append({"symbol":sym,"entry_time":int(z.open_time.iloc[ei]),"exit_time":int(z.open_time.iloc[xi]),
                     "net_pct":gross-2*cost,"reason":reason})
        last_exit=xi
    return rows

def core_trades(cost):
    rows=[]
    for sym,z in F4.items():
        c=z.close; prev=c.shift();hi55=z.high.shift(1).rolling(55,min_periods=55).max()
        sig=(c>hi55)&(prev<=hi55.shift())&(z.ema50>z.ema200)&(z.adx>=30)
        mask=[]
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            ts=int(z.open_time.iloc[i])
            ok=ts in ctx4.index and bool(ctx4.loc[ts,"btc_strict"]) and float(ctx4.loc[ts,"breadth"])>=.55
            if ok: mask.append(i)
        sig2=pd.Series(False,index=z.index); sig2.iloc[mask]=True
        rows.extend(simulate_long(z,sig2,2.,6.,30,cost,sym))
    return pd.DataFrame(rows)

CORE=core_trades(BASE_COST)

def family_trades(spec,cost):
    rows=[]
    fam=spec["family"]
    for sym,z in F1.items():
        c=z.close
        if fam=="MOM_BREAKOUT":
            n=spec["don"]; adx=spec["adx"]
            hi=z[f"hi{n}"]
            sig=(c>hi)&(c.shift(1)<=hi.shift())&(z.ema20>z.ema100)&(z.adx>=adx)
        elif fam=="PULLBACK_CONT":
            adx=spec["adx"]
            # strong trend, prior 24h positive, price pulls to EMA20 then reclaims previous high
            sig=(z.ema20>z.ema100)&(z.ret24>=spec["mom24"])&(z.adx>=adx)&
                (z.low<=z.ema20*(1+spec["touch"]))&(c>z.ema20)&(c>z.high.shift(1))
        elif fam=="FLUSH_REVERSAL":
            sig=(z.ret6<=spec["ret6"])&(z.volz48>=spec["volz"])&(z.rsi14<=spec["rsi"])&(z.body_pos>=spec["body"])
        else:
            raise ValueError(fam)
        rows.extend(simulate_long(z,sig,spec["stop"],spec["target"],spec["hold"],cost,sym))
    return pd.DataFrame(rows)

SPECS=[]
for don in [24,48,72]:
  for adx in [20,25]:
    SPECS.append({"family":"MOM_BREAKOUT","name":f"MOM_D{don}_A{adx}","don":don,"adx":adx,"stop":1.5,"target":3.5,"hold":36})
for adx in [18,22,26]:
  for mom in [.015,.025]:
    SPECS.append({"family":"PULLBACK_CONT","name":f"PULL_A{adx}_M{int(mom*1000)}","adx":adx,"mom24":mom,"touch":.003,"stop":1.5,"target":3.0,"hold":30})
for ret6 in [-.05,-.07]:
  for volz in [1.5,2.0]:
    SPECS.append({"family":"FLUSH_REVERSAL","name":f"FLUSH_R{int(abs(ret6)*100)}_V{int(volz*10)}","ret6":ret6,"volz":volz,"rsi":32,"body":.60,"stop":1.25,"target":2.5,"hold":18})

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def weekly_series(d):
    if d.empty:return pd.Series(dtype=float)
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit="ms",utc=True)
    x["week"]=(dt-dt.dt.weekday.astype("timedelta64[D]")).dt.floor("D")
    return x.groupby("week").net_pct.sum()

CORE_W=weekly_series(CORE)

def bootstrap_prob(d,n=1200):
    w=weekly_series(d).to_numpy(float)
    if len(w)<20:return 0.
    rng=np.random.default_rng(SEED)
    vals=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((vals>0).mean())

def stats(d):
    if d.empty:return {"trades":0}
    r=d.net_pct.to_numpy(float);dt=pd.to_datetime(d.entry_time,unit="ms",utc=True)
    q=d.assign(q=dt.dt.to_period("Q").astype(str)).groupby("q").net_pct.mean()
    y=d.assign(y=dt.dt.year).groupby("y").net_pct.mean()
    months=pd.period_range("2024-01","2026-06",freq="M").astype(str)
    actual=dt.dt.to_period("M").astype(str)
    mret=d.assign(m=actual).groupby("m").net_pct.sum()
    sy=d.groupby("symbol").net_pct.sum();pos=sy.clip(lower=0)
    w=weekly_series(d)
    common=CORE_W.index.intersection(w.index)
    corr=float(CORE_W.loc[common].corr(w.loc[common])) if len(common)>=10 else None
    return {
      "trades":int(len(d)),"avg":float(r.mean()),"pf":pf(r),"win_rate":float((r>0).mean()),
      "positive_quarter_rate":float((q>0).mean()),"all_years_positive":bool((y>0).all()),
      "weekly_prob_positive":bootstrap_prob(d),
      "active_month_rate":float(len(set(actual))/len(months)),
      "median_month_trade_sum":float(mret.median()),
      "positive_month_rate":float((mret>0).mean()),
      "max_positive_symbol_share":float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
      "weekly_corr_core":corr
    }

rows=[]
for spec in SPECS:
    print(spec["name"],flush=True)
    b=family_trades(spec,BASE_COST);s=family_trades(spec,STRESS_COST)
    mb=stats(b);ms=stats(s)
    passed=bool(mb.get("trades",0)>=300 and mb.get("avg",0)>0 and ms.get("avg",0)>0 and
                mb.get("pf",0)>=1.10 and ms.get("pf",0)>=1.05 and
                mb.get("weekly_prob_positive",0)>=.90 and mb.get("max_positive_symbol_share",1)<=.30 and
                mb.get("positive_quarter_rate",0)>=.60)
    corr=mb.get("weekly_corr_core")
    complement=bool(passed and (corr is None or abs(corr)<=.40))
    rows.append({"name":spec["name"],"family":spec["family"],"spec":json.dumps(spec),
                 **{f"base_{k}":v for k,v in mb.items()},**{f"stress_{k}":v for k,v in ms.items()},
                 "passes_economic_gate":passed,"passes_complement_gate":complement})

R=pd.DataFrame(rows).sort_values(["passes_complement_gate","passes_economic_gate","base_pf"],ascending=[False,False,False])
R.to_csv(OUT/"second_alpha_map.csv",index=False)

comp=R[R.passes_complement_gate]
selected=comp.iloc[0].to_dict() if len(comp) else None
summary={
 "version":"R16.8",
 "project_target_monthly_return":0.20,
 "target_note":"20% monthly is a project objective, not a backtest acceptance constraint.",
 "candidate_count":len(SPECS),
 "economic_pass_count":int(R.passes_economic_gate.sum()),
 "complement_pass_count":int(R.passes_complement_gate.sum()),
 "selected":selected,
 "top10":R.head(10).to_dict("records"),
 "core_reference":stats(CORE),
 "development_cutoff":"2026-07-01",
 "july_august_used":False,
 "notes":[
  "No leverage.",
  "No ML.",
  "Independent families are evaluated standalone before portfolio combination.",
  "A candidate must be economically positive after stress costs and not be overly correlated with CORE."
 ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
