#!/usr/bin/env python3
"""R16.16 15m Intraday Shock/Reversion Map.

Independent high-turnover alpha research. Data 2021-01-01..2026-06-30.

LONG: extreme decline over 1h/2h/4h + volume shock + oversold RSI + recovery candle.
SHORT: extreme rise + volume shock + overbought RSI + rejection candle.

Grid:
- horizon bars: 4 / 8 / 16 (1h / 2h / 4h)
- move: 3% / 4% / 5% / 6%
- volume z: 1.5 / 2.0
- recovery/rejection body threshold: 0.60 / 0.75
- geometry: S1.25/T2.5/H16 or S1.5/T3/H24
- cluster: 1h / 3h, max 3 entries ranked by severity

No ML. No leverage.
"""
from __future__ import annotations
import json,math,heapq
from pathlib import Path
import numpy as np,pandas as pd

START=int(pd.Timestamp('2021-01-01T00:00:00Z').timestamp()*1000)
END=int(pd.Timestamp('2026-07-01T00:00:00Z').timestamp()*1000)
BASE_COST=.0016;STRESS_COST=.0021
BASE_FUND=.0001;STRESS_FUND=.0002
SEED=16160
START_CAP=10000.;RISK=.0025;MAX_POS=5;CAP=.25
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def load(sym):
    fs=[]
    for p in [Path('r16_edge_lab/pre2024_history_15m/15m')/f'{sym}.csv.gz',Path('r15_regime_lab/history/15m')/f'{sym}.csv.gz']:
        if p.exists():fs.append(pd.read_csv(p))
    if not fs:return pd.DataFrame()
    x=pd.concat(fs,ignore_index=True)
    for c in ['open_time','open','high','low','close','volume']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close']).drop_duplicates('open_time').sort_values('open_time')
    x=x[(x.open_time>=START)&(x.open_time<END)].reset_index(drop=True)
    h,l,c,v=x.high,x.low,x.close,x.volume;pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1);x['atr']=rma(tr,14)
    gain=rma(c.diff().clip(lower=0),14);loss=rma((-c.diff()).clip(lower=0),14)
    x['rsi14']=100-(100/(1+gain/loss.replace(0,np.nan)))
    x['volz96']=(v-v.rolling(96,min_periods=72).mean())/v.rolling(96,min_periods=72).std().replace(0,np.nan)
    x['body_pos']=(c-l)/(h-l).replace(0,np.nan)
    for hb in [4,8,16]:x[f'ret{hb}']=c.pct_change(hb)
    return x

def simulate(z,i,side,geom,cost,fund,sym):
    stop_a,targ_a,hold=geom
    if i>=len(z)-1:return None
    atr=float(z.atr.iloc[i])
    if not np.isfinite(atr) or atr<=0:return None
    ei=i+1;entry=float(z.open.iloc[ei])
    if side=='LONG':stop=entry-stop_a*atr;target=entry+targ_a*atr
    else:stop=entry+stop_a*atr;target=entry-targ_a*atr
    end=min(ei+hold-1,len(z)-1);px=float(z.close.iloc[end]);xi=end;reason='TIME'
    for j in range(ei,end+1):
        hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
        hs=lo<=stop if side=='LONG' else hi>=stop
        ht=hi>=target if side=='LONG' else lo<=target
        if hs and ht:px=stop;xi=j;reason='STOP_AMBIGUOUS';break
        if hs:px=stop;xi=j;reason='STOP';break
        if ht:px=target;xi=j;reason='TARGET';break
    gross=(px-entry)/entry if side=='LONG' else (entry-px)/entry
    bars=xi-ei+1
    fund_drag=(max(1,math.ceil((bars*.25)/8))*fund) if side=='SHORT' else 0.
    return {'symbol':sym,'side':side,'signal_time':int(z.open_time.iloc[i]),'entry_time':int(z.open_time.iloc[ei]),
            'exit_time':int(z.open_time.iloc[xi])+15*60_000,'stop_pct':stop_a*atr/entry,
            'net_pct':gross-2*cost-fund_drag,'gross_pct':gross,'funding_drag':fund_drag,'reason':reason}

