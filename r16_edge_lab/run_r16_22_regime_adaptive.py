#!/usr/bin/env python3
"""R16.22 Regime-Adaptive Portfolio.
Frozen signals only. Allocation/regime selection; no signal tuning.
Uses CORE4H, REV1H and REV15M. Chooses monthly risk state causally from
prior-month engine performance and realized portfolio drawdown.
Goal: improve median/consistency without accepting tail-driven 20% means.
"""
from __future__ import annotations
import json, heapq
from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path("r16_edge_lab/r16_22_inputs")
OUT=Path("r16_edge_lab/r16_22_regime_adaptive"); OUT.mkdir(parents=True,exist_ok=True)
START_CAP=10000.; PER=.40
BASE_RISK={"CORE":.0075,"REV1H":.01,"REV15M":.015}
MAXPOS={"CORE":5,"REV1H":5,"REV15M":5}
MONTHS=pd.period_range("2021-01","2026-06",freq="M").astype(str)

def ff(base,name):
    h=list(base.rglob(name))
    if not h: raise FileNotFoundError(name)
    return h[0]
def load(path,eng,fund):
    x=pd.read_csv(path); x["engine"]=eng
    for c in ["entry_time","exit_time","stop_pct","net_pct"]: x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna(subset=["entry_time","exit_time","stop_pct","net_pct"]).copy()
    hrs=(x.exit_time-x.entry_time)/3600000; x["net_pct"]-=np.maximum(1,np.ceil(hrs/8))*fund
    x["entry_month"]=pd.to_datetime(x.entry_time,unit="ms",utc=True).dt.to_period("M").astype(str)
    return x
def frames(cost):
    fund=.0001 if cost=="base" else .0002
    return {
      "CORE":load(ff(ROOT/"core",f"{cost}_core_trades.csv.gz"),"CORE",fund),
      "REV1H":load(ff(ROOT/"rev1h",f"selected_long_{cost}.csv.gz"),"REV1H",fund),
      "REV15M":load(ff(ROOT/"rev15m",f"selected_long_{cost}.csv.gz"),"REV15M",fund)}
def prior_scores(F,lookback):
    scores={m:{} for m in MONTHS}
    for eng,d in F.items():
        z=d.copy(); z["month"]=z.entry_month
        mr=z.groupby("month").net_pct.mean()
        for i,m in enumerate(MONTHS):
            hist=MONTHS[max(0,i-lookback):i]
            v=mr.reindex(hist).dropna()
            scores[m][eng]=float(v.mean()) if len(v) else 0.
    return scores
def sim(F,lookback,hot,cold,gross_hot,gross_cold,dd_brake):
    scores=prior_scores(F,lookback); events=[]
    for eng,d in F.items():
        for r in d.itertuples(index=False):
            events.append((int(r.entry_time),eng,int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct),r.entry_month))
    pri={"CORE":0,"REV15M":1,"REV1H":2}; events.sort(key=lambda x:(x[0],pri[x[1]],x[3]))
    eq=peak=START_CAP; gross=0.; uid=0; heap=[]; held=set(); monthly={}; accepted={e:0 for e in F}; rejected=0; worst=0.
    def openrisk(): return sum(h[6] for h in heap)
    def settle(t):
        nonlocal eq,peak,worst,gross
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym,eng,no,ra=heapq.heappop(heap); eq+=pnl; gross-=no; held.discard(sym)
            mo=str(pd.to_datetime(ex,unit="ms",utc=True).to_period("M")); monthly[mo]=monthly.get(mo,0.)+pnl
            peak=max(peak,eq); worst=max(worst,1-(eq-openrisk())/peak)
    for et,eng,xt,sym,sp,nr,mo in events:
        settle(et); dd=1-eq/max(peak,1e-9)
        sc=scores.get(mo,{}); vals=np.array(list(sc.values()),float); market=float(vals.mean()) if len(vals) else 0.
        regime_hot=market>0 and sum(v>0 for v in sc.values())>=2
        mult=hot if regime_hot else cold; gcap=gross_hot if regime_hot else gross_cold
        # engine must have non-negative trailing evidence unless CORE in cold regime
        if sc.get(eng,0)<0 and not (eng=="CORE" and not regime_hot): rejected+=1; continue
        if dd>=dd_brake: mult*=.5; gcap=min(gcap,1.0)
        if sum(1 for h in heap if h[4]==eng)>=MAXPOS[eng] or sym in held: rejected+=1; continue
        risk=eq*BASE_RISK[eng]*mult; desired=min(eq*PER,risk/max(sp,1e-6)); no=min(desired,max(0.,eq*gcap-gross))
        if no<eq*.005: rejected+=1; continue
        ra=no*sp; pnl=no*nr; heapq.heappush(heap,(xt,uid,pnl,sym,eng,no,ra)); uid+=1; held.add(sym); gross+=no; accepted[eng]+=1
        worst=max(worst,1-(eq-openrisk())/peak)
    settle(10**30)
    vals=[]; eql=START_CAP
    for m in MONTHS:
        p=monthly.get(m,0.); r=p/eql if eql>0 else -1.; vals.append(r); eql+=p
    a=np.asarray(vals); years={}
    for m,r in zip(MONTHS,a): years[m[:4]]=years.get(m[:4],1.)*(1+r)
    years={y:v-1 for y,v in years.items()}
    return {"end":eq,"return":eq/START_CAP-1,"dd":worst,"monthly_mean":a.mean(),"monthly_median":np.median(a),
      "positive_month_rate":(a>0).mean(),"m10":int((a>=.10).sum()),"m20":int((a>=.20).sum()),
      "best":a.max(),"worst":a.min(),"years":years,"accepted":accepted,"rejected":rejected,"monthly":vals}
