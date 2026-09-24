#!/usr/bin/env python3
"""R16.17 Frozen Triple-Engine Portfolio Frontier.

Frozen trade streams:
CORE 4h from R16.10
REV1H from R16.14 LONG_M8_V15_B60_G1_C3
REV15 from R16.16 LONG_L16_M8_V20_B60_G1_C3

No signal tuning here. Allocation only.

Grid:
CORE risk 0.50 / 0.75 / 1.00%
REV1H risk 0.50 / 1.00 / 1.50%
REV15 risk 0.50 / 1.00 / 1.50%
priority: CORE_FIRST / ALPHA_FIRST
global gross cap: 100% equity (no leverage)
aggregate symbol notional cap: 25%
engine per-position caps: CORE25%, REV1H20%, REV15 15%
"""
from __future__ import annotations
import json,heapq
from pathlib import Path
import numpy as np,pandas as pd

START_CAP=10000.
GLOBAL_CAP=1.0
SYM_CAP=.25
CAPS={'CORE':.25,'REV1H':.20,'REV15':.15}
MAXPOS={'CORE':5,'REV1H':5,'REV15':8}
OUT=Path('r16_edge_lab/r16_17_triple_frontier');OUT.mkdir(parents=True,exist_ok=True)

def load(path,engine):
    x=pd.read_csv(path)
    x['engine']=engine
    for c in ['entry_time','exit_time','stop_pct','net_pct']:
        x[c]=pd.to_numeric(x[c],errors='coerce')
    return x.dropna(subset=['entry_time','exit_time','stop_pct','net_pct']).copy()

def load_set(cost):
    core=load(f'r16_edge_lab/input_r16_10/{cost}_core_trades.csv.gz','CORE')
    rev1=load(f'r16_edge_lab/input_r16_14/selected_long_{cost}.csv.gz','REV1H')
    rev15=load(f'r16_edge_lab/input_r16_16/selected_long_{cost}.csv.gz','REV15')
    return {'CORE':core,'REV1H':rev1,'REV15':rev15}

