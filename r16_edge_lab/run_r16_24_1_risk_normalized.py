#!/usr/bin/env python3
"""R16.24.1 Risk-Normalized Recovery.
Frozen entries/signals. Re-simulates original target with alternative stop widths.
Position sizing is risk-normalized: fixed equity risk per trade, capped notional.
No leverage. No entry tuning. September 2026 untouched.
"""
from pathlib import Path
import json,heapq,numpy as np,pandas as pd
ROOT=Path("r16_edge_lab/r16_241_inputs");OUT=Path("r16_edge_lab/r16_24_1_risk_normalized");OUT.mkdir(parents=True,exist_ok=True)
START_CAP=10000.;CAP=.40
CFG={
"CORE":{"src":"core","file":"base_core_trades.csv.gz","iv":"4h","bar":4*3600000,"hold":30,"target_atr":6.0,"risk":.0075,"maxpos":5},
"REV1H":{"src":"rev1h","file":"selected_long_base.csv.gz","iv":"1h","bar":3600000,"hold":24,"target_atr":3.0,"risk":.01,"maxpos":5},
"REV15M":{"src":"rev15m","file":"selected_long_base.csv.gz","iv":"15m","bar":15*60000,"hold":24,"target_atr":3.0,"risk":.015,"maxpos":5}}
HIST={"4h":[ROOT/"pre2024",ROOT/"post"],"1h":[ROOT/"pre2024",ROOT/"post"],"15m":[ROOT/"pre2024_15m",ROOT/"post"]}
STOPS=[1.25,1.5,2.,2.5,3.]
COST={"base":.0032,"stress":.0042}
def ff(root,name):
 h=list(root.rglob(name))
 if not h:raise FileNotFoundError(name)
 return h[0]
def entries(c):
 x=pd.read_csv(ff(ROOT/c["src"],c["file"]))
 for k in ["entry_time","symbol"]: x[k]=x[k]
 return x.sort_values("entry_time")
def px(sym,iv):
 fs=[]
 for root in HIST[iv]:
  p=root/iv/f"{sym}.csv.gz"
  if p.exists():fs.append(pd.read_csv(p,usecols=["open_time","open","high","low","close"]))
 if not fs:return pd.DataFrame()
 x=pd.concat(fs).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
 for c in ["open_time","open","high","low","close"]:x[c]=pd.to_numeric(x[c],errors="coerce")
 pc=x.close.shift();tr=pd.concat([x.high-x.low,(x.high-pc).abs(),(x.low-pc).abs()],axis=1).max(axis=1)
 x["atr"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean();return x
def rebuild(eng,c,sm,cost):
 cache={};rows=[]
 for r in entries(c).itertuples(index=False):
  sym=str(r.symbol)
  if sym not in cache:cache[sym]=px(sym,c["iv"])
  z=cache[sym]
  if z.empty:continue
  a=z.open_time.to_numpy(np.int64);ei=int(np.searchsorted(a,int(r.entry_time)))
  if ei>=len(z) or int(a[ei])!=int(r.entry_time):continue
  atr=float(z.atr.iloc[max(0,ei-1)]);en=float(z.open.iloc[ei])
  if not np.isfinite(atr) or atr<=0 or en<=0:continue
  stop=en-sm*atr;target=en+c["target_atr"]*atr;end=min(ei+c["hold"]-1,len(z)-1)
  xp=float(z.close.iloc[end]);xi=end;reason="TIME"
  for j in range(ei,end+1):
   lo=float(z.low.iloc[j]);hi=float(z.high.iloc[j]);hs=lo<=stop;ht=hi>=target
   if hs and ht:xp=stop;xi=j;reason="STOP_AMBIGUOUS";break
   if hs:xp=stop;xi=j;reason="STOP";break
   if ht:xp=target;xi=j;reason="TARGET";break
  rows.append({"engine":eng,"symbol":sym,"entry_time":int(r.entry_time),"exit_time":int(z.open_time.iloc[xi])+c["bar"],
   "stop_pct":sm*atr/en,"net_pct":xp/en-1-cost,"reason":reason})
 return pd.DataFrame(rows)
def portfolio(d,c):
 eq=peak=START_CAP;curve=[eq];heap=[];held=set();uid=acc=rej=0;monthly={}
 def settle(t):
  nonlocal eq,peak
  while heap and heap[0][0]<=t:
   ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;held.discard(sym);peak=max(peak,eq);curve.append(eq)
   m=str(pd.to_datetime(ex,unit="ms",utc=True).to_period("M"));monthly[m]=monthly.get(m,0)+pnl
 for r in d.sort_values(["entry_time","symbol"]).itertuples(index=False):
  settle(int(r.entry_time))
  if len(heap)>=c["maxpos"] or r.symbol in held:rej+=1;continue
  notional=min(eq*CAP,eq*c["risk"]/max(float(r.stop_pct),1e-9))
  pnl=notional*float(r.net_pct);heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));held.add(r.symbol);uid+=1;acc+=1
 settle(10**30);a=np.array(curve);dd=float(-(a/np.maximum.accumulate(a)-1).min())
 months=pd.period_range("2021-01","2026-06",freq="M").astype(str);vals=[];e=START_CAP
 for m in months:
  p=monthly.get(m,0);vals.append(p/e if e>0 else -1);e+=p
 v=np.array(vals);years={}
 for m,r in zip(months,v):years[m[:4]]=years.get(m[:4],1)*(1+r)
 years={y:q-1 for y,q in years.items()}
 return {"return":eq/START_CAP-1,"dd":dd,"monthly_mean":float(v.mean()),"monthly_median":float(np.median(v)),
 "positive_month":float((v>0).mean()),"worst_month":float(v.min()),"best_month":float(v.max()),"years":years,"accepted":acc,"rejected":rej}
