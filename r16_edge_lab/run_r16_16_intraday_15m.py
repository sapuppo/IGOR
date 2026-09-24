#!/usr/bin/env python3
"""R16.16 15m Intraday Extreme Reversion Map.

Independent high-frequency alpha search using the structure proven in R16.14.

Sides: LONG flush reversal, SHORT pump fade.
Lookback returns: 8 bars (2h), 16 bars (4h).
Move thresholds: 4%, 6%, 8%.
Volume z: 1.5, 2.0.
Candle reversal strength: 0.60 / 0.75.
Geometries:
 G0 stop1.25 ATR target2.5 ATR hold32 bars (8h)
 G1 stop1.5 ATR target3 ATR hold48 bars (12h)
Cluster windows: 1h / 3h, max3 entries ranked by severity.

No leverage. Shorts include conservative funding.
Data 2021-01-01..2026-06-30.
"""
from __future__ import annotations
import json,math,heapq
from pathlib import Path
import numpy as np,pandas as pd

PRE=Path('r16_edge_lab/pre2024_15m');POST=Path('r15_regime_lab/history');OUT=Path('r16_edge_lab/r16_16_intraday_15m');OUT.mkdir(parents=True,exist_ok=True)
START=int(pd.Timestamp('2021-01-01T00:00:00Z').timestamp()*1000);END=int(pd.Timestamp('2026-07-01T00:00:00Z').timestamp()*1000)
BASE=.0016;STRESS=.0021;BASE_FUND=.0001;STRESS_FUND=.0002
SEED=16160;START_CAP=10000.;RISK=.0025;MAX_POS=8;PER_POS=.15;GLOBAL=.8
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def load(sym):
    fs=[]
    for root in [PRE,POST]:
        p=root/'15m'/f'{sym}.csv.gz'
        if p.exists():fs.append(pd.read_csv(p))
    if not fs:return pd.DataFrame()
    x=pd.concat(fs,ignore_index=True)
    for c in ['open_time','open','high','low','close','volume']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close']).drop_duplicates('open_time').sort_values('open_time')
    x=x[(x.open_time>=START)&(x.open_time<END)].reset_index(drop=True)
    h,l,c,v=x.high,x.low,x.close,x.volume;pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1);x['atr']=rma(tr,14)
    x['ret8']=c.pct_change(8);x['ret16']=c.pct_change(16)
    gain=rma(c.diff().clip(lower=0),14);loss=rma((-c.diff()).clip(lower=0),14)
    x['rsi14']=100-(100/(1+gain/loss.replace(0,np.nan)))
    x['volz96']=(v-v.rolling(96,min_periods=72).mean())/v.rolling(96,min_periods=72).std().replace(0,np.nan)
    x['body_pos']=(c-l)/(h-l).replace(0,np.nan)
    return x

def outcome(z,i,side,geom,cost,fund,sym):
    st,tg,hold=geom
    if i>=len(z)-1:return None
    atr=float(z.atr.iloc[i])
    if not np.isfinite(atr) or atr<=0:return None
    ei=i+1;entry=float(z.open.iloc[ei])
    stop=entry-st*atr if side=='LONG' else entry+st*atr
    target=entry+tg*atr if side=='LONG' else entry-tg*atr
    end=min(ei+hold-1,len(z)-1);px=float(z.close.iloc[end]);xi=end
    for j in range(ei,end+1):
        hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
        hs=(lo<=stop) if side=='LONG' else (hi>=stop)
        ht=(hi>=target) if side=='LONG' else (lo<=target)
        if hs and ht:px=stop;xi=j;break
        if hs:px=stop;xi=j;break
        if ht:px=target;xi=j;break
    gross=(px-entry)/entry if side=='LONG' else (entry-px)/entry
    bars=xi-ei+1;f=max(1,math.ceil((bars*.25)/8))*fund if side=='SHORT' else 0.
    return {'symbol':sym,'side':side,'signal_time':int(z.open_time.iloc[i]),'entry_time':int(z.open_time.iloc[ei]),'exit_time':int(z.open_time.iloc[xi])+15*60_000,
            'stop_pct':st*atr/entry,'net_pct':gross-2*cost-f,'ret8':float(z.ret8.iloc[i]),'ret16':float(z.ret16.iloc[i]),
            'volz96':float(z.volz96.iloc[i]),'rsi14':float(z.rsi14.iloc[i]),'body_pos':float(z.body_pos.iloc[i])}

