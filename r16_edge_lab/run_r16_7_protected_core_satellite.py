#!/usr/bin/env python3
"""R16.7 Protected Core + Satellite

CORE stays untouched and owns its own 5-position sleeve.
Satellite may trade only non-CORE STANDARD/EXPANSION opportunities in a separate sleeve.

Frozen market logic:
CORE      ADX>=30, breadth>=55%, BTC STRICT, risk 0.25%
STANDARD  ADX>=25, breadth>=45%, BTC STRICT
EXPANSION ADX>=20, breadth>=45%, BTC SOFT
Donchian55 + EMA trend + S2/T6/H30.

Satellite grid (development only < 2026-07-01):
- risk: 0.05%, 0.075%, 0.10%
- max positions: 1 or 2
CORE always: 0.25%, max 5
Total equity is shared, but satellite cannot consume CORE slots.
July/Aug are diagnostics only and already consumed.
"""
from __future__ import annotations
import json, heapq
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_7_protected_core_satellite")
OUT.mkdir(parents=True,exist_ok=True)

DEV_END=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
JUL_END=int(pd.Timestamp("2026-08-01T00:00:00Z").timestamp()*1000)
AUG_END=int(pd.Timestamp("2026-09-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016;STRESS_COST=.0021
STOP_ATR=2.;TARGET_ATR=6.;HOLD=30
START_CAP=10000.
CORE_RISK=.0025;CORE_MAX=5
SAT_RISKS=[.0005,.00075,.001]
SAT_MAXS=[1,2]
NOTIONAL_CAP=.25
SEED=1670
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def load(sym):
    x=pd.read_csv(ROOT/f"{sym}.csv.gz")
    for c in ["open_time","open","high","low","close","volume"]:x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    h,l,c=x.high,x.low,x.close;pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1);atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x["atr"]=atr;x["adx"]=rma(dx,14)
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
CTX["strict"]=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0)).reindex(CTX.index).fillna(False)
CTX["soft"]=((btc.close>btc.ema200)&(btc.ret42>0)).reindex(CTX.index).fillna(False)

def classify(adx,br,strict,soft):
    if adx>=30 and br>=.55 and strict:return "CORE"
    if adx>=25 and br>=.45 and strict:return "STANDARD"
    if adx>=20 and br>=.45 and soft:return "EXPANSION"
    return None

