#!/usr/bin/env python3
"""R16.9B - Flush Shock Cluster Control

Fixed candidate discovered in R16.9:
- 1h ret6 <= -9%
- vol z48 >= 2
- RSI14 <= 32
- candle body position >= .60
- long next open
- stop 1.25 ATR / target 2.5 ATR / hold 18h
- no BTC/breadth/trend veto

Problem to solve: correlated clusters of simultaneous altcoin flushes.

Predeclared cluster controls:
- event bucket: 1h / 3h / 6h
- max entries per bucket: 1 / 2 / 3
- ranking: severity / recovery / composite
No ML, no leverage, no July/August.
"""
from __future__ import annotations
import json, heapq
from pathlib import Path
import numpy as np
import pandas as pd

ROOT1=Path("r15_regime_lab/history/1h")
ROOT4=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_9b_flush_cluster_control")
OUT.mkdir(parents=True,exist_ok=True)

DEV_END=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016
STRESS_COST=.0021
SEED=1691
START_CAP=10_000.
CORE_RISK=.0025
CORE_MAX=5
NOTIONAL_CAP=.25

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def load(root,sym):
    x=pd.read_csv(root/f"{sym}.csv.gz")
    for c in ["open_time","open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time")
    x=x[x.open_time<DEV_END].reset_index(drop=True)
    h,l,c,v=x.high,x.low,x.close,x.volume
    pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x["atr"]=atr;x["adx"]=rma(dx,14)
    x["ema50"]=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x["ema200"]=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x["ret6"]=c.pct_change(6);x["ret42"]=c.pct_change(42)
    x["rsi14"]=100-(100/(1+rma(c.diff().clip(lower=0),14)/rma((-c.diff()).clip(lower=0),14).replace(0,np.nan)))
    x["volz48"]=(v-v.rolling(48,min_periods=36).mean())/v.rolling(48,min_periods=36).std().replace(0,np.nan)
    x["body_pos"]=(c-l)/(h-l).replace(0,np.nan)
    return x

F1={s:load(ROOT1,s) for s in SYMBOLS}
F4={s:load(ROOT4,s) for s in SYMBOLS}

# CORE exact context
parts=[]
for s,z in F4.items():
    ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),index=z.open_time.astype("int64"),name=s)
    parts.append(ser[~ser.index.duplicated()])
breadth=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
btc=F4["BTCUSDT"].set_index("open_time")
ctx=pd.DataFrame(index=breadth.index)
ctx["breadth"]=breadth
ctx["strict"]=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0)).reindex(ctx.index).fillna(False)

def exit_trade(z,i,stop_atr,target_atr,hold,cost,sym,extra=None):
    atr=float(z.atr.iloc[i])
    if not np.isfinite(atr) or atr<=0 or i>=len(z)-1:return None
    ei=i+1;entry=float(z.open.iloc[ei]);stop=entry-stop_atr*atr;target=entry+target_atr*atr
    end=min(ei+hold-1,len(z)-1);px=float(z.close.iloc[end]);xi=end;reason="TIME"
    for j in range(ei,end+1):
        hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=lo<=stop;ht=hi>=target
        if hs and ht:px=stop;xi=j;reason="STOP_AMBIGUOUS";break
        if hs:px=stop;xi=j;reason="STOP";break
        if ht:px=target;xi=j;reason="TARGET";break
    row={"symbol":sym,"signal_time":int(z.open_time.iloc[i]),"entry_time":int(z.open_time.iloc[ei]),
         "exit_time":int(z.open_time.iloc[xi])+int(3600_000 if z is F1.get(sym) else 4*3600_000),
         "stop_pct":stop_atr*atr/entry,"net_pct":(px-entry)/entry-2*cost,"reason":reason}
    if extra:row.update(extra)
    return row

def core_trades(cost):
    rows=[]
    for sym,z in F4.items():
        hi55=z.high.shift(1).rolling(55,min_periods=55).max()
        sig=(z.close>hi55)&(z.close.shift(1)<=hi55.shift())&(z.ema50>z.ema200)&(z.adx>=30)
        last=-1
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            if i<=last:continue
            ts=int(z.open_time.iloc[i])
            if ts not in ctx.index or not bool(ctx.loc[ts,"strict"]) or float(ctx.loc[ts,"breadth"])<.55:continue
            r=exit_trade(z,i,2.,6.,30,cost,sym)
            if r:
                rows.append(r)
                # convert 4h exit time back to last occupied candle index
                last=np.searchsorted(z.open_time.to_numpy(),r["exit_time"]-4*3600_000)
    return pd.DataFrame(rows)

