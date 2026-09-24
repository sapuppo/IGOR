#!/usr/bin/env python3
"""R16.19C Fast Market-Neutral Cross-Sectional Map.

Equivalent intent to R16.19B but vectorized / epoch-aligned.
1h, 2021-01-01..2026-06-30.
Long top-K + short bottom-K (MOM) or opposite (REV), 50/50 gross.
Entry next open, exit after hold hours at open. No overlapping vintages.
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np, pandas as pd

PRE=Path('r16_edge_lab/pre2024_history');POST=Path('r15_regime_lab/history')
OUT=Path('r16_edge_lab/r16_19c_market_neutral_fast');OUT.mkdir(parents=True,exist_ok=True)
START=int(pd.Timestamp('2021-01-01T00:00:00Z').timestamp()*1000);END=int(pd.Timestamp('2026-07-01T00:00:00Z').timestamp()*1000)
BASE=.0016;STRESS=.0021;BASE_F=.0001;STRESS_F=.0002;SEED=16192
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def load(s):
    fs=[]
    for root in [PRE,POST]:
        p=root/'1h'/f'{s}.csv.gz'
        if p.exists():fs.append(pd.read_csv(p,usecols=['open_time','open','close']))
    if not fs:return pd.DataFrame()
    x=pd.concat(fs,ignore_index=True)
    for c in ['open_time','open','close']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna().drop_duplicates('open_time').sort_values('open_time')
    return x[(x.open_time>=START)&(x.open_time<END)].reset_index(drop=True)

F={s:load(s) for s in SYMBOLS}
idx=sorted(set().union(*[set(x.open_time.astype('int64')) for x in F.values() if len(x)]))
T=np.asarray(idx,dtype='int64');N=len(T);M=len(SYMBOLS);col={s:i for i,s in enumerate(SYMBOLS)}
O=np.full((N,M),np.nan);C=np.full((N,M),np.nan)
for s,x in F.items():
    if x.empty:continue
    p=np.searchsorted(T,x.open_time.to_numpy(dtype='int64'));j=col[s];O[p,j]=x.open.to_numpy(float);C[p,j]=x.close.to_numpy(float)
RET={}
for lb in [12,24,72]:
    a=np.full_like(C,np.nan);a[lb:]=C[lb:]/C[:-lb]-1;RET[lb]=a

def pos_for(hold,lb):
    step=hold*3600_000
    p=np.flatnonzero((T%step)==0)
    return p[(p>=lb)&(p+hold+1<N)]

def build(mode,lb,hold,k,disp,cost,fund):
    rows=[];fund_drag=max(1,math.ceil(hold/8))*fund
    for p in pos_for(hold,lb):
        ranks=RET[lb][p];valid=np.isfinite(ranks)
        ids=np.flatnonzero(valid)
        if len(ids)<max(12,2*k+4):continue
        vals=ranks[ids]
        if float(np.std(vals,ddof=1))<disp:continue
        order=ids[np.argsort(vals)]
        if mode=='MOM':S=order[:k];L=order[-k:]
        else:L=order[:k];S=order[-k:]
        ep=p+1;xp=p+hold+1
        len_=O[ep,L];lex=O[xp,L];sen=O[ep,S];sex=O[xp,S]
        okL=np.isfinite(len_)&np.isfinite(lex)&(len_>0)
        okS=np.isfinite(sen)&np.isfinite(sex)&(sen>0)
        if okL.sum()!=k or okS.sum()!=k:continue
        long_net=float(np.mean(lex/len_-1))-2*cost
        short_net=float(np.mean(1-sex/sen))-2*cost-fund_drag
        pair=.5*(long_net+short_net)
        rows.append((int(T[ep]),int(T[xp]),pair,long_net,short_net,float(np.std(vals,ddof=1))))
    return pd.DataFrame(rows,columns=['entry_time','exit_time','pair_net','long_net','short_net','dispersion'])

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum();return float(gp/gl) if gl>0 else None
def boot(x,n=2000):
    if x.empty:return 0.
    z=x.copy();dt=pd.to_datetime(z.entry_time,unit='ms',utc=True);z['w']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    w=z.groupby('w').pair_net.sum().to_numpy(float)
    if len(w)<20:return 0.
    rng=np.random.default_rng(SEED);v=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((v>0).mean())
def met(x):
    if x.empty:return {'trades':0}
    a=x.pair_net.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True);z=x.copy();z['y']=dt.dt.year;z['q']=dt.dt.to_period('Q').astype(str);z['m']=dt.dt.to_period('M').astype(str)
    yr=z.groupby('y').pair_net.apply(lambda s:(1+s).prod()-1);qr=z.groupby('q').pair_net.apply(lambda s:(1+s).prod()-1);mr=z.groupby('m').pair_net.apply(lambda s:(1+s).prod()-1)
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);dd=eq/peak-1
    return {'trades':int(len(z)),'avg':float(a.mean()),'pf':pf(a),'win_rate':float((a>0).mean()),'bootstrap':boot(z),
            'positive_year_rate':float((yr>0).mean()),'all_years_positive':bool((yr>0).all()),'positive_quarter_rate':float((qr>0).mean()),
            'positive_month_rate':float((mr>0).mean()),'monthly_mean':float(mr.mean()),'monthly_median':float(mr.median()),
            'best_month':float(mr.max()),'worst_month':float(mr.min()),'max_dd':float(-dd.min()),'total_return':float(eq[-1]-1),
            'yearly':{str(int(k)):float(v) for k,v in yr.items()}}

rows=[];cache={}
for mode in ['MOM','REV']:
 for lb in [12,24,72]:
  for hold in [6,12,24]:
   for k in [2,3,5]:
    for disp in [.02,.04]:
     name=f'{mode}_L{lb}_H{hold}_K{k}_D{int(disp*100)}'
     b=build(mode,lb,hold,k,disp,BASE,BASE_F);s=build(mode,lb,hold,k,disp,STRESS,STRESS_F);mb=met(b);ms=met(s)
     passed=bool(mb.get('trades',0)>=300 and mb.get('pf',0)>=1.12 and ms.get('pf',0)>=1.07 and mb.get('bootstrap',0)>=.95 and
                 mb.get('all_years_positive',False) and mb.get('positive_quarter_rate',0)>=.70 and mb.get('positive_month_rate',0)>=.55 and
                 ms.get('total_return',0)>0 and ms.get('max_dd',1)<=.25 and ms.get('worst_month',-1)>=-.15)
     rows.append({'name':name,'mode':mode,'lookback':lb,'hold':hold,'k':k,'dispersion':disp,
                  **{f'base_{q}':v for q,v in mb.items()},**{f'stress_{q}':v for q,v in ms.items()},'passes_gate':passed})
     cache[name]=(b,s)
R=pd.DataFrame(rows);R['score']=R.passes_gate.astype(int)*1000+R.stress_monthly_mean.fillna(-9)*100+R.base_bootstrap.fillna(0)*10-R.stress_max_dd.fillna(1)
R=R.sort_values(['passes_gate','score','stress_monthly_mean'],ascending=[False,False,False]);R.to_csv(OUT/'market_neutral_map.csv',index=False)
p=R[R.passes_gate];sel=p.iloc[0].to_dict() if len(p) else None
if sel:
    b,s=cache[sel['name']];b.to_csv(OUT/'selected_base.csv',index=False);s.to_csv(OUT/'selected_stress.csv',index=False)
summary={'version':'R16.19C','period':'2021-01-01..2026-06-30','variants':int(len(R)),'strict_pass_count':int(R.passes_gate.sum()),
         'selected':sel,'top10':R.head(10).to_dict('records'),'notes':['1x gross 50/50 market-neutral.','No overlapping vintages.','Costs+short funding included.','September 2026 untouched.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