def raw_for(F,side,hb,geom,cost,fund):
    rows=[]
    for sym,z in F.items():
        if z.empty:continue
        r=z[f'ret{hb}']
        if side=='LONG':broad=(r<=-.03)&(z.volz96>=1.5)&(z.rsi14<=35)&(z.body_pos>=.60)
        else:broad=(r>=.03)&(z.volz96>=1.5)&(z.rsi14>=65)&(z.body_pos<=.40)
        for i in np.flatnonzero(np.asarray(broad.fillna(False))):
            q=simulate(z,i,side,geom,cost,fund,sym)
            if q:
                q.update({'move_ret':float(r.iloc[i]),'volz':float(z.volz96.iloc[i]),'rsi':float(z.rsi14.iloc[i]),'body':float(z.body_pos.iloc[i])})
                rows.append(q)
    return pd.DataFrame(rows)

def select(df,side,move,volz,body,cluster_h):
    if df.empty:return df.copy()
    if side=='LONG':
        m=(df.move_ret<=-move)&(df.volz>=volz)&(df.rsi<=35)&(df.body>=body);score=-df.move_ret
    else:
        m=(df.move_ret>=move)&(df.volz>=volz)&(df.rsi>=65)&(df.body<=1-body);score=df.move_ret
    x=df[m].copy()
    if x.empty:return x
    x['cluster']=(x.signal_time//(cluster_h*3600_000))*(cluster_h*3600_000)
    x['score']=score.loc[x.index]
    x=x.sort_values(['cluster','score'],ascending=[True,False]).groupby('cluster',sort=False).head(3)
    x=x.sort_values(['symbol','entry_time'])
    keep=[];last={}
    for idx,r in x.iterrows():
        if int(r.entry_time)<=last.get(r.symbol,-1):continue
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
    rng=np.random.default_rng(SEED);v=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((v>0).mean())
def stats(d):
    if d.empty:return {'trades':0}
    x=d.copy();r=x.net_pct.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['year']=dt.dt.year;x['q']=dt.dt.to_period('Q').astype(str);x['m']=dt.dt.to_period('M').astype(str)
    y=x.groupby('year').net_pct.sum();yc=x.groupby('year').size();q=x.groupby('q').net_pct.sum();qc=x.groupby('q').size();m=x.groupby('m').net_pct.sum()
    sy=x.groupby('symbol').net_pct.sum();pos=sy.clip(lower=0);ay=[yr for yr,n in yc.items() if n>=20];aq=[qq for qq,n in qc.items() if n>=8]
    return {'trades':int(len(x)),'avg':float(r.mean()),'pf':pf(r),'win_rate':float((r>0).mean()),'weekly_prob_positive':boot(x),
            'active_year_positive_rate':float(np.mean([float(y.loc[a])>0 for a in ay])) if ay else 0.,
            'positive_active_quarter_rate':float(np.mean([float(q.loc[a])>0 for a in aq])) if aq else 0.,
            'positive_month_rate':float((m>0).mean()),'active_months':int(len(m)),'median_month_sum':float(m.median()),
            'max_positive_symbol_share':float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
            'yearly':{str(int(k)):float(v) for k,v in y.items()},'trades_by_year':{str(int(k)):int(v) for k,v in yc.items()}}
def portfolio(d):
    if d.empty:return {'return':0.,'dd':0.,'accepted':0,'rejected':0}
    eq=START_CAP;curve=[eq];heap=[];active=set();uid=acc=rej=0
    def settle(t):
        nonlocal eq
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;active.discard(sym);curve.append(eq)
    for r in d.sort_values(['entry_time','symbol']).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:rej+=1;continue
        notional=min(eq*CAP,eq*RISK/max(float(r.stop_pct),1e-6));pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));active.add(r.symbol);uid+=1;acc+=1
    settle(10**30);a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {'return':float(eq/START_CAP-1),'dd':float(-dd.min()),'accepted':acc,'rejected':rej}

