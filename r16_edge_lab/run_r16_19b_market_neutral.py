#!/usr/bin/env python3
"""R16.19B Market-Neutral Cross-Sectional Pair Map.

1h merged history 2021-01-01..2026-06-30.
At UTC-aligned non-overlapping rebalances:
- rank symbols by completed-candle lookback return
- MOM: long top K, short bottom K
- REV: long bottom K, short top K
- 50% gross long + 50% gross short, net ~0, total gross 1x
- enter next 1h open, exit after hold horizon
- costs and conservative short funding included

Grid = 2 modes x 3 lookbacks x 3 holds x 3 K x 2 dispersion floors = 108.
No ML. No signal leverage.
"""
from __future__ import annotations
import json,math
from pathlib import Path
import numpy as np,pandas as pd

PRE=Path('r16_edge_lab/pre2024_history');POST=Path('r15_regime_lab/history')
OUT=Path('r16_edge_lab/r16_19b_market_neutral');OUT.mkdir(parents=True,exist_ok=True)
START=int(pd.Timestamp('2021-01-01T00:00:00Z').timestamp()*1000)
END=int(pd.Timestamp('2026-07-01T00:00:00Z').timestamp()*1000)
BASE=.0016;STRESS=.0021;BASE_F=.0001;STRESS_F=.0002
SEED=16191
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def load(sym):
    fs=[]
    for root in [PRE,POST]:
        p=root/'1h'/f'{sym}.csv.gz'
        if p.exists():fs.append(pd.read_csv(p,usecols=['open_time','open','close']))
    if not fs:return pd.DataFrame()
    x=pd.concat(fs,ignore_index=True)
    for c in ['open_time','open','close']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna().drop_duplicates('open_time').sort_values('open_time')
    return x[(x.open_time>=START)&(x.open_time<END)].reset_index(drop=True)

print('loading matrices',flush=True)
cs=[];os=[]
for s in SYMBOLS:
    x=load(s)
    if x.empty:continue
    idx=x.open_time.astype('int64')
    cs.append(pd.Series(x.close.to_numpy(float),index=idx,name=s))
    os.append(pd.Series(x.open.to_numpy(float),index=idx,name=s))
C=pd.concat(cs,axis=1).sort_index()
O=pd.concat(os,axis=1).reindex(C.index)
T=C.index.to_numpy(np.int64)

# precompute cross-sectional lookback matrices and forward leg returns
RETS={lb:C/C.shift(lb)-1 for lb in [12,24,72]}
FWD={}
for hold in [6,12,24]:
    # next-open -> close hold hours later; row i is signal candle index
    entry=O.shift(-1)
    exitc=C.shift(-(hold+1))
    FWD[hold]=exitc/entry-1

def build(mode,lb,hold,k,disp,cost,fund):
    R=RETS[lb];F=FWD[hold]
    rows=[];fund_units=max(1,math.ceil(hold/8));fund_drag=fund_units*fund
    # non-overlap: signal every hold bars from a fixed UTC anchor
    for i in range(lb,len(C)-hold-2,hold):
        ranks=R.iloc[i].dropna()
        if len(ranks)<max(12,2*k+4) or float(ranks.std())<disp:continue
        if mode=='MOM':
            L=ranks.nlargest(k).index;S=ranks.nsmallest(k).index
        else:
            L=ranks.nsmallest(k).index;S=ranks.nlargest(k).index
        f=F.iloc[i]
        if f[L].isna().any() or f[S].isna().any():continue
        long_net=float(f[L].mean())-2*cost
        short_net=float((-f[S]).mean())-2*cost-fund_drag
        net=.5*(long_net+short_net)
        rows.append({'signal_time':int(T[i]),'entry_time':int(T[i+1]),'exit_time':int(T[i+hold+1]),
                     'pair_net':net,'long_net':long_net,'short_net':short_net,'dispersion':float(ranks.std())})
    return pd.DataFrame(rows)

def pf(x):
    a=np.asarray(x,float);gp=a[a>0].sum();gl=-a[a<0].sum();return float(gp/gl) if gl>0 else None
def weekly(d):
    if d.empty:return pd.Series(dtype=float)
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit='ms',utc=True);x['w']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    return x.groupby('w').pair_net.sum()
def boot(d,n=1200):
    w=weekly(d).to_numpy(float)
    if len(w)<30:return 0.
    rng=np.random.default_rng(SEED)
    vals=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((vals>0).mean())