def trades_for(sym,cost):
    z=F[sym];c=z.close;prev=c.shift()
    sig=(c>z.hi55)&(prev<=z.hi55.shift())&(z.ema50>z.ema200)
    rows=[];last_exit=-1
    for i in np.flatnonzero(np.asarray(sig.fillna(False))):
        if i<=last_exit or i>=len(z)-1:continue
        ts=int(z.open_time.iloc[i])
        if ts not in CTX.index:continue
        tier=classify(float(z.adx.iloc[i]),float(CTX.loc[ts,"breadth"]),bool(CTX.loc[ts,"strict"]),bool(CTX.loc[ts,"soft"]))
        if tier is None:continue
        atr=float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr<=0:continue
        ei=i+1;entry=float(z.open.iloc[ei]);stop=entry-STOP_ATR*atr;target=entry+TARGET_ATR*atr
        end=min(ei+HOLD-1,len(z)-1);px=float(z.close.iloc[end]);xi=end;reason="TIME"
        for j in range(ei,end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=lo<=stop;ht=hi>=target
            if hs and ht:px=stop;xi=j;reason="STOP_AMBIGUOUS";break
            if hs:px=stop;xi=j;reason="STOP";break
            if ht:px=target;xi=j;reason="TARGET";break
        gross=(px-entry)/entry
        rows.append({"symbol":sym,"tier":tier,"entry_time":int(z.open_time.iloc[ei]),"exit_time":int(z.open_time.iloc[xi])+4*3600_000,
                     "stop_pct":STOP_ATR*atr/entry,"net_pct":gross-2*cost})
        last_exit=xi
    return rows

def build(cost):
    return pd.DataFrame(sum((trades_for(s,cost) for s in SYMBOLS),[]))

BASE=build(BASE_COST);STRESS=build(STRESS_COST)

def sleeve_portfolio(d,sat_risk,sat_max,start=None,end=DEV_END):
    x=d.copy()
    if start is not None:x=x[x.entry_time>=start]
    if end is not None:x=x[x.entry_time<end]
    if x.empty:return {"end":START_CAP,"return":0.,"max_dd":0.,"core_acc":0,"sat_acc":0,"rejected":0}
    x["tier_priority"]=x.tier.map({"CORE":0,"STANDARD":1,"EXPANSION":2}).fillna(9)
    x=x.sort_values(["entry_time","tier_priority","symbol"]).reset_index(drop=True)
    eq=START_CAP;curve=[eq];uid=0
    core_heap=[];sat_heap=[];core_syms=set();sat_syms=set();core_acc=sat_acc=rej=0
    def settle(heap,syms,until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;syms.discard(sym);curve.append(eq)
    for r in x.itertuples(index=False):
        t=int(r.entry_time);settle(core_heap,core_syms,t);settle(sat_heap,sat_syms,t)
        stop=max(float(r.stop_pct),1e-6)
        if r.tier=="CORE":
            if len(core_heap)>=CORE_MAX or r.symbol in core_syms or r.symbol in sat_syms:rej+=1;continue
            risk=CORE_RISK;notional=min(eq*NOTIONAL_CAP,eq*risk/stop);pnl=notional*float(r.net_pct)
            heapq.heappush(core_heap,(int(r.exit_time),uid,pnl,r.symbol));core_syms.add(r.symbol);core_acc+=1;uid+=1
        else:
            if len(sat_heap)>=sat_max or r.symbol in core_syms or r.symbol in sat_syms:rej+=1;continue
            risk=sat_risk;notional=min(eq*NOTIONAL_CAP,eq*risk/stop);pnl=notional*float(r.net_pct)
            heapq.heappush(sat_heap,(int(r.exit_time),uid,pnl,r.symbol));sat_syms.add(r.symbol);sat_acc+=1;uid+=1
    settle(core_heap,core_syms,10**30);settle(sat_heap,sat_syms,10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {"end":float(eq),"return":float(eq/START_CAP-1),"max_dd":float(-dd.min()),"core_acc":core_acc,"sat_acc":sat_acc,"rejected":rej}

# Core-only fair baseline from same candidate generation.
def core_only(d,start=None,end=DEV_END):
    x=d[d.tier.eq("CORE")].copy()
    if start is not None:x=x[x.entry_time>=start]
    if end is not None:x=x[x.entry_time<end]
    if x.empty:return {"end":START_CAP,"return":0.,"max_dd":0.,"core_acc":0,"sat_acc":0,"rejected":0}
    eq=START_CAP;curve=[eq];heap=[];syms=set();uid=acc=rej=0
    def settle(until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;syms.discard(sym);curve.append(eq)
    for r in x.sort_values(["entry_time","symbol"]).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=CORE_MAX or r.symbol in syms:rej+=1;continue
        notional=min(eq*NOTIONAL_CAP,eq*CORE_RISK/max(float(r.stop_pct),1e-6))
        pnl=notional*float(r.net_pct);heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));syms.add(r.symbol);uid+=1;acc+=1
    settle(10**30);a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {"end":float(eq),"return":float(eq/START_CAP-1),"max_dd":float(-dd.min()),"core_acc":acc,"sat_acc":0,"rejected":rej}

core_b=core_only(BASE);core_s=core_only(STRESS)
rows=[]
for sr in SAT_RISKS:
    for sm in SAT_MAXS:
        pb=sleeve_portfolio(BASE,sr,sm);ps=sleeve_portfolio(STRESS,sr,sm)
        # robust improvement rule: must add return over CORE in base and stress, DD cannot rise >2.5pp
        passed=bool(pb["return"]>core_b["return"] and ps["return"]>core_s["return"] and
                    pb["max_dd"]<=core_b["max_dd"]+.025 and ps["max_dd"]<=core_s["max_dd"]+.025)
        rows.append({"sat_risk":sr,"sat_max":sm,"base":pb,"stress":ps,"passes":passed})
R=pd.DataFrame([{"sat_risk":r["sat_risk"],"sat_max":r["sat_max"],"base_return":r["base"]["return"],"base_dd":r["base"]["max_dd"],
                 "stress_return":r["stress"]["return"],"stress_dd":r["stress"]["max_dd"],"base_core_acc":r["base"]["core_acc"],
                 "base_sat_acc":r["base"]["sat_acc"],"passes":r["passes"]} for r in rows])
R.to_csv(OUT/"satellite_grid.csv",index=False)
ok=R[R.passes]
selected=(ok.sort_values(["base_dd","stress_return"],ascending=[True,False]).iloc[0] if len(ok) else R.sort_values("stress_return",ascending=False).iloc[0])

sr=float(selected.sat_risk);sm=int(selected.sat_max)
diag={
 "july_base":sleeve_portfolio(BASE,sr,sm,DEV_END,JUL_END),
 "august_base":sleeve_portfolio(BASE,sr,sm,JUL_END,AUG_END)
}
summary={"version":"R16.7","core_baseline":{"base":core_b,"stress":core_s},"grid":rows,
         "selected":{"sat_risk":sr,"sat_max":sm,"passes":bool(selected.passes)},
         "selected_dev":{"base":sleeve_portfolio(BASE,sr,sm),"stress":sleeve_portfolio(STRESS,sr,sm)},
         "consumed_diagnostics":diag,
         "selection_cutoff":"2026-07-01","july_august_used_for_selection":False,
         "notes":["CORE sleeve is protected from satellite capacity.","Satellite trades only non-CORE STANDARD/EXPANSION signals.","July/August are diagnostics only."]}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
