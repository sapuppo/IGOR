#!/usr/bin/env python3
"""R16.26B causal adaptive short walk-forward.
Candidate short rules are generated from R16.11. For each test year Y, the
chosen rule is selected strictly from trades with entry_time < Jan 1 Y.
No test-year performance participates in selection.
"""
from pathlib import Path
import json, importlib.util, numpy as np, pandas as pd
P=Path("r16_edge_lab/run_r16_11_bear_short_map.py")
spec=importlib.util.spec_from_file_location("r11",P); M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
OUT=Path("r16_edge_lab/r16_26b_short_walkforward");OUT.mkdir(parents=True,exist_ok=True)
F={s:M.load_pair(Path("r16_edge_lab/pre2024_history"),Path("r15_regime_lab/history"),s) for s in M.SYMBOLS};CTX=M.context(F)
cands=[]
for don in [40,55,70]:
 for adx in [20,25,30]:
  for br in [.25,.35,.45]:
   for btc in ["STRICT","SOFT"]:
    for stop,target,hold in [(2.,4.,30),(2.,6.,30)]:
     name=f"D{don}_A{adx}_B{int(br*100)}_{btc}_S{stop}_T{target}_H{hold}"
     d=M.simulate_variant(F,CTX,don,adx,br,btc,stop,target,hold,M.STRESS_COST,M.STRESS_FUND_8H)
     if len(d): d["candidate"]=name
     cands.append((name,d))
def met(d):
 if len(d)<20:return None
 r=d.net_pct.to_numpy(float); gp=r[r>0].sum();gl=-r[r<0].sum();pf=gp/gl if gl>0 else 9.
 dt=pd.to_datetime(d.entry_time,unit="ms",utc=True);q=d.assign(q=dt.dt.to_period("Q").astype(str)).groupby("q").net_pct.sum()
 return {"n":len(d),"avg":float(r.mean()),"pf":float(pf),"qpos":float((q>0).mean()),"score":float(pf+20*r.mean()+.25*(q>0).mean())}
oos=[]; selections=[]
for year in range(2022,2027):
 cut=int(pd.Timestamp(f"{year}-01-01",tz="UTC").timestamp()*1000);end=int(pd.Timestamp(f"{year+1}-01-01",tz="UTC").timestamp()*1000)
 ranked=[]
 for name,d in cands:
  tr=d[d.entry_time<cut];mm=met(tr)
  if mm and mm["avg"]>0 and mm["pf"]>1.0: ranked.append((mm["score"],name,mm,d))
 if not ranked:
  selections.append({"year":year,"selected":None,"reason":"no positive prior-only candidate"});continue
 ranked.sort(reverse=True,key=lambda x:x[0]);_,name,mm,d=ranked[0]
 test=d[(d.entry_time>=cut)&(d.entry_time<end)].copy()
 if len(test):oos.append(test)
 selections.append({"year":year,"selected":name,"train":mm,"test_trades":int(len(test)),"test_trade_sum":float(test.net_pct.sum()) if len(test) else 0.})
D=pd.concat(oos,ignore_index=True) if oos else pd.DataFrame()
if len(D):D.to_csv(OUT/"oos_trades.csv.gz",index=False,compression="gzip")
port=M.portfolio(D) if len(D) else {"return":0,"max_dd":0}
years={}
if len(D):
 dt=pd.to_datetime(D.entry_time,unit="ms",utc=True);z=D.assign(year=dt.dt.year)
 years={str(int(k)):float(v) for k,v in z.groupby("year").net_pct.sum().items()}
summary={"version":"R16.26B","method":"annual expanding walk-forward; selection uses prior years only","cost":"R16.11 stress costs + stress funding","selections":selections,"oos_trade_sums_by_year":years,"oos_portfolio":port,
"guards":["2022 selected from 2021 only","test-year returns excluded from selection","no leverage","same-bar stop+target remains stop-first"],
"decision":"candidate_for_portfolio_integration" if port.get("return",0)>0 and port.get("max_dd",1)<.35 and years.get("2022",0)>0 else "redesign_again"}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float));print(json.dumps(summary,indent=2,default=float))
