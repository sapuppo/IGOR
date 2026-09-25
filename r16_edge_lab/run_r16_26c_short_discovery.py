#!/usr/bin/env python3
"""R16.26C multi-family causal short discovery.
Families: breakdown continuation (R16.11), rally fade and failed recovery (R16.12).
Annual OOS selection uses prior years only. Test-year data never select rules.
"""
from pathlib import Path
import importlib.util,json,numpy as np,pandas as pd
def mod(n,p):
 s=importlib.util.spec_from_file_location(n,Path(p));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
A=mod("r11","r16_edge_lab/run_r16_11_bear_short_map.py");B=mod("r12","r16_edge_lab/run_r16_12_bear_rally_fade.py")
PRE=Path("r16_edge_lab/pre2024_history");POST=Path("r15_regime_lab/history");OUT=Path("r16_edge_lab/r16_26c_short_discovery");OUT.mkdir(parents=True,exist_ok=True)
F={s:A.load_pair(PRE,POST,s) for s in A.SYMBOLS};CTX=A.context(F); C=[]
# compact structurally diverse grid, all stress-costed
for don in [40,70]:
 for adx in [20,30]:
  for br in [.25,.45]:
   for btc in ["STRICT","SOFT"]:
    for st,tg,ho in [(2.,4.,30),(2.,6.,30)]:
     n=f"BD_D{don}_A{adx}_B{br}_{btc}_{st}_{tg}";d=A.simulate_variant(F,CTX,don,adx,br,btc,st,tg,ho,A.STRESS_COST,A.STRESS_FUND_8H);C.append(("BREAKDOWN",n,d))
specs=[]
for lb in [6,12]:
 for rally in [.04,.07]:
  for touch in ["ema20","ema50"]:
   for adx in [18,24]:
    for br in [.35,.45]:
     for btc in ["STRICT","SOFT"]:
      specs.append({"family":"RALLY_FADE","lookback":lb,"rally":rally,"touch":touch,"adx":adx,"breadth":br,"btc":btc,"stop":1.5,"target":3.,"hold":24})
for don in [20,40]:
 for adx in [18,24]:
  for br in [.35,.45]:
   for btc in ["STRICT","SOFT"]:
    specs.append({"family":"FAILED_RECOVERY","don":don,"adx":adx,"breadth":br,"btc":btc,"stop":1.5,"target":3.,"hold":24})
F2={s:B.load_pair(PRE,POST,s) for s in B.SYMBOLS};CTX2=B.context(F2)
for i,s in enumerate(specs):
 n=f"{s['family']}_{i}";d=B.build_variant(F2,CTX2,s,B.STRESS_COST,B.STRESS_FUND_8H);C.append((s["family"],n,d))
def metric(d):
 if len(d)<12:return None
 r=d.net_pct.to_numpy(float);gp=r[r>0].sum();gl=-r[r<0].sum();pf=gp/gl if gl>0 else 9.
 dt=pd.to_datetime(d.entry_time,unit="ms",utc=True);q=d.assign(q=dt.dt.to_period("Q").astype(str)).groupby("q").net_pct.sum();qpos=float((q>0).mean())
 # shrink small samples rather than demand a fixed 20 trades
 shrink=len(d)/(len(d)+30); edge=float(r.mean())*shrink
 return {"n":len(d),"avg":float(r.mean()),"pf":float(pf),"qpos":qpos,"edge_shrunk":edge,"score":edge*100+np.log(max(pf,.01))+.25*qpos}
rows=[];oos=[]
for y in range(2022,2027):
 cut=int(pd.Timestamp(f"{y}-01-01",tz="UTC").timestamp()*1000);end=int(pd.Timestamp(f"{y+1}-01-01",tz="UTC").timestamp()*1000);rank=[]
 for fam,n,d in C:
  m=metric(d[d.entry_time<cut])
  if m and m["edge_shrunk"]>0 and m["pf"]>1:rank.append((m["score"],fam,n,m,d))
 if not rank: rows.append({"year":y,"selected":None});continue
 rank.sort(reverse=True,key=lambda z:z[0]);_,fam,n,m,d=rank[0];t=d[(d.entry_time>=cut)&(d.entry_time<end)].copy()
 if len(t):t["wf_year"]=y;t["family"]=fam;oos.append(t)
 rows.append({"year":y,"family":fam,"selected":n,"train":m,"test_n":len(t),"test_sum":float(t.net_pct.sum()) if len(t) else 0.})
D=pd.concat(oos,ignore_index=True) if oos else pd.DataFrame();port=A.portfolio(D) if len(D) else {"return":0,"max_dd":0}
if len(D):D.to_csv(OUT/"oos_trades.csv.gz",index=False,compression="gzip")
yrs={}
if len(D): yrs={str(int(k)):float(v) for k,v in D.assign(year=pd.to_datetime(D.entry_time,unit="ms",utc=True).dt.year).groupby("year").net_pct.sum().items()}
summary={"version":"R16.26C","families":["BREAKDOWN","RALLY_FADE","FAILED_RECOVERY"],"candidate_count":len(C),"method":"annual prior-only family+rule selection with small-sample shrinkage","stress_costed":True,"selections":rows,"oos_trade_sums_by_year":yrs,"oos_portfolio":port,"guards":["no test-year selection","no leverage","same-bar ambiguity stop-first"],"decision":"integrate_test" if port.get("return",0)>0 and yrs.get("2022",0)>0 else "reject_or_expand_families"}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float));print(json.dumps(summary,indent=2,default=float))
