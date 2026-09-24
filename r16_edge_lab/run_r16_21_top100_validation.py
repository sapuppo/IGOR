#!/usr/bin/env python3
"""R16.21 Frozen REV15M generalization on current-liquid top100 universe.

Frozen rule from R16.16:
- 15m
- 16-bar / 4h return <= -8%
- volume z96 >=2
- RSI14 <=35
- candle body position >=.60
- long next 15m open
- stop 1.5 ATR / target 3 ATR / hold 48 bars (12h)
- global 3h event cluster, max 3 entries ranked by severity
- same-bar ambiguous => stop
No tuning.
"""
from __future__ import annotations
import json,heapq
from pathlib import Path
import numpy as np,pandas as pd

ROOT=Path('r16_edge_lab/r16_21_top100_history');OUT=Path('r16_edge_lab/r16_21_top100_validation');OUT.mkdir(parents=True,exist_ok=True)
BASE=.0016;STRESS=.0021;SEED=16210;START_CAP=10000.;RISK=.0025;MAXPOS=8;PER=.15;GLOBAL=.8
uni=json.loads((ROOT/'universe.json').read_text());DEV39={u['symbol'] for u in uni if u['was_in_dev39']}
SYMS=[u['symbol'] for u in uni]

def rma(s,n):return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def load(s):
    p=ROOT/'15m'/f'{s}.csv.gz'
    if not p.exists():return pd.DataFrame()
    x=pd.read_csv(p)
    for c in ['open_time','open','high','low','close','volume']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna().drop_duplicates('open_time').sort_values('open_time').reset_index(drop=True)
    h,l,c,v=x.high,x.low,x.close,x.volume;pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1);x['atr']=rma(tr,14)
    x['ret16']=c.pct_change(16)
    gain=rma(c.diff().clip(lower=0),14);loss=rma((-c.diff()).clip(lower=0),14);x['rsi']=100-(100/(1+gain/loss.replace(0,np.nan)))
    x['volz']=(v-v.rolling(96,min_periods=72).mean())/v.rolling(96,min_periods=72).std().replace(0,np.nan)
    x['body']=(c-l)/(h-l).replace(0,np.nan)
    return x

def outcome(z,i,cost,sym):
    atr=float(z.atr.iloc[i])
    if not np.isfinite(atr) or atr<=0 or i>=len(z)-1:return None
    ei=i+1;en=float(z.open.iloc[ei]);st=en-1.5*atr;tg=en+3*atr
    end=min(ei+47,len(z)-1);px=float(z.close.iloc[end]);xi=end;reason='TIME'
    for j in range(ei,end+1):
        hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=lo<=st;ht=hi>=tg
        if hs and ht:px=st;xi=j;reason='STOP_AMBIGUOUS';break
        if hs:px=st;xi=j;reason='STOP';break
        if ht:px=tg;xi=j;reason='TARGET';break
    return {'symbol':sym,'unseen':sym not in DEV39,'signal_time':int(z.open_time.iloc[i]),'entry_time':int(z.open_time.iloc[ei]),
            'exit_time':int(z.open_time.iloc[xi])+15*60_000,'stop_pct':1.5*atr/en,'net_pct':(px-en)/en-2*cost,'ret16':float(z.ret16.iloc[i])}

def raw(cost):
    rows=[]
    for n,s in enumerate(SYMS,1):
        z=load(s)
        if z.empty:continue
        sig=(z.ret16<=-.08)&(z.volz>=2)&(z.rsi<=35)&(z.body>=.60)
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            q=outcome(z,i,cost,s)
            if q:rows.append(q)
        if n%10==0:print('symbols',n,flush=True)
    x=pd.DataFrame(rows)
    if x.empty:return x
    x['cluster']=(x.signal_time//(3*3600_000))*(3*3600_000);x['score']=-x.ret16
    x=x.sort_values(['cluster','score'],ascending=[True,False]).groupby('cluster',sort=False).head(3)
    x=x.sort_values(['symbol','entry_time']);keep=[];last={}
    for idx,r in x.iterrows():
        if int(r.entry_time)<=last.get(r.symbol,-1):continue
        keep.append(idx);last[r.symbol]=int(r.exit_time)
    return x.loc[keep].sort_values('entry_time').reset_index(drop=True)

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum();return float(gp/gl) if gl>0 else None
def boot(x,n=2500):
    if x.empty:return 0.
    z=x.copy();dt=pd.to_datetime(z.entry_time,unit='ms',utc=True);z['w']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D');w=z.groupby('w').net_pct.sum().to_numpy(float)
    if len(w)<15:return 0.
    rng=np.random.default_rng(SEED);v=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)]);return float((v>0).mean())
def met(x):
    if x.empty:return {'trades':0}
    a=x.net_pct.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True);z=x.copy();z['y']=dt.dt.year;z['q']=dt.dt.to_period('Q').astype(str);z['m']=dt.dt.to_period('M').astype(str)
    y=z.groupby('y').net_pct.sum();q=z.groupby('q').net_pct.sum();m=z.groupby('m').net_pct.sum();sy=z.groupby('symbol').net_pct.sum();pos=sy.clip(lower=0)
    return {'trades':int(len(z)),'avg':float(a.mean()),'pf':pf(a),'win_rate':float((a>0).mean()),'bootstrap':boot(z),
            'positive_year_rate':float((y>0).mean()),'positive_quarter_rate':float((q>0).mean()),'positive_month_rate':float((m>0).mean()),
            'median_month_sum':float(m.median()),'max_positive_symbol_share':float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
            'yearly':{str(int(k)):float(v) for k,v in y.items()}}
def port(x):
    if x.empty:return {'return':0.,'dd':0.,'accepted':0}
    eq=START_CAP;peak=eq;worst=0.;gross=0.;heap=[];active=set();uid=acc=0
    def settle(t):
        nonlocal eq,peak,worst,gross
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym,no,ra=heapq.heappop(heap);eq+=pnl;gross-=no;active.discard(sym);peak=max(peak,eq);worst=max(worst,1-(eq-sum(h[5] for h in heap))/peak)
    for r in x.sort_values(['entry_time','score'],ascending=[True,False]).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAXPOS or r.symbol in active:continue
        desired=min(eq*PER,eq*RISK/max(float(r.stop_pct),1e-6));cap=max(0.,eq*GLOBAL-gross);no=min(desired,cap)
        if no<eq*.005:continue
        ra=no*float(r.stop_pct);pnl=no*float(r.net_pct);heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol,no,ra));uid+=1;active.add(r.symbol);gross+=no;acc+=1
        worst=max(worst,1-(eq-sum(h[5] for h in heap))/peak)
    settle(10**30);return {'end':float(eq),'return':float(eq/START_CAP-1),'dd':float(worst),'accepted':acc}

B=raw(BASE);S=raw(STRESS)
for name,df in [('base',B),('stress',S)]:df.to_csv(OUT/f'{name}_trades.csv.gz',index=False,compression='gzip')
summary={'version':'R16.21','period':'2024-01-01..2026-06-30','top100_symbols':len(SYMS),'dev39_overlap':len(DEV39),'new_symbols':len(set(SYMS)-DEV39),
         'base_all':met(B),'stress_all':met(S),'base_unseen':met(B[B.unseen]) if len(B) else {},'stress_unseen':met(S[S.unseen]) if len(S) else {},
         'portfolio_base':port(B),'portfolio_stress':port(S),
         'notes':['Frozen R16.16 rule; no tuning.','Universe selected by current liquidity, so this is cross-universe development evidence, not temporal holdout.','September 2026 untouched.']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
