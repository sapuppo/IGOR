#!/usr/bin/env python3
"""R16.18 Controlled Leverage Frontier.

Frozen inputs: CORE, REV1H, REV15M trade lists.
No signal tuning.

Base risk vector from R16.17:
 CORE 0.75%, REV1H 1.0%, REV15M 1.5%.

Grid:
- gross exposure cap: 1x, 1.5x, 2x, 3x, 5x equity
- risk multiplier: 1x, 1.5x, 2x, 3x
- per-position notional cap: 40% equity
- engine position caps unchanged: CORE5, REV1H5, REV15M5

Funding drag is added to all long trades:
 base 0.01% / 8h, stress 0.02% / 8h.

Reports monthly mean/median, months >=20%, worst month and conservative open-risk DD.
"""
from __future__ import annotations
import json,heapq,math
from pathlib import Path
import numpy as np,pandas as pd

ROOT=Path('r16_edge_lab/r16_18_inputs');OUT=Path('r16_edge_lab/r16_18_leverage_frontier');OUT.mkdir(parents=True,exist_ok=True)
START_CAP=10000.;PER_POS=.40
BASE_RISKS={'CORE':.0075,'REV1H':.01,'REV15M':.015}
MAXPOS={'CORE':5,'REV1H':5,'REV15M':5}

def ff(base,name):
    h=list(base.rglob(name))
    if not h:raise FileNotFoundError(name)
    return h[0]
def load(path,engine,fund8h):
    x=pd.read_csv(path)
    x['engine']=engine
    for c in ['entry_time','exit_time','stop_pct','net_pct']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['entry_time','exit_time','stop_pct','net_pct'])
    hrs=(x.exit_time-x.entry_time)/3600_000
    units=np.maximum(1,np.ceil(hrs/8))
    x['net_pct']=x.net_pct-units*fund8h
    return x

def sim(frames,risk_mult,gross_cap):
    events=[]
    for e,d in frames.items():
        for r in d.itertuples(index=False):events.append((e,int(r.entry_time),int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    pri={'CORE':0,'REV15M':1,'REV1H':2};events.sort(key=lambda z:(z[1],pri[z[0]],z[3]))
    eq=START_CAP;peak=eq;worst=0.;gross=0.;uid=0
    heaps={e:[] for e in frames};held=set();monthly={};acc={e:0 for e in frames};rej=0
    def openrisk():return sum(h[6] for e in heaps for h in heaps[e])
    def settle(t):
        nonlocal eq,peak,worst,gross
        due=[]
        for e in heaps:
            while heaps[e] and heaps[e][0][0]<=t:due.append(heapq.heappop(heaps[e]))
        due.sort()
        for ex,_,pnl,sym,e,notional,riskamt in due:
            eq+=pnl;gross-=notional;held.discard(sym)
            mo=str(pd.to_datetime(ex,unit='ms',utc=True).to_period('M'));monthly[mo]=monthly.get(mo,0.)+pnl
            peak=max(peak,eq);worst=max(worst,1-(eq-openrisk())/peak)
    for e,et,xt,sym,sp,nr in events:
        settle(et)
        if len(heaps[e])>=MAXPOS[e] or sym in held:rej+=1;continue
        risk=eq*BASE_RISKS[e]*risk_mult
        desired=min(eq*PER_POS,risk/max(sp,1e-6))
        cap=max(0.,eq*gross_cap-gross);notional=min(desired,cap)
        if notional<eq*.005:rej+=1;continue
        riskamt=notional*sp;pnl=notional*nr
        heapq.heappush(heaps[e],(xt,uid,pnl,sym,e,notional,riskamt));uid+=1;held.add(sym);gross+=notional;acc[e]+=1
        worst=max(worst,1-(eq-openrisk())/peak)
    settle(10**30)
    months=pd.period_range('2021-01','2026-06',freq='M').astype(str)
    vals=[];eql=START_CAP
    for mo in months:
        p=monthly.get(mo,0.);ret=p/eql if eql>0 else 0.;vals.append(ret);eql+=p
    a=np.asarray(vals,float)
    return {'end':float(eq),'return':float(eq/START_CAP-1),'dd':float(worst),'accepted':acc,'rejected':rej,
            'monthly_mean':float(a.mean()),'monthly_median':float(np.median(a)),'positive_month_rate':float((a>0).mean()),
            'm10':int((a>=.10).sum()),'m20':int((a>=.20).sum()),'best':float(a.max()),'worst':float(a.min()),'monthly':vals}

B={'CORE':load(ff(ROOT/'core','base_core_trades.csv.gz'),'CORE',.0001),
   'REV1H':load(ff(ROOT/'rev1h','selected_long_base.csv.gz'),'REV1H',.0001),
   'REV15M':load(ff(ROOT/'rev15m','selected_long_base.csv.gz'),'REV15M',.0001)}
S={'CORE':load(ff(ROOT/'core','stress_core_trades.csv.gz'),'CORE',.0002),
   'REV1H':load(ff(ROOT/'rev1h','selected_long_stress.csv.gz'),'REV1H',.0002),
   'REV15M':load(ff(ROOT/'rev15m','selected_long_stress.csv.gz'),'REV15M',.0002)}

rows=[];cache={}
for g in [1.,1.5,2.,3.,5.]:
 for rm in [1.,1.5,2.,3.]:
    b=sim(B,rm,g);s=sim(S,rm,g)
    acceptable=bool(s['dd']<=.50 and s['worst']>=-.25 and s['return']>0)
    target=bool(s['monthly_mean']>=.20)
    rows.append({'gross_cap':g,'risk_mult':rm,'base_return':b['return'],'base_dd':b['dd'],'base_mean':b['monthly_mean'],'base_median':b['monthly_median'],'base_m20':b['m20'],'base_best':b['best'],'base_worst':b['worst'],
                 'stress_return':s['return'],'stress_dd':s['dd'],'stress_mean':s['monthly_mean'],'stress_median':s['monthly_median'],'stress_m20':s['m20'],'stress_best':s['best'],'stress_worst':s['worst'],
                 'acceptable':acceptable,'target_mean_20':target})
    cache[(g,rm)]=(b,s)
R=pd.DataFrame(rows).sort_values(['target_mean_20','acceptable','stress_mean','stress_dd'],ascending=[False,False,False,True]);R.to_csv(OUT/'leverage_frontier.csv',index=False)
target=R[R.target_mean_20 & R.acceptable]
if len(target):sel=target.sort_values(['stress_dd','gross_cap','risk_mult']).iloc[0].to_dict()
else:
    ok=R[R.acceptable];sel=(ok.iloc[0] if len(ok) else R.iloc[0]).to_dict()
b,s=cache[(float(sel['gross_cap']),float(sel['risk_mult']))]
months=pd.period_range('2021-01','2026-06',freq='M').astype(str)
pd.DataFrame({'month':months,'base_return':b['monthly'],'stress_return':s['monthly']}).to_csv(OUT/'selected_monthly.csv',index=False)
summary={'version':'R16.18','selected':sel,'selected_base':{k:v for k,v in b.items() if k!='monthly'},'selected_stress':{k:v for k,v in s.items() if k!='monthly'},
         'target_monthly_mean':.20,'target_reached_in_acceptable_grid':bool(len(target)),
         'notes':['Frozen signals.','Funding drag included.','Gross cap is total portfolio notional / equity.','This is a risk study, not a return guarantee.','September 2026 remains untouched.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
