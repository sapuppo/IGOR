#!/usr/bin/env python3
"""R16.19B Fast causal cross-sectional momentum rotation.

1h data, 2021-01-01..2026-06-30.
At timestamps aligned exactly to hold horizon, rank completed-candle momentum,
enter next hour open and exit exactly hold hours later at open.

Grid:
lookback 24/72/168h
hold 12/24/48h
K 1/3/5
regime ALL / BTC_BULL / BREADTH_BULL
min momentum 0% / 2%

No leverage, no overlapping rebalance vintages.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np,pandas as pd

PRE=Path('r16_edge_lab/pre2024_history');POST=Path('r15_regime_lab/history')
OUT=Path('r16_edge_lab/r16_19b_cross_momentum');OUT.mkdir(parents=True,exist_ok=True)
START=int(pd.Timestamp('2021-01-01T00:00:00Z').timestamp()*1000);END=int(pd.Timestamp('2026-07-01T00:00:00Z').timestamp()*1000)
BASE=.0032;STRESS=.0042;SEED=16191
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

frames={s:load(s) for s in SYMBOLS}
idx=sorted(set().union(*[set(x.open_time.astype('int64')) for x in frames.values() if len(x)]))
IDX=np.asarray(idx,dtype='int64');N=len(IDX);M=len(SYMBOLS);col={s:i for i,s in enumerate(SYMBOLS)}
O=np.full((N,M),np.nan);C=np.full((N,M),np.nan)
for s,x in frames.items():
    if x.empty:continue
    pos=np.searchsorted(IDX,x.open_time.to_numpy(dtype='int64'));j=col[s]
    O[pos,j]=x.open.to_numpy(float);C[pos,j]=x.close.to_numpy(float)

# returns and EMA200 causally
RET={}
for lb in [24,72,168]:
    a=np.full_like(C,np.nan)
    a[lb:]=C[lb:]/C[:-lb]-1
    RET[lb]=a
EMA=np.full_like(C,np.nan)
alpha=2/201
for j in range(M):
    ser=pd.Series(C[:,j]);EMA[:,j]=ser.ewm(span=200,adjust=False,min_periods=200).mean().to_numpy()
BREADTH=np.nanmean(np.where(np.isfinite(EMA),C>EMA,np.nan),axis=1)
btcj=col['BTCUSDT'];btc_ret72=RET[72][:,btcj]

def positions(hold):
    # exact epoch-aligned non-overlapping vintages
    step=hold*3600_000
    p=np.flatnonzero((IDX%step)==0)
    return p[(p>=200)&(p+hold+1<N)]

def run(lb,hold,k,regime,minmom,cost):
    rows=[]
    for p in positions(hold):
        if regime=='BTC_BULL':
            if not (np.isfinite(EMA[p,btcj]) and C[p,btcj]>EMA[p,btcj] and btc_ret72[p]>0):continue
        elif regime=='BREADTH_BULL':
            if not (BREADTH[p]>=.55):continue
        sig=RET[lb][p].copy()
        valid=np.isfinite(sig)&(sig>=minmom)
        if not valid.any():continue
        ids=np.flatnonzero(valid)
        order=ids[np.argsort(sig[ids])[::-1]]
        picks=order[:k]
        ep=p+1;xp=p+1+hold
        en=O[ep,picks];ex=O[xp,picks]
        ok=np.isfinite(en)&np.isfinite(ex)&(en>0)
        if not ok.any():continue
        rr=ex[ok]/en[ok]-1-cost
        rows.append((int(IDX[ep]),int(IDX[xp]),float(np.mean(rr)),int(ok.sum())))
    return pd.DataFrame(rows,columns=['entry_time','exit_time','ret','n'])

def boot(x,n=2000):
    if x.empty:return 0.
    z=x.copy();dt=pd.to_datetime(z.entry_time,unit='ms',utc=True);z['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    w=z.groupby('week').ret.sum().to_numpy(float)
    if len(w)<20:return 0.
    rng=np.random.default_rng(SEED);v=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((v>0).mean())

def met(x):
    if x.empty:return {'periods':0}
    r=x.ret.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True);z=x.copy();z['y']=dt.dt.year;z['q']=dt.dt.to_period('Q').astype(str);z['m']=dt.dt.to_period('M').astype(str)
    yr=z.groupby('y').ret.apply(lambda s:(1+s).prod()-1);qr=z.groupby('q').ret.apply(lambda s:(1+s).prod()-1);mr=z.groupby('m').ret.apply(lambda s:(1+s).prod()-1)
    eq=np.cumprod(1+r);peak=np.maximum.accumulate(eq);dd=eq/peak-1;gp=r[r>0].sum();gl=-r[r<0].sum()
    return {'periods':int(len(z)),'avg_period':float(r.mean()),'pf':float(gp/gl) if gl>0 else None,'win_rate':float((r>0).mean()),
            'bootstrap':boot(z),'positive_year_rate':float((yr>0).mean()),'positive_quarter_rate':float((qr>0).mean()),
            'positive_month_rate':float((mr>0).mean()),'monthly_mean':float(mr.mean()),'monthly_median':float(mr.median()),
            'best_month':float(mr.max()),'worst_month':float(mr.min()),'max_dd':float(-dd.min()),'total_return':float(eq[-1]-1),
            'yearly':{str(int(k)):float(v) for k,v in yr.items()}}

if __name__ == '__main__':
    rows=[];cache={}
    for lb in [24,72,168]:
     for hold in [12,24,48]:
      for k in [1,3,5]:
       for reg in ['ALL','BTC_BULL','BREADTH_BULL']:
        for mm in [0.,.02]:
         name=f'MOM_L{lb}_H{hold}_K{k}_{reg}_M{int(mm*100)}'
         b=run(lb,hold,k,reg,mm,BASE);s=run(lb,hold,k,reg,mm,STRESS);mb=met(b);ms=met(s)
         passed=bool(mb.get('periods',0)>=100 and mb.get('pf',0)>=1.10 and ms.get('pf',0)>=1.05 and mb.get('bootstrap',0)>=.95 and
                     mb.get('positive_year_rate',0)>=.80 and mb.get('positive_quarter_rate',0)>=.65 and ms.get('total_return',0)>0 and ms.get('max_dd',1)<=.35)
         rows.append({'name':name,'lb':lb,'hold':hold,'k':k,'regime':reg,'minmom':mm,
                      **{f'base_{a}':v for a,v in mb.items()},**{f'stress_{a}':v for a,v in ms.items()},'passes_gate':passed})
         cache[name]=(b,s)
    R=pd.DataFrame(rows);R['score']=R.passes_gate.astype(int)*1000+R.base_bootstrap.fillna(0)*100+R.stress_pf.fillna(0)*10+R.base_positive_year_rate.fillna(0)
    R=R.sort_values(['passes_gate','score','stress_monthly_mean'],ascending=[False,False,False]);R.to_csv(OUT/'momentum_map.csv',index=False)
    p=R[R.passes_gate];sel=p.iloc[0].to_dict() if len(p) else None
    if sel:
        b,s=cache[sel['name']];b.to_csv(OUT/'selected_base.csv',index=False);s.to_csv(OUT/'selected_stress.csv',index=False)
    summary={'version':'R16.19B','period':'2021-01-01..2026-06-30','variants':int(len(R)),'strict_pass_count':int(R.passes_gate.sum()),'selected':sel,'top10':R.head(10).to_dict('records'),
             'notes':['No leverage.','No overlapping vintages.','Next-open causal execution.','September 2026 untouched.']}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
    