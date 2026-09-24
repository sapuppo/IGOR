#!/usr/bin/env python3
"""R16.17 Three-Engine No-Leverage Portfolio Frontier.

Inputs are frozen trade files from:
- R16.10 CORE 4h
- R16.14 1h extreme-reversion LONG
- R16.16 15m extreme-reversion LONG

No signal tuning here. Only portfolio allocation:
- global gross exposure <= 100% equity
- per-position notional <= 20%
- same symbol cannot be held by two engines simultaneously
- conservative open-risk drawdown

Grid:
CORE risk: 0.25%, 0.50%, 0.75%
REV1H risk: 0.50%, 0.75%, 1.00%
REV15M risk: 0.50%, 0.75%, 1.00%, 1.50%
REV15M max positions: 5 or 8
"""
from __future__ import annotations
import json,heapq
from pathlib import Path
import numpy as np,pandas as pd

ROOT=Path('r16_edge_lab/r16_17_inputs')
OUT=Path('r16_edge_lab/r16_17_three_engine_frontier');OUT.mkdir(parents=True,exist_ok=True)
START_CAP=10000.;GLOBAL_CAP=1.0;PER_POS=.20

def load(path,engine):
    x=pd.read_csv(path)
    x['engine']=engine
    for c in ['entry_time','exit_time','stop_pct','net_pct']:x[c]=pd.to_numeric(x[c],errors='coerce')
    return x.dropna(subset=['entry_time','exit_time','stop_pct','net_pct'])

def weekly(d):
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    return x.groupby('week').net_pct.sum()

def corr_matrix(frames):
    s={k:weekly(v) for k,v in frames.items()}
    allidx=None
    for v in s.values():allidx=v.index if allidx is None else allidx.union(v.index)
    D=pd.DataFrame({k:v.reindex(allidx).fillna(0.) for k,v in s.items()})
    return D.corr().to_dict()