def trade_stats(d):
 r=d.net_pct.to_numpy(float);gp=r[r>0].sum();gl=-r[r<0].sum()
 return {"trades":len(r),"pf":float(gp/gl) if gl else None,"win_rate":float((r>0).mean()),"avg_trade":float(r.mean()),
 "stop_rate":float(d.reason.str.startswith("STOP").mean()),"target_rate":float((d.reason=="TARGET").mean())}
if __name__ == '__main__':
 rows=[];cache={}
 for eng,c in CFG.items():
  for sm in STOPS:
   for scen,cost in COST.items():
    d=rebuild(eng,c,sm,cost);p=portfolio(d,c);t=trade_stats(d)
    rows.append({"engine":eng,"stop_atr":sm,"scenario":scen,**t,**p});cache[(eng,sm,scen)]=d
 R=pd.DataFrame(rows);R.to_csv(OUT/"risk_normalized_grid.csv",index=False)
 sel={}
 for eng in CFG:
  z=R[(R.engine==eng)&(R.scenario=="stress")].copy()
  z["gate"]=(z["return"]>0)&(z.dd<=.35)&(z.monthly_median>0)&(z.positive_month>=.55)&(z.pf>=1.1)
  z["score"]=z.gate.astype(int)*1000+z.monthly_median*100+z.monthly_mean*20-z.dd*10+z.pf
  q=z.sort_values(["gate","score"],ascending=False).iloc[0];sel[eng]=q.to_dict()
  cache[(eng,float(q.stop_atr),"base")].to_csv(OUT/f"{eng.lower()}_selected_base.csv.gz",index=False,compression="gzip")
  cache[(eng,float(q.stop_atr),"stress")].to_csv(OUT/f"{eng.lower()}_selected_stress.csv.gz",index=False,compression="gzip")
 summary={"version":"R16.24.1","selected_stress":sel,"grid":R.to_dict("records"),
 "notes":["Frozen entries; only stop width changes.","Original target ATR preserved per engine.","Risk-normalized sizing with fixed equity risk and 40% notional cap; no leverage.","Stress selection requires positive return, DD<=35%, positive monthly median, >=55% positive months, PF>=1.10.","September 2026 untouched."]}
 (OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8");print(json.dumps(summary,indent=2,default=float))
 