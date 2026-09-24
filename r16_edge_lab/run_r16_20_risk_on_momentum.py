#!/usr/bin/env python3
"""R16.20 Risk-On Gate for Frozen Cross-Sectional Momentum.

Frozen signal from R16.19B:
- 1h data
- exact epoch-aligned rebalance every 48h
- rank 72h return
- select top 1
- selected coin momentum >= +2%
- existing causal BTC bull gate: BTC close > 1h EMA200 and BTC 72h return > 0
- entry next 1h open, exit 48h later at open
- no overlapping vintages

ONLY additional market-regime gates are varied:
- BTC 30d return minimum: 0 / 5 / 10%
- market breadth minimum: 55 / 65 / 75%
- breadth 24h slope: none / >=0 / >=+5pp
- long-term BTC trend: none / close>EMA200d / EMA50d>EMA200d

No leverage. No signal/holding/ranking tuning. Sep-2026 remains untouched.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np,pandas as pd

PRE=Path('r16_edge_lab/pre2024_history');POST=Path('r15_regime_lab/history')
OUT=Path('r16_edge_lab/r16_20_risk_on_momentum');OUT.mkdir(parents=True,exist_ok=True)
START=int(pd.Timestamp('2021-01-01T00:00:00Z').timestamp()*1000)
END=int(pd.Timestamp('2026-07-01T00:00:00Z').timestamp()*1000)
BASE_COST=.0032;STRESS_COST=.0042;SEED=16200
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

F={s:load(s) for s in SYMBOLS}
idx=sorted(set().union(*[set(x.open_time.astype('int64')) for x in F.values() if len(x)]))
IDX=np.asarray(idx,dtype='int64');N=len(IDX);M=len(SYMBOLS);col={s:i for i,s in enumerate(SYMBOLS)}
O=np.full((N,M),np.nan);C=np.full((N,M),np.nan)
for s,x in F.items():
    if x.empty:continue
    p=np.searchsorted(IDX,x.open_time.to_numpy(dtype='int64'));j=col[s]
    O[p,j]=x.open.to_numpy(float);C[p,j]=x.close.to_numpy(float)

RET72=np.full_like(C,np.nan);RET72[72:]=C[72:]/C[:-72]-1
EMA200H=np.full_like(C,np.nan)
for j in range(M):
    EMA200H[:,j]=pd.Series(C[:,j]).ewm(span=200,adjust=False,min_periods=200).mean().to_numpy()
BREADTH=np.nanmean(np.where(np.isfinite(EMA200H),C>EMA200H,np.nan),axis=1)
BSLOPE24=np.full(N,np.nan);BSLOPE24[24:]=BREADTH[24:]-BREADTH[:-24]

bj=col['BTCUSDT'];btc=C[:,bj]
BTCEMA200H=EMA200H[:,bj]
BTCRET72=RET72[:,bj]
BTCRET720=np.full(N,np.nan);BTCRET720[720:]=btc[720:]/btc[:-720]-1
BTCEMA50D=pd.Series(btc).ewm(span=1200,adjust=False,min_periods=1200).mean().to_numpy()
BTCEMA200D=pd.Series(btc).ewm(span=4800,adjust=False,min_periods=4800).mean().to_numpy()

# Freeze raw candidate periods and selected asset before varying the extra regime gate.
step=48*3600_000
pos=np.flatnonzero((IDX%step)==0)
pos=pos[(pos>=4800)&(pos+49<N)]
raw=[]
for p in pos:
    # frozen existing BTC_BULL
    if not (np.isfinite(BTCEMA200H[p]) and btc[p]>BTCEMA200H[p] and BTCRET72[p]>0):continue
    sig=RET72[p].copy();valid=np.isfinite(sig)&(sig>=.02)
    if not valid.any():continue
    ids=np.flatnonzero(valid);pick=int(ids[np.argmax(sig[ids])])
    ep=p+1;xp=p+49;en=O[ep,pick];ex=O[xp,pick]
    if not (np.isfinite(en) and np.isfinite(ex) and en>0):continue
    raw.append({'p':int(p),'signal_time':int(IDX[p]),'entry_time':int(IDX[ep]),'exit_time':int(IDX[xp]),
                'symbol':SYMBOLS[pick],'gross':float(ex/en-1),
                'btc30':float(BTCRET720[p]) if np.isfinite(BTCRET720[p]) else np.nan,
                'breadth':float(BREADTH[p]),'bslope24':float(BSLOPE24[p]) if np.isfinite(BSLOPE24[p]) else np.nan,
                'btc_close':float(btc[p]),'ema50d':float(BTCEMA50D[p]) if np.isfinite(BTCEMA50D[p]) else np.nan,
                'ema200d':float(BTCEMA200D[p]) if np.isfinite(BTCEMA200D[p]) else np.nan})
RAW=pd.DataFrame(raw)
RAW.to_csv(OUT/'frozen_raw_periods.csv',index=False)

def apply(g30,bmin,slope,trend,cost):
    x=RAW.copy()
    m=(x.btc30>=g30)&(x.breadth>=bmin)
    if slope is not None:m&=x.bslope24>=slope
    if trend=='ABOVE200D':m&=x.btc_close>x.ema200d
    elif trend=='EMA50GT200D':m&=x.ema50d>x.ema200d
    x=x[m].copy();x['ret']=x.gross-cost
    return x

def boot(x,n=2500):
    if x.empty:return 0.
    z=x.copy();dt=pd.to_datetime(z.entry_time,unit='ms',utc=True)
    z['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    w=z.groupby('week').ret.sum().to_numpy(float)
    if len(w)<20:return 0.
    rng=np.random.default_rng(SEED)
    vals=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((vals>0).mean())

def met(x):
    if x.empty:return {'periods':0}
    r=x.ret.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    z=x.copy();z['y']=dt.dt.year;z['q']=dt.dt.to_period('Q').astype(str);z['m']=dt.dt.to_period('M').astype(str)
    yr=z.groupby('y').ret.apply(lambda s:(1+s).prod()-1);qr=z.groupby('q').ret.apply(lambda s:(1+s).prod()-1);mr=z.groupby('m').ret.apply(lambda s:(1+s).prod()-1)
    eq=np.cumprod(1+r);peak=np.maximum.accumulate(eq);dd=eq/peak-1
    gp=r[r>0].sum();gl=-r[r<0].sum()
    return {'periods':int(len(z)),'avg_period':float(r.mean()),'pf':float(gp/gl) if gl>0 else None,
            'bootstrap':boot(z),'win_rate':float((r>0).mean()),
            'positive_year_rate':float((yr>0).mean()),'positive_quarter_rate':float((qr>0).mean()),
            'positive_month_rate':float((mr>0).mean()),'monthly_mean':float(mr.mean()),'monthly_median':float(mr.median()),
            'best_month':float(mr.max()),'worst_month':float(mr.min()),'max_dd':float(-dd.min()),'total_return':float(eq[-1]-1),
            'yearly':{str(int(k)):float(v) for k,v in yr.items()}}

rows=[];cache={}
for g30 in [0.,.05,.10]:
 for bmin in [.55,.65,.75]:
  for slope in [None,0.,.05]:
   for trend in ['NONE','ABOVE200D','EMA50GT200D']:
    name=f'R{int(g30*100)}_B{int(bmin*100)}_S{"N" if slope is None else int(slope*100)}_{trend}'
    b=apply(g30,bmin,slope,trend,BASE_COST);s=apply(g30,bmin,slope,trend,STRESS_COST)
    mb=met(b);ms=met(s)
    passed=bool(mb.get('periods',0)>=80 and mb.get('pf',0)>=1.15 and ms.get('pf',0)>=1.10 and mb.get('bootstrap',0)>=.95 and
                mb.get('positive_year_rate',0)>=.80 and mb.get('positive_quarter_rate',0)>=.65 and mb.get('positive_month_rate',0)>=.50 and
                ms.get('max_dd',1)<=.40 and ms.get('worst_month',-1)>=-.25 and ms.get('total_return',0)>0)
    rows.append({'name':name,'btc30_min':g30,'breadth_min':bmin,'breadth_slope24_min':slope,'trend':trend,
                 **{f'base_{k}':v for k,v in mb.items()},**{f'stress_{k}':v for k,v in ms.items()},'passes_gate':passed})
    cache[name]=(b,s)

R=pd.DataFrame(rows)
R['score']=R.passes_gate.astype(int)*1000+R.stress_monthly_mean.fillna(-9)*100+R.base_bootstrap.fillna(0)*10-R.stress_max_dd.fillna(1)
R=R.sort_values(['passes_gate','score','stress_monthly_mean'],ascending=[False,False,False])
R.to_csv(OUT/'risk_on_gate_grid.csv',index=False)
p=R[R.passes_gate];sel=p.iloc[0].to_dict() if len(p) else None
if sel:
    b,s=cache[sel['name']];b.to_csv(OUT/'selected_base.csv',index=False);s.to_csv(OUT/'selected_stress.csv',index=False)
summary={'version':'R16.20','frozen_signal':'MOM_L72_H48_K1_BTC_BULL_M2','period':'2021-01-01..2026-06-30',
         'raw_periods':int(len(RAW)),'candidate_gates':int(len(R)),'strict_pass_count':int(R.passes_gate.sum()),
         'selected':sel,'top10':R.head(10).to_dict('records'),
         'notes':['Only higher-timeframe risk-on gate varied.','No leverage.','No signal/ranking/holding tuning.','September 2026 untouched.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8')
print(json.dumps(summary,indent=2,default=float),flush=True)
