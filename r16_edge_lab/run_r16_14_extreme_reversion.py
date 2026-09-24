#!/usr/bin/env python3
"""R16.14 Extreme Reversion Pair Map

Independent 1h alpha research:
- FLUSH_LONG after extreme 6h decline + volume shock + reversal candle.
- PUMP_FADE_SHORT after extreme 6h rise + volume shock + rejection candle.

Predeclared grid per side:
- move threshold: 6%, 8%, 10%
- volume z: 1.5, 2.0
- reversal/rejection candle position: 0.60 or 0.75 equivalent
- geometry: S1.25/T2.5/H18 or S1.5/T3/H24
- cluster window: 3h or 6h, max 3 entries ranked by move severity

Shorts include conservative funding drag.
No ML, no leverage.
Data: 2021-01-01..2026-06-30.
"""
from __future__ import annotations
import argparse,json,math,heapq
from pathlib import Path
import numpy as np,pandas as pd

START=int(pd.Timestamp("2021-01-01T00:00:00Z").timestamp()*1000)
END=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016;STRESS_COST=.0021
BASE_FUND=.0001;STRESS_FUND=.0002
SEED=16140
START_CAP=10000.;RISK=.0025;MAX_POS=5;NOTIONAL_CAP=.25
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def load_pair(pre,post,sym):
    fs=[]
    for root in [pre,post]:
        p=root/'1h'/f'{sym}.csv.gz'
        if p.exists():fs.append(pd.read_csv(p))
    if not fs:return pd.DataFrame()
    x=pd.concat(fs,ignore_index=True)
    for c in ['open_time','open','high','low','close','volume']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close']).drop_duplicates('open_time').sort_values('open_time')
    x=x[(x.open_time>=START)&(x.open_time<END)].reset_index(drop=True)
    h,l,c,v=x.high,x.low,x.close,x.volume;pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1);atr=rma(tr,14)
    x['atr']=atr
    x['ret6']=c.pct_change(6)
    gain=rma(c.diff().clip(lower=0),14);loss=rma((-c.diff()).clip(lower=0),14)
    x['rsi14']=100-(100/(1+gain/loss.replace(0,np.nan)))
    x['volz48']=(v-v.rolling(48,min_periods=36).mean())/v.rolling(48,min_periods=36).std().replace(0,np.nan)
    x['body_pos']=(c-l)/(h-l).replace(0,np.nan)
    return x

def simulate(z,i,side,stop_atr,target_atr,hold,cost,fund8h,sym):
    if i>=len(z)-1:return None
    atr=float(z.atr.iloc[i])
    if not np.isfinite(atr) or atr<=0:return None
    ei=i+1;entry=float(z.open.iloc[ei])
    if side=='LONG':
        stop=entry-stop_atr*atr;target=entry+target_atr*atr
    else:
        stop=entry+stop_atr*atr;target=entry-target_atr*atr
    end=min(ei+hold-1,len(z)-1);px=float(z.close.iloc[end]);xi=end;reason='TIME'
    for j in range(ei,end+1):
        hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
        hs=(lo<=stop) if side=='LONG' else (hi>=stop)
        ht=(hi>=target) if side=='LONG' else (lo<=target)
        if hs and ht:px=stop;xi=j;reason='STOP_AMBIGUOUS';break
        if hs:px=stop;xi=j;reason='STOP';break
        if ht:px=target;xi=j;reason='TARGET';break
    gross=(px-entry)/entry if side=='LONG' else (entry-px)/entry
    bars=xi-ei+1
    fund=max(1,math.ceil(bars/8))*fund8h if side=='SHORT' else 0.
    return {'symbol':sym,'side':side,'signal_time':int(z.open_time.iloc[i]),'entry_time':int(z.open_time.iloc[ei]),
            'exit_time':int(z.open_time.iloc[xi])+3600_000,'stop_pct':stop_atr*atr/entry,
            'gross_pct':gross,'net_pct':gross-2*cost-fund,'funding_drag':fund,'reason':reason,
            'ret6':float(z.ret6.iloc[i]),'volz48':float(z.volz48.iloc[i]),
            'rsi14':float(z.rsi14.iloc[i]),'body_pos':float(z.body_pos.iloc[i])}