B=frames("base"); S=frames("stress"); rows=[]; cache={}
for lb in [2,3,6]:
 for hot in [1.0,1.5,2.0]:
  for cold in [.5,.75,1.0]:
   for gh in [1.0,1.5,2.0]:
    for gc in [.6,.8,1.0]:
     for brake in [.10,.15,.20]:
      b=sim(B,lb,hot,cold,gh,gc,brake); s=sim(S,lb,hot,cold,gh,gc,brake)
      robust=(s["return"]>0 and s["dd"]<=.35 and s["worst"]>=-.20 and s["monthly_median"]>0 and
              s["positive_month_rate"]>=.55 and min(s["years"].values())>=-.15)
      target=(s["monthly_mean"]>=.20 and s["monthly_median"]>=.10)
      rows.append({"lookback":lb,"hot_mult":hot,"cold_mult":cold,"gross_hot":gh,"gross_cold":gc,"dd_brake":brake,
       "base_return":b["return"],"base_dd":b["dd"],"base_mean":b["monthly_mean"],"base_median":b["monthly_median"],
       "stress_return":s["return"],"stress_dd":s["dd"],"stress_mean":s["monthly_mean"],"stress_median":s["monthly_median"],
       "stress_pos_month":s["positive_month_rate"],"stress_m20":s["m20"],"stress_best":s["best"],"stress_worst":s["worst"],
       "robust":robust,"target20_distribution":target}); cache[(lb,hot,cold,gh,gc,brake)]=(b,s)
R=pd.DataFrame(rows)
R["score"]=R.robust.astype(int)*1000+R.stress_median*100+R.stress_mean*20-R.stress_dd*10+R.stress_pos_month
R=R.sort_values(["robust","target20_distribution","score"],ascending=[False,False,False]); R.to_csv(OUT/"grid.csv",index=False)
sel=R.iloc[0]; key=(int(sel.lookback),float(sel.hot_mult),float(sel.cold_mult),float(sel.gross_hot),float(sel.gross_cold),float(sel.dd_brake)); b,s=cache[key]
pd.DataFrame({"month":MONTHS,"base":b["monthly"],"stress":s["monthly"]}).to_csv(OUT/"selected_monthly.csv",index=False)
summary={"version":"R16.22","selected":sel.to_dict(),"selected_base":{k:v for k,v in b.items() if k!="monthly"},
"selected_stress":{k:v for k,v in s.items() if k!="monthly"},"strict_robust_count":int(R.robust.sum()),
"target20_distribution_count":int(R.target20_distribution.sum()),
"notes":["Frozen signals; allocation/regime only.","Causal prior-month state.","20% mean alone is not approval.","September 2026 untouched."]}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float)); print(json.dumps(summary,indent=2,default=float))