def raw_flush(cost):
    rows=[]
    for sym,z in F1.items():
        sig=(z.ret6<=-.09)&(z.volz48>=2.)&(z.rsi14<=32)&(z.body_pos>=.60)
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            r=exit_trade(z,i,1.25,2.5,18,cost,sym,{
                "ret6":float(z.ret6.iloc[i]),"volz48":float(z.volz48.iloc[i]),
                "body_pos":float(z.body_pos.iloc[i]),"rsi14":float(z.rsi14.iloc[i])
            })
            if r:rows.append(r)
    return pd.DataFrame(rows)

CORE_B=core_trades(BASE_COST);CORE_S=core_trades(STRESS_COST)
RAW_B=raw_flush(BASE_COST);RAW_S=raw_flush(STRESS_COST)

def select_cluster(df,hours,max_entries,rank):
    if df.empty:return df.copy()
    x=df.copy()
    bucket_ms=hours*3600_000
    x["cluster"]=(x.signal_time//bucket_ms)*bucket_ms
    if rank=="SEVERITY":
        x["rank_score"]=-x.ret6
    elif rank=="RECOVERY":
        x["rank_score"]=x.body_pos
    else:
        x["rank_score"]=(-x.ret6)*x.volz48*x.body_pos
    x=x.sort_values(["cluster","rank_score"],ascending=[True,False])
    x=x.groupby("cluster",sort=False).head(max_entries)
    # same-symbol overlap suppressed after cluster selection
    x=x.sort_values(["symbol","entry_time"])
    keep=[];last={}
    for idx,r in x.iterrows():
        le=last.get(r.symbol,-1)
        if int(r.entry_time)<=le:continue
        keep.append(idx);last[r.symbol]=int(r.exit_time)
    return x.loc[keep].sort_values("entry_time").reset_index(drop=True)

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def weekly_series(d):
    if d.empty:return pd.Series(dtype=float)
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit="ms",utc=True)
    x["week"]=(dt-dt.dt.weekday.astype("timedelta64[D]")).dt.floor("D")
    return x.groupby("week").net_pct.sum()

CORE_W=weekly_series(CORE_B)

def boot(d,n=1500):
    w=weekly_series(d).to_numpy(float)
    if len(w)<15:return 0.
    rng=np.random.default_rng(SEED);vals=np.empty(n)
    for i in range(n):vals[i]=rng.choice(w,len(w),replace=True).mean()
    return float((vals>0).mean())

def stats(d):
    if d.empty:return {"trades":0}
    r=d.net_pct.to_numpy(float);dt=pd.to_datetime(d.entry_time,unit="ms",utc=True)
    q=d.assign(q=dt.dt.to_period("Q").astype(str)).groupby("q").net_pct.sum()
    y=d.assign(y=dt.dt.year).groupby("y").net_pct.sum()
    mo=d.assign(m=dt.dt.to_period("M").astype(str)).groupby("m").net_pct.sum()
    sy=d.groupby("symbol").net_pct.sum();pos=sy.clip(lower=0)
    w=weekly_series(d);common=w.index.intersection(CORE_W.index)
    corr=float(w.loc[common].corr(CORE_W.loc[common])) if len(common)>=10 else None
    return {"trades":int(len(d)),"avg":float(r.mean()),"pf":pf(r),"win_rate":float((r>0).mean()),
            "positive_quarter_rate":float((q>0).mean()),"all_years_positive":bool((y>0).all()),
            "weekly_prob_positive":boot(d),"positive_month_rate":float((mo>0).mean()),
            "median_month_sum":float(mo.median()),"active_months":int(len(mo)),
            "max_positive_symbol_share":float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
            "weekly_corr_core":corr}