def raw_events(F,side,geom,cost,fund):
    stop,target,hold=geom;rows=[]
    for sym,z in F.items():
        if z.empty:continue
        if side=='LONG':
            broad=(z.ret6<=-.06)&(z.volz48>=1.5)&(z.rsi14<=35)&(z.body_pos>=.60)
        else:
            broad=(z.ret6>=.06)&(z.volz48>=1.5)&(z.rsi14>=65)&(z.body_pos<=.40)
        for i in np.flatnonzero(np.asarray(broad.fillna(False))):
            r=simulate(z,i,side,stop,target,hold,cost,fund,sym)
            if r:rows.append(r)
    return pd.DataFrame(rows)

def select(df,side,move,volz,body,cluster_h):
    if df.empty:return df.copy()
    if side=='LONG':
        m=(df.ret6<=-move)&(df.volz48>=volz)&(df.rsi14<=35)&(df.body_pos>=body)
        score=-df.ret6
    else:
        m=(df.ret6>=move)&(df.volz48>=volz)&(df.rsi14>=65)&(df.body_pos<=1-body)
        score=df.ret6
    x=df[m].copy()
    if x.empty:return x
    x['cluster']=(x.signal_time//(cluster_h*3600_000))*(cluster_h*3600_000)
    x['rank_score']=score.loc[x.index]
    x=x.sort_values(['cluster','rank_score'],ascending=[True,False]).groupby('cluster',sort=False).head(3)
    x=x.sort_values(['symbol','entry_time'])
    keep=[];last={}
    for idx,r in x.iterrows():
        le=last.get(r.symbol,-1)
        if int(r.entry_time)<=le:continue
        keep.append(idx);last[r.symbol]=int(r.exit_time)
    return x.loc[keep].sort_values('entry_time').reset_index(drop=True)

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None
def weekly(d):
    if d.empty:return pd.Series(dtype=float)
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    return x.groupby('week').net_pct.sum()
def boot(d,n=2000):
    w=weekly(d).to_numpy(float)
    if len(w)<20:return 0.
    rng=np.random.default_rng(SEED)
    vals=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((vals>0).mean())
def stats(d):
    if d.empty:return {'trades':0}
    x=d.copy();r=x.net_pct.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['year']=dt.dt.year;x['quarter']=dt.dt.to_period('Q').astype(str);x['month']=dt.dt.to_period('M').astype(str)
    y=x.groupby('year').net_pct.sum();yc=x.groupby('year').size();q=x.groupby('quarter').net_pct.sum();qc=x.groupby('quarter').size()
    m=x.groupby('month').net_pct.sum();sy=x.groupby('symbol').net_pct.sum();pos=sy.clip(lower=0)
    ay=[yr for yr,n in yc.items() if n>=15];aq=[qq for qq,n in qc.items() if n>=6]
    year_pos=float(np.mean([float(y.loc[yr])>0 for yr in ay])) if ay else 0.
    return {'trades':int(len(x)),'avg':float(r.mean()),'pf':pf(r),'win_rate':float((r>0).mean()),
            'weekly_prob_positive':boot(x),'active_year_positive_rate':year_pos,
            'positive_active_quarter_rate':float(np.mean([float(q.loc[qq])>0 for qq in aq])) if aq else 0.,
            'positive_month_rate':float((m>0).mean()),'active_months':int(len(m)),
            'median_month_sum':float(m.median()),'worst_month_sum':float(m.min()),'best_month_sum':float(m.max()),
            'max_positive_symbol_share':float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
            'yearly':{str(int(k)):float(v) for k,v in y.items()},'trades_by_year':{str(int(k)):int(v) for k,v in yc.items()}}
def portfolio(d):
    if d.empty:return {'end':START_CAP,'return':0.,'max_dd':0.,'accepted':0,'rejected':0}
    eq=START_CAP;curve=[eq];heap=[];active=set();uid=acc=rej=0
    def settle(t):
        nonlocal eq
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;active.discard(sym);curve.append(eq)
    for r in d.sort_values(['entry_time','symbol']).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:rej+=1;continue
        notional=min(eq*NOTIONAL_CAP,eq*RISK/max(float(r.stop_pct),1e-6))
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));active.add(r.symbol);uid+=1;acc+=1
    settle(10**30);a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {'end':float(eq),'return':float(eq/START_CAP-1),'max_dd':float(-dd.min()),'accepted':acc,'rejected':rej}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pre',default='r16_edge_lab/pre2024_history');ap.add_argument('--post',default='r15_regime_lab/history');ap.add_argument('--output',default='r16_edge_lab/r16_14_extreme_reversion')
    args=ap.parse_args();pre=Path(args.pre);post=Path(args.post);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    F={s:load_pair(pre,post,s) for s in SYMBOLS}
    geoms=[(1.25,2.5,18),(1.5,3.0,24)]
    raw={}
    for side in ['LONG','SHORT']:
      for gi,g in enumerate(geoms):
        print(f'RAW {side} G{gi}',flush=True)
        raw[(side,gi,'base')]=raw_events(F,side,g,BASE_COST,BASE_FUND)
        raw[(side,gi,'stress')]=raw_events(F,side,g,STRESS_COST,STRESS_FUND)

    rows=[];cache={}
    for side in ['LONG','SHORT']:
      for move in [.06,.08,.10]:
       for volz in [1.5,2.0]:
        for body in [.60,.75]:
         for gi,g in enumerate(geoms):
          for ch in [3,6]:
            name=f'{side}_M{int(move*100)}_V{int(volz*10)}_B{int(body*100)}_G{gi}_C{ch}'
            b=select(raw[(side,gi,'base')],side,move,volz,body,ch)
            s=select(raw[(side,gi,'stress')],side,move,volz,body,ch)
            mb=stats(b);ms=stats(s);pb=portfolio(b);ps=portfolio(s)
            passed=bool(mb.get('trades',0)>=120 and mb.get('avg',0)>0 and ms.get('avg',0)>0 and
                        mb.get('pf',0)>=1.18 and ms.get('pf',0)>=1.12 and mb.get('weekly_prob_positive',0)>=.90 and
                        mb.get('active_year_positive_rate',0)>=.80 and mb.get('positive_active_quarter_rate',0)>=.65 and
                        mb.get('max_positive_symbol_share',1)<=.30 and ps.get('return',0)>0 and ps.get('max_dd',1)<=.15)
            rows.append({'name':name,'side':side,'move':move,'volz':volz,'body':body,'geom':str(g),'cluster_h':ch,
                         **{f'base_{k}':v for k,v in mb.items()},**{f'stress_{k}':v for k,v in ms.items()},
                         'base_portfolio_return':pb['return'],'base_portfolio_dd':pb['max_dd'],
                         'stress_portfolio_return':ps['return'],'stress_portfolio_dd':ps['max_dd'],'passes_gate':passed})
            cache[name]=(b,s)
    R=pd.DataFrame(rows)
    R['score']=R.passes_gate.astype(int)*1000+R.base_weekly_prob_positive.fillna(0)*100+R.stress_pf.fillna(0)*10+R.base_active_year_positive_rate.fillna(0)
    R=R.sort_values(['passes_gate','score','base_pf'],ascending=[False,False,False])
    R.to_csv(out/'extreme_reversion_map.csv',index=False)

    selected={}
    for side in ['LONG','SHORT']:
        z=R[(R.side==side)&(R.passes_gate)]
        selected[side]=z.iloc[0].to_dict() if len(z) else None
        if selected[side]:
            b,s=cache[selected[side]['name']]
            b.to_csv(out/f'selected_{side.lower()}_base.csv.gz',index=False,compression='gzip')
            s.to_csv(out/f'selected_{side.lower()}_stress.csv.gz',index=False,compression='gzip')

    summary={'version':'R16.14','period':'2021-01-01..2026-06-30','variants':int(len(R)),
             'strict_pass_count':int(R.passes_gate.sum()),'selected':selected,
             'best_long':R[R.side.eq('LONG')].iloc[0].to_dict(),'best_short':R[R.side.eq('SHORT')].iloc[0].to_dict(),
             'top10':R.head(10).to_dict('records'),'july_august_used':False,
             'notes':['No leverage.','No ML.','Shorts include conservative funding drag.','September 2026 remains untouched.']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8')
    print(json.dumps(summary,indent=2,default=float),flush=True)
if __name__=='__main__':main()
