#!/usr/bin/env python3
"""R16.19 Cross-Sectional Rotation Map.

Independent long-only engine on 1h data.
At fixed UTC rebalances, rank the universe using only completed candles,
enter at next 1h open, hold until the next rebalance.

Families:
- MOM: top K by 24h / 72h / 168h return.
- REV: bottom K by 12h / 24h return, only when market breadth is depressed.

Grid:
MOM:
 lookback 24/72/168h, hold 12/24/48h, K 1/3/5,
 regime ALL/BTC_BULL/BREADTH_BULL, min momentum 0/2%.
REV:
 lookback 12/24h, hold 6/12/24h, K 1/3/5,
 breadth ceiling 35/45%, require next-open market rebound proxy via BTC signal candle body positive? 
 To remain causal: require BTC 6h return <= -3% and current BTC close > prior close.

No leverage. Equal weight. Full notional <=100%.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np,pandas as pd

PRE=Path('r16_edge_lab/pre2024_history')
POST=Path('r15_regime_lab/history')
OUT=Path('r16_edge_lab/r16_19_cross_sectional')
OUT.mkdir(parents=True,exist_ok=True)
START=int(pd.Timestamp('2021-01-01T00:00:00Z').timestamp()*1000)
END=int(pd.Timestamp('2026-07-01T00:00:00Z').timestamp()*1000)
BASE_RT=.0032
STRESS_RT=.0042
SEED=16190
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def load(sym):
    fs=[]
    for root in [PRE,POST]:
        p=root/'1h'/f'{sym}.csv.gz'
        if p.exists():fs.append(pd.read_csv(p))
    if not fs:return pd.DataFrame()
    x=pd.concat(fs,ignore_index=True)
    for c in ['open_time','open','high','low','close','volume']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close']).drop_duplicates('open_time').sort_values('open_time')
    x=x[(x.open_time>=START)&(x.open_time<END)].reset_index(drop=True)
    c=x.close
    x['ema200']=c.ewm(span=200,adjust=False,min_periods=200).mean()
    for h in [6,12,24,72,168]:x[f'ret{h}']=c.pct_change(h)
    return x

F={s:load(s) for s in SYMBOLS}
# Common hourly matrix.
all_ts=sorted(set().union(*[set(z.open_time.astype('int64').tolist()) for z in F.values() if not z.empty]))
IDX=pd.Index(all_ts,dtype='int64')
close=pd.DataFrame(index=IDX);openp=pd.DataFrame(index=IDX);above=pd.DataFrame(index=IDX)
rets={h:pd.DataFrame(index=IDX) for h in [6,12,24,72,168]}
for s,z in F.items():
    if z.empty:continue
    q=z.set_index('open_time')
    close[s]=q.close.reindex(IDX);openp[s]=q.open.reindex(IDX)
    above[s]=(q.close>q.ema200).astype(float).reindex(IDX)
    for h in rets:rets[h][s]=q[f'ret{h}'].reindex(IDX)
breadth=above.mean(axis=1,skipna=True)
btc=F['BTCUSDT'].set_index('open_time')
btc_close=btc.close.reindex(IDX);btc_ema=btc.ema200.reindex(IDX);btc_ret72=btc.ret72.reindex(IDX);btc_ret6=btc.ret6.reindex(IDX)

def bootstrap(period_df,n=2000):
    if period_df.empty:return 0.
    x=period_df.copy();dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    w=x.groupby('week').ret.sum().to_numpy(float)
    if len(w)<20:return 0.
    rng=np.random.default_rng(SEED)
    vals=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((vals>0).mean())

def metrics(p):
    if p.empty:return {'periods':0}
    r=p.ret.to_numpy(float);dt=pd.to_datetime(p.entry_time,unit='ms',utc=True)
    x=p.copy();x['y']=dt.dt.year;x['q']=dt.dt.to_period('Q').astype(str);x['m']=dt.dt.to_period('M').astype(str)
    y=(1+x.groupby('y').ret.apply(lambda s:(1+s).prod()-1))
    # undo added 1 above to keep dictionary readable
    yret=x.groupby('y').ret.apply(lambda s:(1+s).prod()-1)
    qret=x.groupby('q').ret.apply(lambda s:(1+s).prod()-1)
    mret=x.groupby('m').ret.apply(lambda s:(1+s).prod()-1)
    eq=np.cumprod(1+r);peak=np.maximum.accumulate(eq);dd=eq/peak-1
    gp=r[r>0].sum();gl=-r[r<0].sum();pf=float(gp/gl) if gl>0 else None
    return {'periods':int(len(x)),'avg_period':float(r.mean()),'pf':pf,'win_rate':float((r>0).mean()),
            'bootstrap':bootstrap(x),'positive_year_rate':float((yret>0).mean()),'positive_quarter_rate':float((qret>0).mean()),
            'positive_month_rate':float((mret>0).mean()),'monthly_mean':float(mret.mean()),'monthly_median':float(mret.median()),
            'best_month':float(mret.max()),'worst_month':float(mret.min()),'max_dd':float(-dd.min()),
            'total_return':float(eq[-1]-1),'yearly':{str(int(k)):float(v) for k,v in yret.items()}}

def run_mom(lb,hold,k,regime,minmom,cost):
    rows=[];step=hold
    # rebalance at UTC hour boundaries divisible by hold
    for pos in range(200,len(IDX)-hold-1):
        ts=int(IDX[pos]);dt=pd.to_datetime(ts,unit='ms',utc=True)
        if dt.hour%step!=0:continue
        if regime=='BTC_BULL' and not (np.isfinite(btc_ema.loc[ts]) and btc_close.loc[ts]>btc_ema.loc[ts] and btc_ret72.loc[ts]>0):continue
        if regime=='BREADTH_BULL' and not (breadth.loc[ts]>=.55):continue
        sig=rets[lb].loc[ts].dropna()
        sig=sig[sig>=minmom].sort_values(ascending=False)
        picks=sig.head(k).index.tolist()
        if not picks:continue
        entpos=pos+1;exitpos=min(entpos+hold,len(IDX)-1)
        et=int(IDX[entpos]);xt=int(IDX[exitpos])
        vals=[]
        for s in picks:
            en=openp.at[et,s];ex=openp.at[xt,s]
            if np.isfinite(en) and np.isfinite(ex) and en>0:vals.append(ex/en-1-cost)
        if vals:rows.append({'entry_time':et,'exit_time':xt,'ret':float(np.mean(vals)),'n':len(vals)})
    return pd.DataFrame(rows)

def run_rev(lb,hold,k,brceil,cost):
    rows=[]
    for pos in range(200,len(IDX)-hold-1):
        ts=int(IDX[pos]);dt=pd.to_datetime(ts,unit='ms',utc=True)
        if dt.hour%hold!=0:continue
        if not (breadth.loc[ts]<=brceil and btc_ret6.loc[ts]<=-.03 and btc_close.loc[ts]>btc_close.iloc[pos-1]):continue
        sig=rets[lb].loc[ts].dropna().sort_values(ascending=True)
        picks=sig.head(k).index.tolist()
        if not picks:continue
        entpos=pos+1;exitpos=min(entpos+hold,len(IDX)-1);et=int(IDX[entpos]);xt=int(IDX[exitpos])
        vals=[]
        for s in picks:
            en=openp.at[et,s];ex=openp.at[xt,s]
            if np.isfinite(en) and np.isfinite(ex) and en>0:vals.append(ex/en-1-cost)
        if vals:rows.append({'entry_time':et,'exit_time':xt,'ret':float(np.mean(vals)),'n':len(vals)})
    return pd.DataFrame(rows)

rows=[];cache={}
for lb in [24,72,168]:
 for hold in [12,24,48]:
  for k in [1,3,5]:
   for regime in ['ALL','BTC_BULL','BREADTH_BULL']:
    for mm in [0.,.02]:
     name=f'MOM_L{lb}_H{hold}_K{k}_{regime}_M{int(mm*100)}'
     b=run_mom(lb,hold,k,regime,mm,BASE_RT);s=run_mom(lb,hold,k,regime,mm,STRESS_RT)
     mb=metrics(b);ms=metrics(s)
     passed=bool(mb.get('periods',0)>=100 and mb.get('pf',0)>=1.10 and ms.get('pf',0)>=1.05 and mb.get('bootstrap',0)>=.95 and
                 mb.get('positive_year_rate',0)>=.80 and mb.get('positive_quarter_rate',0)>=.65 and ms.get('total_return',0)>0 and ms.get('max_dd',1)<=.35)
     rows.append({'name':name,'family':'MOM','lb':lb,'hold':hold,'k':k,'regime':regime,'minmom':mm,
                  **{f'base_{a}':v for a,v in mb.items()},**{f'stress_{a}':v for a,v in ms.items()},'passes_gate':passed})
     cache[name]=(b,s)
for lb in [12,24]:
 for hold in [6,12,24]:
  for k in [1,3,5]:
   for br in [.35,.45]:
    name=f'REV_L{lb}_H{hold}_K{k}_B{int(br*100)}'
    b=run_rev(lb,hold,k,br,BASE_RT);s=run_rev(lb,hold,k,br,STRESS_RT);mb=metrics(b);ms=metrics(s)
    passed=bool(mb.get('periods',0)>=80 and mb.get('pf',0)>=1.10 and ms.get('pf',0)>=1.05 and mb.get('bootstrap',0)>=.90 and
                mb.get('positive_year_rate',0)>=.80 and mb.get('positive_quarter_rate',0)>=.60 and ms.get('total_return',0)>0 and ms.get('max_dd',1)<=.35)
    rows.append({'name':name,'family':'REV','lb':lb,'hold':hold,'k':k,'regime':f'B{int(br*100)}','minmom':None,
                 **{f'base_{a}':v for a,v in mb.items()},**{f'stress_{a}':v for a,v in ms.items()},'passes_gate':passed})
    cache[name]=(b,s)

R=pd.DataFrame(rows);R['score']=R.passes_gate.astype(int)*1000+R.base_bootstrap.fillna(0)*100+R.stress_pf.fillna(0)*10+R.base_positive_year_rate.fillna(0)
R=R.sort_values(['passes_gate','score','stress_monthly_mean'],ascending=[False,False,False]);R.to_csv(OUT/'rotation_map.csv',index=False)
p=R[R.passes_gate];sel=p.iloc[0].to_dict() if len(p) else None
if sel:
    b,s=cache[sel['name']];b.to_csv(OUT/'selected_base.csv',index=False);s.to_csv(OUT/'selected_stress.csv',index=False)
summary={'version':'R16.19','period':'2021-01-01..2026-06-30','variants':int(len(R)),'strict_pass_count':int(R.passes_gate.sum()),
         'selected':sel,'top10':R.head(10).to_dict('records'),'notes':['No leverage.','Fully causal next-open rotation.','September 2026 remains untouched.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