GEOMS=[(1.25,2.5,32),(1.5,3.0,48)]
raw={(side,gi,cname):[] for side in ['LONG','SHORT'] for gi in range(2) for cname in ['base','stress']}
for n,sym in enumerate(SYMBOLS,1):
    z=load(sym)
    if z.empty:continue
    broad_long=(((z.ret8<=-.04)|(z.ret16<=-.04))&(z.volz96>=1.5)&(z.rsi14<=35)&(z.body_pos>=.60))
    broad_short=(((z.ret8>=.04)|(z.ret16>=.04))&(z.volz96>=1.5)&(z.rsi14>=65)&(z.body_pos<=.40))
    for side,broad in [('LONG',broad_long),('SHORT',broad_short)]:
        idxs=np.flatnonzero(np.asarray(broad.fillna(False)))
        for gi,g in enumerate(GEOMS):
            for i in idxs:
                rb=outcome(z,i,side,g,BASE,BASE_FUND,sym);rs=outcome(z,i,side,g,STRESS,STRESS_FUND,sym)
                if rb:raw[(side,gi,'base')].append(rb)
                if rs:raw[(side,gi,'stress')].append(rs)
    print(n,sym,flush=True)
for k in list(raw):raw[k]=pd.DataFrame(raw[k])

def select(df,side,lb,move,volz,body,ch):
    if df.empty:return df.copy()
    rcol='ret8' if lb==8 else 'ret16'
    if side=='LONG':
        m=(df[rcol]<=-move)&(df.volz96>=volz)&(df.rsi14<=35)&(df.body_pos>=body);score=-df[rcol]
    else:
        m=(df[rcol]>=move)&(df.volz96>=volz)&(df.rsi14>=65)&(df.body_pos<=1-body);score=df[rcol]
    x=df[m].copy()
    if x.empty:return x
    x['cluster']=(x.signal_time//(ch*3600_000))*(ch*3600_000);x['rank_score']=score.loc[x.index]
    x=x.sort_values(['cluster','rank_score'],ascending=[True,False]).groupby('cluster',sort=False).head(3)
    x=x.sort_values(['symbol','entry_time'])
    keep=[];last={}
    for idx,r in x.iterrows():
        if int(r.entry_time)<=last.get(r.symbol,-1):continue
        keep.append(idx);last[r.symbol]=int(r.exit_time)
    return x.loc[keep].sort_values('entry_time').reset_index(drop=True)
def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum();return float(gp/gl) if gl>0 else None
def weekly(d):
    if d.empty:return pd.Series(dtype=float)
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit='ms',utc=True);x['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D');return x.groupby('week').net_pct.sum()
def boot(d,n=1500):
    w=weekly(d).to_numpy(float)
    if len(w)<20:return 0.
    rng=np.random.default_rng(SEED);vals=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((vals>0).mean())
def stats(d):
    if d.empty:return {'trades':0}
    x=d.copy();r=x.net_pct.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['y']=dt.dt.year;x['q']=dt.dt.to_period('Q').astype(str);x['m']=dt.dt.to_period('M').astype(str)
    y=x.groupby('y').net_pct.sum();yc=x.groupby('y').size();q=x.groupby('q').net_pct.sum();qc=x.groupby('q').size();m=x.groupby('m').net_pct.sum()
    sy=x.groupby('symbol').net_pct.sum();pos=sy.clip(lower=0);ay=[yr for yr,n in yc.items() if n>=30];aq=[qq for qq,n in qc.items() if n>=10]
    return {'trades':int(len(x)),'avg':float(r.mean()),'pf':pf(r),'win_rate':float((r>0).mean()),'weekly_prob_positive':boot(x),
            'active_year_positive_rate':float(np.mean([float(y.loc[yr])>0 for yr in ay])) if ay else 0.,
            'positive_active_quarter_rate':float(np.mean([float(q.loc[qq])>0 for qq in aq])) if aq else 0.,
            'positive_month_rate':float((m>0).mean()),'active_months':int(len(m)),'median_month_sum':float(m.median()),
            'max_positive_symbol_share':float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
            'yearly':{str(int(k)):float(v) for k,v in y.items()}}