def simulate(frames,risks,maxpos,priority):
    events=[]
    for eng,df in frames.items():
        for r in df.itertuples(index=False):
            events.append((eng,int(r.entry_time),int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    pri={e:i for i,e in enumerate(priority)}
    events.sort(key=lambda z:(z[1],pri[z[0]],z[3]))
    eq=START_CAP;peak=eq;worst=0.;uid=0;gross=0.
    heaps={e:[] for e in frames};active={e:set() for e in frames};held_symbols=set()
    accepted={e:0 for e in frames};rejected=0;monthly_pnl={}
    def openrisk():
        return sum(h[6] for e in heaps for h in heaps[e])
    def settle(t):
        nonlocal eq,peak,worst,gross
        due=[]
        for e in heaps:
            while heaps[e] and heaps[e][0][0]<=t:due.append(heapq.heappop(heaps[e]))
        due.sort()
        for ex,_,pnl,sym,e,notional,riskamt in due:
            eq+=pnl;gross-=notional;active[e].discard(sym);held_symbols.discard(sym)
            mo=str(pd.to_datetime(ex,unit='ms',utc=True).to_period('M'));monthly_pnl[mo]=monthly_pnl.get(mo,0.)+pnl
            peak=max(peak,eq);worst=max(worst,1-(eq-openrisk())/peak)
    for e,et,xt,sym,sp,nr in events:
        settle(et)
        if len(heaps[e])>=maxpos[e] or sym in held_symbols:
            rejected+=1;continue
        riskamt_des=eq*risks[e]
        desired=min(eq*PER_POS,riskamt_des/max(sp,1e-6))
        cap=max(0.,eq*GLOBAL_CAP-gross);notional=min(desired,cap)
        if notional<eq*.005:
            rejected+=1;continue
        riskamt=notional*sp;pnl=notional*nr
        heapq.heappush(heaps[e],(xt,uid,pnl,sym,e,notional,riskamt));uid+=1
        active[e].add(sym);held_symbols.add(sym);gross+=notional;accepted[e]+=1
        worst=max(worst,1-(eq-openrisk())/peak)
    settle(10**30)
    months=pd.period_range('2021-01','2026-06',freq='M').astype(str)
    vals=[];eql=START_CAP
    for mo in months:
        p=monthly_pnl.get(mo,0.);ret=p/eql if eql>0 else 0.;vals.append(ret);eql+=p
    a=np.asarray(vals,float)
    return {'end':float(eq),'return':float(eq/START_CAP-1),'dd':float(worst),'accepted':accepted,'rejected':rejected,
            'monthly_mean':float(a.mean()),'monthly_median':float(np.median(a)),'positive_month_rate':float((a>0).mean()),
            'months_ge_10':int((a>=.10).sum()),'months_ge_20':int((a>=.20).sum()),'best_month':float(a.max()),'worst_month':float(a.min()),
            'monthly_returns':vals}

def findfile(base,needle):
    hits=list(base.rglob(needle))
    if not hits:raise FileNotFoundError(f'{needle} under {base}')
    return hits[0]

core_b=load(findfile(ROOT/'core','base_core_trades.csv.gz'),'CORE')
core_s=load(findfile(ROOT/'core','stress_core_trades.csv.gz'),'CORE')
r1_b=load(findfile(ROOT/'rev1h','selected_long_base.csv.gz'),'REV1H')
r1_s=load(findfile(ROOT/'rev1h','selected_long_stress.csv.gz'),'REV1H')
r15_b=load(findfile(ROOT/'rev15m','selected_long_base.csv.gz'),'REV15M')
r15_s=load(findfile(ROOT/'rev15m','selected_long_stress.csv.gz'),'REV15M')

BASE={'CORE':core_b,'REV1H':r1_b,'REV15M':r15_b}
STRESS={'CORE':core_s,'REV1H':r1_s,'REV15M':r15_s}
corr=corr_matrix(BASE)

rows=[]
for cr in [.0025,.005,.0075]:
 for r1 in [.005,.0075,.01]:
  for r15 in [.005,.0075,.01,.015]:
   for m15 in [5,8]:
    risks={'CORE':cr,'REV1H':r1,'REV15M':r15}
    maxpos={'CORE':5,'REV1H':5,'REV15M':m15}
    b=simulate(BASE,risks,maxpos,['CORE','REV15M','REV1H'])
    s=simulate(STRESS,risks,maxpos,['CORE','REV15M','REV1H'])
    robust=bool(b['dd']<=.25 and s['dd']<=.28 and s['return']>0)
    rows.append({'core_risk':cr,'rev1h_risk':r1,'rev15m_risk':r15,'rev15m_max':m15,
                 'base_return':b['return'],'base_dd':b['dd'],'base_mean_month':b['monthly_mean'],'base_median_month':b['monthly_median'],
                 'base_pos_month_rate':b['positive_month_rate'],'base_m20':b['months_ge_20'],'base_best':b['best_month'],'base_worst':b['worst_month'],
                 'stress_return':s['return'],'stress_dd':s['dd'],'stress_mean_month':s['monthly_mean'],'stress_median_month':s['monthly_median'],
                 'stress_pos_month_rate':s['positive_month_rate'],'stress_m20':s['months_ge_20'],'stress_best':s['best_month'],'stress_worst':s['worst_month'],
                 'robust':robust})
R=pd.DataFrame(rows).sort_values(['robust','stress_return','stress_dd'],ascending=[False,False,True]);R.to_csv(OUT/'frontier.csv',index=False)
sel=(R[R.robust].iloc[0] if len(R[R.robust]) else R.iloc[0]).to_dict()
risks={'CORE':float(sel['core_risk']),'REV1H':float(sel['rev1h_risk']),'REV15M':float(sel['rev15m_risk'])}
maxpos={'CORE':5,'REV1H':5,'REV15M':int(sel['rev15m_max'])}
b=simulate(BASE,risks,maxpos,['CORE','REV15M','REV1H']);s=simulate(STRESS,risks,maxpos,['CORE','REV15M','REV1H'])
months=pd.period_range('2021-01','2026-06',freq='M').astype(str)
pd.DataFrame({'month':months,'base_return':b['monthly_returns'],'stress_return':s['monthly_returns']}).to_csv(OUT/'selected_monthly.csv',index=False)
summary={'version':'R16.17','period':'2021-01-01..2026-06-30','engines':['CORE','REV1H','REV15M'],
         'weekly_return_correlation':corr,'grid_size':int(len(R)),'selected':sel,
         'selected_base':{k:v for k,v in b.items() if k!='monthly_returns'},'selected_stress':{k:v for k,v in s.items() if k!='monthly_returns'},
         'project_target_monthly':.20,'notes':['No leverage; global gross cap 100%.','Same-symbol overlap blocked across engines.','Open-risk drawdown used.','September 2026 untouched.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