rows=[];cache={}
for h in [1,3,6]:
  for mx in [1,2,3]:
    for rank in ["SEVERITY","RECOVERY","COMPOSITE"]:
      name=f"H{h}_N{mx}_{rank}"
      b=select_cluster(RAW_B,h,mx,rank);s=select_cluster(RAW_S,h,mx,rank)
      mb=stats(b);ms=stats(s)
      passed=bool(mb.get("trades",0)>=100 and mb.get("pf",0)>=1.25 and ms.get("pf",0)>=1.20 and
                  mb.get("avg",0)>0 and ms.get("avg",0)>0 and mb.get("all_years_positive",False) and
                  mb.get("positive_quarter_rate",0)>=.70 and mb.get("weekly_prob_positive",0)>=.90 and
                  mb.get("max_positive_symbol_share",1)<=.30 and
                  (mb.get("weekly_corr_core") is None or abs(mb.get("weekly_corr_core"))<=.40))
      rows.append({"name":name,"hours":h,"max_entries":mx,"rank":rank,
                   **{f"base_{k}":v for k,v in mb.items()},**{f"stress_{k}":v for k,v in ms.items()},
                   "passes_gate":passed})
      cache[name]=(b,s)
R=pd.DataFrame(rows).sort_values(["passes_gate","base_weekly_prob_positive","stress_pf"],ascending=[False,False,False])
R.to_csv(OUT/"cluster_grid.csv",index=False)

def combined(core,flush,risk,maxpos):
    events=[]
    for r in core.itertuples(index=False):events.append(("CORE",int(r.entry_time),int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    for r in flush.itertuples(index=False):events.append(("FLUSH",int(r.entry_time),int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    events.sort(key=lambda z:(z[1],0 if z[0]=="CORE" else 1,z[3]))
    eq=START_CAP;curve=[eq];ch=[];fh=[];cs=set();fs=set();uid=ca=fa=rej=0
    def settle(heap,syms,t):
        nonlocal eq
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;syms.discard(sym);curve.append(eq)
    for kind,et,xt,sym,sp,nr in events:
        settle(ch,cs,et);settle(fh,fs,et)
        if kind=="CORE":
            if len(ch)>=CORE_MAX or sym in cs or sym in fs:rej+=1;continue
            rr=CORE_RISK;heap=ch;syms=cs;ca+=1
        else:
            if len(fh)>=maxpos or sym in cs or sym in fs:rej+=1;continue
            rr=risk;heap=fh;syms=fs;fa+=1
        notional=min(eq*NOTIONAL_CAP,eq*rr/max(sp,1e-6));pnl=notional*nr
        heapq.heappush(heap,(xt,uid,pnl,sym));syms.add(sym);uid+=1
    settle(ch,cs,10**30);settle(fh,fs,10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {"end":float(eq),"return":float(eq/START_CAP-1),"max_dd":float(-dd.min()),"core_acc":ca,"flush_acc":fa,"rejected":rej}

empty=pd.DataFrame(columns=CORE_B.columns)
core_b=combined(CORE_B,empty,0,0);core_s=combined(CORE_S,empty,0,0)
P=[]
for rr in R[R.passes_gate].itertuples(index=False):
    b,s=cache[rr.name]
    for risk in [.001,.002,.003,.005]:
      for mx in [1,2,3]:
        pb=combined(CORE_B,b,risk,mx);ps=combined(CORE_S,s,risk,mx)
        ok=bool(pb["return"]>core_b["return"] and ps["return"]>core_s["return"] and
                pb["max_dd"]<=.15 and ps["max_dd"]<=.18)
        P.append({"candidate":rr.name,"risk":risk,"maxpos":mx,
                  "base_return":pb["return"],"base_dd":pb["max_dd"],
                  "stress_return":ps["return"],"stress_dd":ps["max_dd"],
                  "flush_acc":pb["flush_acc"],"passes_portfolio":ok})
P=pd.DataFrame(P)
if len(P):
    P=P.sort_values(["passes_portfolio","base_return"],ascending=[False,False])
    P.to_csv(OUT/"portfolio_grid.csv",index=False)

summary={"version":"R16.9B","fixed_flush":"D9_R60","cluster_candidates":int(len(R)),
         "strict_pass_count":int(R.passes_gate.sum()),"top10":R.head(10).to_dict("records"),
         "core_only":{"base":core_b,"stress":core_s},
         "best_portfolio":P.iloc[0].to_dict() if len(P) and bool(P.iloc[0].passes_portfolio) else None,
         "development_cutoff":"2026-07-01","july_august_used":False,
         "notes":["No leverage.","No ML.","Cross-sectional cluster control is predeclared and causal."]}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