def stats(d):
    if d.empty:return {'trades':0}
    x=d.copy();a=x.pair_net.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['y']=dt.dt.year;x['q']=dt.dt.to_period('Q').astype(str);x['m']=dt.dt.to_period('M').astype(str)
    y=x.groupby('y').pair_net.sum();q=x.groupby('q').pair_net.sum();m=x.groupby('m').pair_net.sum()
    return {'trades':int(len(x)),'avg':float(a.mean()),'pf':pf(a),'win_rate':float((a>0).mean()),'weekly_prob_positive':boot(x),
            'all_years_positive':bool((y>0).all()),'positive_quarter_rate':float((q>0).mean()),'positive_month_rate':float((m>0).mean()),
            'median_month_sum':float(m.median()),'worst_month_sum':float(m.min()),'best_month_sum':float(m.max()),
            'yearly':{str(int(k)):float(v) for k,v in y.items()}}
def compound(d,alloc=.5):
    eq=10000.;peak=eq;dd=0.;monthly={}
    for r in d.sort_values('exit_time').itertuples(index=False):
        pnl=eq*alloc*float(r.pair_net);eq+=pnl;peak=max(peak,eq);dd=max(dd,1-eq/peak)
        mo=str(pd.to_datetime(int(r.exit_time),unit='ms',utc=True).to_period('M'));monthly[mo]=monthly.get(mo,0)+pnl
    months=pd.period_range('2021-01','2026-06',freq='M').astype(str);vals=[];e=10000.
    for mo in months:
        p=monthly.get(mo,0.);vals.append(p/e if e else 0.);e+=p
    a=np.asarray(vals,float)
    return {'return':float(eq/10000-1),'dd':float(dd),'mean_month':float(a.mean()),'median_month':float(np.median(a)),
            'positive_month_rate':float((a>0).mean()),'m20':int((a>=.20).sum()),'best':float(a.max()),'worst':float(a.min())}

rows=[];cache={}
for mode in ['MOM','REV']:
 for lb in [12,24,72]:
  for hold in [6,12,24]:
   for k in [2,3,5]:
    for disp in [.02,.04]:
        name=f'{mode}_L{lb}_H{hold}_K{k}_D{int(disp*100)}'
        b=build(mode,lb,hold,k,disp,BASE,BASE_F);s=build(mode,lb,hold,k,disp,STRESS,STRESS_F)
        mb=stats(b);ms=stats(s);pb=compound(b,.5);ps=compound(s,.5)
        passed=bool(mb.get('trades',0)>=300 and mb.get('avg',0)>0 and ms.get('avg',0)>0 and
                    mb.get('pf',0)>=1.12 and ms.get('pf',0)>=1.07 and mb.get('weekly_prob_positive',0)>=.95 and
                    mb.get('all_years_positive',False) and mb.get('positive_quarter_rate',0)>=.70 and ps['return']>0 and ps['dd']<=.20)
        rows.append({'name':name,'mode':mode,'lookback':lb,'hold':hold,'k':k,'dispersion':disp,
                     **{f'base_{kk}':vv for kk,vv in mb.items()},**{f'stress_{kk}':vv for kk,vv in ms.items()},
                     'base_sleeve_return':pb['return'],'base_sleeve_dd':pb['dd'],'stress_sleeve_return':ps['return'],'stress_sleeve_dd':ps['dd'],'passes_gate':passed})
        cache[name]=(b,s);print(name,mb.get('pf'),mb.get('trades'),flush=True)
R=pd.DataFrame(rows);R['score']=R.passes_gate.astype(int)*1000+R.base_weekly_prob_positive.fillna(0)*100+R.stress_pf.fillna(0)*10+R.base_positive_quarter_rate.fillna(0)
R=R.sort_values(['passes_gate','score','base_pf'],ascending=[False,False,False]);R.to_csv(OUT/'map.csv',index=False)
p=R[R.passes_gate];sel=p.iloc[0].to_dict() if len(p) else None
if sel:
    b,s=cache[sel['name']];b.to_csv(OUT/'selected_base.csv.gz',index=False,compression='gzip');s.to_csv(OUT/'selected_stress.csv.gz',index=False,compression='gzip')
summary={'version':'R16.19B','variants':int(len(R)),'strict_pass_count':int(R.passes_gate.sum()),'selected':sel,
         'best_momentum':R[R.mode.eq('MOM')].iloc[0].to_dict(),'best_reversal':R[R.mode.eq('REV')].iloc[0].to_dict(),'top10':R.head(10).to_dict('records'),
         'notes':['1x gross synthetic market-neutral basket.','Funding and trading costs included.','September 2026 untouched.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
