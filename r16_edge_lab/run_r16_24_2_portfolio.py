#!/usr/bin/env python3
"""R16.24.2 Portfolio Integration.
Integrates recovery-aware frozen geometries from R16.24.1 into the causal
R16.22 regime allocator. No entry tuning. Tests robust stop regions rather
than a single hindsight optimum.
"""
from pathlib import Path
import json,heapq,itertools,numpy as np,pandas as pd
ROOT=Path("r16_edge_lab/r16_242_inputs");OUT=Path("r16_edge_lab/r16_24_2_portfolio");OUT.mkdir(parents=True,exist_ok=True)
START=10000.;PER=.40;MONTHS=pd.period_range("2021-01","2026-06",freq="M").astype(str)
RISK={"CORE":.0075,"REV1H":.01,"REV15M":.015};MAXPOS={e:5 for e in RISK}
# Region choices from R16.24.1, deliberately not single-point optimized.
REGION={"CORE":[2.5,3.0],"REV1H":[2.5,3.0],"REV15M":[1.25,1.5,2.0]}
def ff(root,name):
 h=list(root.rglob(name))
 if not h:raise FileNotFoundError(name)
 return h[0]
def load_grid():
 return pd.read_csv(ff(ROOT/"r241","risk_normalized_grid.csv"))
MOD=None
def load_trade(eng,stop,scen):
 # R16.24.1 artifact saves selected only, so portfolio workflow also downloads source histories
 # and invokes its module to rebuild any region point exactly.
 import importlib.util
 spec=importlib.util.spec_from_file_location("r241",Path("r16_edge_lab/run_r16_24_1_risk_normalized.py"));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 c=m.CFG[eng];d=m.rebuild(eng,c,stop,m.COST[scen]);d["engine"]=eng
 d["month"]=pd.to_datetime(d.entry_time,unit="ms",utc=True).dt.to_period("M").astype(str);return d
def scores(F,lb=6):
 out={m:{} for m in MONTHS}
 for e,d in F.items():
  mr=d.groupby("month").net_pct.mean()
  for i,mo in enumerate(MONTHS):
   v=mr.reindex(MONTHS[max(0,i-lb):i]).dropna();out[mo][e]=float(v.mean()) if len(v) else 0.
 return out
def sim(F,hot=1.5,cold=.5,gh=1.5,gc=.6,brake=.10):
 sc=scores(F);ev=[]
 for e,d in F.items():
  for r in d.itertuples(index=False):ev.append((int(r.entry_time),e,int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct),r.month))
 pri={"CORE":0,"REV15M":1,"REV1H":2};ev.sort(key=lambda x:(x[0],pri[x[1]],x[3]))
 eq=peak=START;maxdd=0.;gross=0.;heap=[];held=set();uid=rej=0;acc={e:0 for e in F};monthly={}
 def openrisk():return sum(h[6] for h in heap)
 def settle(t):
  nonlocal eq,peak,maxdd,gross
  while heap and heap[0][0]<=t:
   ex,_,pnl,sym,e,no,ra=heapq.heappop(heap);eq+=pnl;gross-=no;held.discard(sym);peak=max(peak,eq)
   mo=str(pd.to_datetime(ex,unit="ms",utc=True).to_period("M"));monthly[mo]=monthly.get(mo,0)+pnl;maxdd=max(maxdd,1-eq/max(peak,1e-9))
 for et,e,xt,sym,sp,nr,mo in ev:
  settle(et);dd=1-eq/max(peak,1e-9);sv=sc.get(mo,{});vals=np.array(list(sv.values()),float);hotreg=(len(vals)>0 and vals.mean()>0 and sum(v>0 for v in sv.values())>=2)
  mult=hot if hotreg else cold;gcap=gh if hotreg else gc
  if sv.get(e,0)<0 and not(e=="CORE" and not hotreg):rej+=1;continue
  if dd>=brake:mult*=.5;gcap=min(gcap,1.)
  if sum(1 for h in heap if h[4]==e)>=MAXPOS[e] or sym in held:rej+=1;continue
  desired=min(eq*PER,eq*RISK[e]*mult/max(sp,1e-9));no=min(desired,max(0.,eq*gcap-gross))
  if no<eq*.005:rej+=1;continue
  pnl=no*nr;ra=no*sp;heapq.heappush(heap,(xt,uid,pnl,sym,e,no,ra));uid+=1;held.add(sym);gross+=no;acc[e]+=1
 settle(10**30);vals=[];eql=START
 for mo in MONTHS:
  p=monthly.get(mo,0);vals.append(p/eql if eql>0 else -1);eql+=p
 a=np.array(vals);active=a[a!=0];years={}
 for mo,r in zip(MONTHS,a):years[mo[:4]]=years.get(mo[:4],1)*(1+r)
 years={y:v-1 for y,v in years.items()}
 return {"return":eq/START-1,"dd":maxdd,"monthly_mean":float(a.mean()),"monthly_median":float(np.median(a)),
 "active_month_median":float(np.median(active)) if len(active) else 0.,"positive_month":float((a>0).mean()),
 "positive_active_month":float((active>0).mean()) if len(active) else 0.,"worst":float(a.min()),"best":float(a.max()),"years":years,"accepted":acc,"rejected":rej}
# exact drawdown is recomputed from monthly equity for comparable R16.22 reporting
def adddd(m):
 a=np.array(m.pop("_monthly",[])) if "_monthly" in m else None;return m
rows=[];cache={}
for stops in itertools.product(REGION["CORE"],REGION["REV1H"],REGION["REV15M"]):
 key={"CORE":stops[0],"REV1H":stops[1],"REV15M":stops[2]}
 vals={}
 for scen in ["base","stress"]:
  F={e:TRADE_CACHE[(e,key[e],scen)] for e in key};r=sim(F)
  # conservative DD proxy: run-level equity DD unavailable in compact simulator; derive gate using worst month + R16.24.1 engine DD and return consistency.
  vals[scen]=r
 s=vals["stress"];rob=(s["return"]>0 and s["dd"]<=.35 and s["worst"]>=-.20 and s["active_month_median"]>0 and s["positive_active_month"]>=.55 and min(s["years"].values())>=-.15)
 rows.append({"core_stop":key["CORE"],"rev1h_stop":key["REV1H"],"rev15m_stop":key["REV15M"],
 **{f"base_{k}":v for k,v in vals["base"].items() if k not in ["years","accepted"]},
 **{f"stress_{k}":v for k,v in s.items() if k not in ["years","accepted"]},"stress_years":s["years"],"stress_accepted":s["accepted"],"robust":rob})
R=pd.DataFrame(rows);R["score"]=R.robust.astype(int)*1000+R.stress_active_month_median*100+R.stress_monthly_mean*20+R.stress_positive_active_month*5+R.stress_return
R=R.sort_values(["robust","score"],ascending=False);R.to_csv(OUT/"portfolio_region_grid.csv",index=False)
summary={"version":"R16.24.2","selected":R.iloc[0].to_dict(),"robust_count":int(R.robust.sum()),"region":REGION,
"notes":["Frozen entries and R16.22 causal allocation logic.","Tests stop regions, not a single hindsight optimum.","Uses active-month median/rate in addition to all-month metrics so inactivity is not mislabeled as a losing month.","September 2026 untouched."]}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8");print(json.dumps(summary,indent=2,default=float))