def main():
    F={s:load(s) for s in SYMBOLS}
    geoms=[(1.25,2.5,16),(1.5,3.0,24)]
    raw={}
    for side in ['LONG','SHORT']:
      for hb in [4,8,16]:
       for gi,g in enumerate(geoms):
        print('RAW',side,hb,gi,flush=True)
        raw[(side,hb,gi,'base')]=raw_for(F,side,hb,g,BASE_COST,BASE_FUND)
        raw[(side,hb,gi,'stress')]=raw_for(F,side,hb,g,STRESS_COST,STRESS_FUND)
    rows=[];cache={}
    for side in ['LONG','SHORT']:
      for hb in [4,8,16]:
       for mv in [.03,.04,.05,.06]:
        for vz in [1.5,2.0]:
         for body in [.60,.75]:
          for gi,g in enumerate(geoms):
           for ch in [1,3]:
            name=f'{side}_H{hb}_M{int(mv*100)}_V{int(vz*10)}_B{int(body*100)}_G{gi}_C{ch}'
            b=select(raw[(side,hb,gi,'base')],side,mv,vz,body,ch);s=select(raw[(side,hb,gi,'stress')],side,mv,vz,body,ch)
            mb=stats(b);ms=stats(s);pb=portfolio(b);ps=portfolio(s)
            passed=bool(mb.get('trades',0)>=300 and mb.get('avg',0)>0 and ms.get('avg',0)>0 and
                        mb.get('pf',0)>=1.18 and ms.get('pf',0)>=1.12 and mb.get('weekly_prob_positive',0)>=.95 and
                        mb.get('active_year_positive_rate',0)>=.80 and mb.get('positive_active_quarter_rate',0)>=.65 and
                        mb.get('max_positive_symbol_share',1)<=.30 and ps.get('return',0)>0 and ps.get('dd',1)<=.15)
            rows.append({'name':name,'side':side,'horizon_bars':hb,'move':mv,'volz':vz,'body':body,'geom':str(g),'cluster_h':ch,
                         **{f'base_{k}':v for k,v in mb.items()},**{f'stress_{k}':v for k,v in ms.items()},
                         'base_portfolio_return':pb['return'],'base_portfolio_dd':pb['dd'],
                         'stress_portfolio_return':ps['return'],'stress_portfolio_dd':ps['dd'],'passes_gate':passed})
            cache[name]=(b,s)
    R=pd.DataFrame(rows);R['score']=R.passes_gate.astype(int)*1000+R.base_weekly_prob_positive.fillna(0)*100+R.stress_pf.fillna(0)*10+R.base_active_year_positive_rate.fillna(0)
    R=R.sort_values(['passes_gate','score','base_pf'],ascending=[False,False,False])
    out=Path('r16_edge_lab/r16_16_intraday_reversion');out.mkdir(parents=True,exist_ok=True);R.to_csv(out/'intraday_map.csv',index=False)
    selected={}
    for side in ['LONG','SHORT']:
        z=R[(R.side==side)&(R.passes_gate)]
        selected[side]=z.iloc[0].to_dict() if len(z) else None
        if selected[side]:
            b,s=cache[selected[side]['name']]
            b.to_csv(out/f'selected_{side.lower()}_base.csv.gz',index=False,compression='gzip')
            s.to_csv(out/f'selected_{side.lower()}_stress.csv.gz',index=False,compression='gzip')
    summary={'version':'R16.16','period':'2021-01-01..2026-06-30','variants':int(len(R)),'strict_pass_count':int(R.passes_gate.sum()),
             'selected':selected,'top10':R.head(10).to_dict('records'),'notes':['No leverage.','No ML.','15m data from official Binance archives.','September 2026 untouched.']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8');print(json.dumps(summary,indent=2,default=float),flush=True)
if __name__=='__main__':main()