def portfolio(d):
    if d.empty:return {'return':0.,'dd':0.}
    eq=START_CAP;peak=eq;worst=0.;heap=[];active=set();gross=0.;uid=0
    def settle(t):
        nonlocal eq,peak,worst,gross
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym,notional,riskamt=heapq.heappop(heap);eq+=pnl;gross-=notional;active.discard(sym);peak=max(peak,eq);worst=max(worst,1-(eq-sum(h[5] for h in heap))/peak)
    for r in d.sort_values(['entry_time','symbol']).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:continue
        desired=min(eq*PER_POS,eq*RISK/max(float(r.stop_pct),1e-6));cap=max(0,eq*GLOBAL-gross);notional=min(desired,cap)
        if notional<eq*.005:continue
        riskamt=notional*float(r.stop_pct);pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol,notional,riskamt));uid+=1;active.add(r.symbol);gross+=notional
        worst=max(worst,1-(eq-sum(h[5] for h in heap))/peak)
    settle(10**30);return {'return':float(eq/START_CAP-1),'dd':float(worst)}

rows=[];cache={}
for side in ['LONG','SHORT']:
 for lb in [8,16]:
  for move in [.04,.06,.08]:
   for vz in [1.5,2.0]:
    for body in [.60,.75]:
     for gi in [0,1]:
      for ch in [1,3]:
       name=f'{side}_L{lb}_M{int(move*100)}_V{int(vz*10)}_B{int(body*100)}_G{gi}_C{ch}'
       b=select(raw[(side,gi,'base')],side,lb,move,vz,body,ch);s=select(raw[(side,gi,'stress')],side,lb,move,vz,body,ch)
       mb=stats(b);ms=stats(s);pb=portfolio(b);ps=portfolio(s)
       passed=bool(mb.get('trades',0)>=400 and mb.get('avg',0)>0 and ms.get('avg',0)>0 and mb.get('pf',0)>=1.12 and ms.get('pf',0)>=1.07 and
                   mb.get('weekly_prob_positive',0)>=.95 and mb.get('active_year_positive_rate',0)>=.80 and mb.get('positive_active_quarter_rate',0)>=.65 and
                   mb.get('max_positive_symbol_share',1)<=.25 and ps['return']>0 and ps['dd']<=.18)
       rows.append({'name':name,'side':side,'lookback':lb,'move':move,'volz':vz,'body':body,'geom':gi,'cluster_h':ch,
                    **{f'base_{k}':v for k,v in mb.items()},**{f'stress_{k}':v for k,v in ms.items()},
                    'base_portfolio_return':pb['return'],'base_dd':pb['dd'],'stress_portfolio_return':ps['return'],'stress_dd':ps['dd'],'passes_gate':passed})
       cache[name]=(b,s)
R=pd.DataFrame(rows);R['score']=R.passes_gate.astype(int)*1000+R.base_weekly_prob_positive.fillna(0)*100+R.stress_pf.fillna(0)*10+R.base_active_year_positive_rate.fillna(0)
R=R.sort_values(['passes_gate','score','base_pf'],ascending=[False,False,False]);R.to_csv(OUT/'intraday_map.csv',index=False)
sel={}
for side in ['LONG','SHORT']:
    z=R[(R.side==side)&R.passes_gate];sel[side]=z.iloc[0].to_dict() if len(z) else None
    if sel[side]:
        b,s=cache[sel[side]['name']];b.to_csv(OUT/f'selected_{side.lower()}_base.csv.gz',index=False,compression='gzip');s.to_csv(OUT/f'selected_{side.lower()}_stress.csv.gz',index=False,compression='gzip')
summary={'version':'R16.16','period':'2021-01-01..2026-06-30','variants':int(len(R)),'strict_pass_count':int(R.passes_gate.sum()),'selected':sel,
         'best_long':R[R.side.eq('LONG')].iloc[0].to_dict(),'best_short':R[R.side.eq('SHORT')].iloc[0].to_dict(),'top10':R.head(10).to_dict('records'),
         'notes':['No leverage.','No ML.','September 2026 remains untouched.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