def simulate(streams,risks,priority):
    pr={'CORE_FIRST':{'CORE':0,'REV15':1,'REV1H':2},'ALPHA_FIRST':{'REV15':0,'REV1H':1,'CORE':2}}[priority]
    events=[]
    for eng,df in streams.items():
        for r in df.itertuples(index=False):
            events.append((int(r.entry_time),pr[eng],eng,int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    events.sort(key=lambda x:(x[0],x[1],x[5]))

    eq=START_CAP;peak=eq;worst=0.;uid=0
    heaps={e:[] for e in streams};engine_count={e:0 for e in streams}
    gross=0.;sym_notional={};active_lots={}
    monthly_pnl={};accepted={e:0 for e in streams};rejected=0

    def open_risk():
        return sum(v['risk'] for v in active_lots.values())

    def settle(t):
        nonlocal eq,peak,worst,gross
        due=[]
        for eng,h in heaps.items():
            while h and h[0][0]<=t:due.append(heapq.heappop(h))
        due.sort()
        for ex,lid,pnl,sym,eng,notional,risk_amt in due:
            eq+=pnl;gross-=notional
            sym_notional[sym]=max(0.,sym_notional.get(sym,0.)-notional)
            if sym_notional[sym]<=1e-9:sym_notional.pop(sym,None)
            active_lots.pop(lid,None);engine_count[eng]-=1
            mo=str(pd.to_datetime(ex,unit='ms',utc=True).to_period('M'))
            monthly_pnl[mo]=monthly_pnl.get(mo,0.)+pnl
            peak=max(peak,eq)
            worst=max(worst,1-(eq-open_risk())/peak)

    for et,_,eng,xt,sym,sp,nr in events:
        settle(et)
        if engine_count[eng]>=MAXPOS[eng]:
            rejected+=1;continue
        desired=min(eq*CAPS[eng],eq*risks[eng]/max(sp,1e-6))
        gcap=max(0.,eq*GLOBAL_CAP-gross)
        scap=max(0.,eq*SYM_CAP-sym_notional.get(sym,0.))
        notional=min(desired,gcap,scap)
        if notional<eq*.005:
            rejected+=1;continue
        risk_amt=notional*sp;pnl=notional*nr
        lid=uid;uid+=1
        heapq.heappush(heaps[eng],(xt,lid,pnl,sym,eng,notional,risk_amt))
        active_lots[lid]={'risk':risk_amt}
        engine_count[eng]+=1;gross+=notional;sym_notional[sym]=sym_notional.get(sym,0.)+notional;accepted[eng]+=1
        peak=max(peak,eq);worst=max(worst,1-(eq-open_risk())/peak)
    settle(10**30)

    months=pd.period_range('2021-01','2026-06',freq='M').astype(str)
    vals=[];e=START_CAP
    for mo in months:
        p=monthly_pnl.get(mo,0.);ret=p/e if e>0 else 0.;vals.append(ret);e+=p
    a=np.asarray(vals,float)
    years={}
    for mo,r in zip(months,a):
        y=mo[:4];years[y]=years.get(y,1.)*(1+r)
    years={y:v-1 for y,v in years.items()}
    return {
      'end':float(eq),'return':float(eq/START_CAP-1),'open_risk_dd':float(worst),
      'accepted':accepted,'rejected':rejected,
      'monthly_mean':float(a.mean()),'monthly_median':float(np.median(a)),
      'positive_month_rate':float((a>0).mean()),
      'months_ge_05':int((a>=.05).sum()),'months_ge_10':int((a>=.10).sum()),'months_ge_20':int((a>=.20).sum()),
      'best_month':float(a.max()),'worst_month':float(a.min()),
      'year_returns':years,'monthly_returns':vals
    }

def main():
    B=load_set('base');S=load_set('stress')
    rows=[];cache={}
    for cr in [.005,.0075,.01]:
      for r1 in [.005,.01,.015]:
       for r15 in [.005,.01,.015]:
        for priority in ['CORE_FIRST','ALPHA_FIRST']:
            risks={'CORE':cr,'REV1H':r1,'REV15':r15}
            b=simulate(B,risks,priority);s=simulate(S,risks,priority)
            robust=bool(b['open_risk_dd']<=.25 and s['open_risk_dd']<=.30 and s['return']>0 and min(s['year_returns'].values())>-.25)
            rows.append({
              'core_risk':cr,'rev1_risk':r1,'rev15_risk':r15,'priority':priority,
              'base_return':b['return'],'base_dd':b['open_risk_dd'],'base_month_mean':b['monthly_mean'],'base_month_median':b['monthly_median'],
              'base_pos_month_rate':b['positive_month_rate'],'base_m05':b['months_ge_05'],'base_m10':b['months_ge_10'],'base_m20':b['months_ge_20'],
              'base_best':b['best_month'],'base_worst':b['worst_month'],
              'stress_return':s['return'],'stress_dd':s['open_risk_dd'],'stress_month_mean':s['monthly_mean'],'stress_month_median':s['monthly_median'],
              'stress_pos_month_rate':s['positive_month_rate'],'stress_m05':s['months_ge_05'],'stress_m10':s['months_ge_10'],'stress_m20':s['months_ge_20'],
              'stress_best':s['best_month'],'stress_worst':s['worst_month'],'robust':robust
            })
            cache[(cr,r1,r15,priority)]=(b,s)
    R=pd.DataFrame(rows).sort_values(['robust','stress_month_mean','stress_return','stress_dd'],ascending=[False,False,False,True])
    R.to_csv(OUT/'triple_frontier.csv',index=False)
    rr=R[R.robust].iloc[0] if R.robust.any() else R.iloc[0]
    key=(float(rr.core_risk),float(rr.rev1_risk),float(rr.rev15_risk),rr.priority)
    b,s=cache[key]
    months=pd.period_range('2021-01','2026-06',freq='M').astype(str)
    pd.DataFrame({'month':months,'base_return':b['monthly_returns'],'stress_return':s['monthly_returns']}).to_csv(OUT/'selected_monthly.csv',index=False)
    summary={
      'version':'R16.17','period':'2021-01-01..2026-06-30',
      'engines':['CORE4H','REV1H','REV15M'],'global_gross_cap':GLOBAL_CAP,'symbol_cap':SYM_CAP,
      'grid_size':int(len(R)),'selected':rr.to_dict(),
      'selected_base':{k:v for k,v in b.items() if k!='monthly_returns'},
      'selected_stress':{k:v for k,v in s.items() if k!='monthly_returns'},
      'project_target_monthly':.20,
      'notes':['No leverage.','All signal streams frozen before this allocation study.','September 2026 remains untouched.']
    }
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8')
    print(json.dumps(summary,indent=2,default=float),flush=True)
if __name__=='__main__':main()
