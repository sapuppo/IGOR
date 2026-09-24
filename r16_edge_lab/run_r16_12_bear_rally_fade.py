#!/usr/bin/env python3
"""R16.12 Bear Rally Fade / Failed Recovery Short Map

Goal:
Find a structurally different short alpha from raw downside breakout.

Families:
1) RALLY_FADE
   - higher-timeframe downtrend: EMA50 < EMA200
   - BTC bear regime
   - weak market breadth
   - coin rallies materially from a recent 4h low
   - rally touches EMA20 or EMA50 resistance
   - bearish rejection closes back below the touched EMA and below prior close

2) FAILED_RECOVERY
   - higher-timeframe downtrend
   - BTC bear regime
   - weak breadth
   - high pierces recent Donchian resistance
   - close fails back below that resistance and below open

Execution:
- 4h completed signal candle, short next 4h open
- same-bar stop+target -> stop first
- base/stress costs plus conservative short funding drag
- no leverage beyond 1x notional
- 2021-01-01 .. 2026-06-30
"""
from __future__ import annotations
import argparse, json, heapq, math
from pathlib import Path
import numpy as np
import pandas as pd

START_MS=int(pd.Timestamp("2021-01-01T00:00:00Z").timestamp()*1000)
END_MS=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)

BASE_COST=.0016
STRESS_COST=.0021
BASE_FUND_8H=.0001
STRESS_FUND_8H=.0002

START_CAP=10_000.0
RISK=.0025
MAX_POS=5
NOTIONAL_CAP=.25
SEED=16120

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):
    return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def load_pair(pre,post,sym):
    frames=[]
    for root in [pre,post]:
        p=root/'4h'/f'{sym}.csv.gz'
        if p.exists(): frames.append(pd.read_csv(p))
    if not frames: return pd.DataFrame()
    x=pd.concat(frames,ignore_index=True)
    for c in ['open_time','open','high','low','close','volume']:
        x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close']).drop_duplicates('open_time').sort_values('open_time')
    x=x[(x.open_time>=START_MS)&(x.open_time<END_MS)].reset_index(drop=True)
    h,l,c=x.high,x.low,x.close
    pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.0),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.0),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x['atr']=atr
    x['adx']=rma(dx,14)
    x['ema20']=c.ewm(span=20,adjust=False,min_periods=20).mean()
    x['ema50']=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x['ema200']=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x['ret42']=c.pct_change(42)
    x['ret6']=c.pct_change(6)
    x['ret12']=c.pct_change(12)
    x['low6']=l.shift(1).rolling(6,min_periods=6).min()
    x['low12']=l.shift(1).rolling(12,min_periods=12).min()
    for n in [20,40]:
        x[f'hi{n}']=h.shift(1).rolling(n,min_periods=n).max()
    return x

def context(F):
    parts=[]
    for sym,z in F.items():
        if z.empty: continue
        ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),
                      index=z.open_time.astype('int64'),name=sym)
        parts.append(ser[~ser.index.duplicated()])
    breadth=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
    btc=F['BTCUSDT'].set_index('open_time')
    ctx=pd.DataFrame(index=breadth.index)
    ctx['breadth']=breadth
    ctx['btc_strict']=((btc.close<btc.ema200)&(btc.ema50<btc.ema200)&(btc.ret42<0)).reindex(ctx.index).fillna(False)
    ctx['btc_soft']=((btc.close<btc.ema200)&(btc.ret42<0)).reindex(ctx.index).fillna(False)
    return ctx

def simulate_short(z,idxs,cost,fund8h,stop_atr,target_atr,hold,sym):
    rows=[];last_exit=-1
    for i in idxs:
        if i<=last_exit or i>=len(z)-1: continue
        atr=float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr<=0: continue
        ei=i+1
        entry=float(z.open.iloc[ei])
        stop=entry+stop_atr*atr
        target=entry-target_atr*atr
        end=min(ei+hold-1,len(z)-1)
        px=float(z.close.iloc[end]);xi=end;reason='TIME'
        for j in range(ei,end+1):
            hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
            hs=hi>=stop;ht=lo<=target
            if hs and ht:
                px=stop;xi=j;reason='STOP_AMBIGUOUS';break
            if hs:
                px=stop;xi=j;reason='STOP';break
            if ht:
                px=target;xi=j;reason='TARGET';break
        gross=(entry-px)/entry
        bars_held=xi-ei+1
        funding_units=max(1,math.ceil((bars_held*4)/8))
        funding_drag=funding_units*fund8h
        rows.append({
            'symbol':sym,'signal_time':int(z.open_time.iloc[i]),
            'entry_time':int(z.open_time.iloc[ei]),
            'exit_time':int(z.open_time.iloc[xi])+4*3600_000,
            'stop_pct':stop_atr*atr/entry,
            'net_pct':gross-2*cost-funding_drag,
            'gross_pct':gross,'funding_drag':funding_drag,
            'bars_held':bars_held,'reason':reason
        })
        last_exit=xi
    return rows

def build_variant(F,CTX,spec,cost,fund8h):
    rows=[]
    family=spec['family']
    for sym,z in F.items():
        if z.empty: continue
        down=(z.ema50<z.ema200)&(z.adx>=spec['adx'])
        if family=='RALLY_FADE':
            base_low=z['low6'] if spec['lookback']==6 else z['low12']
            rally=z.close/base_low-1
            touch=(z.high>=z[spec['touch']])
            reject=(z.close<z[spec['touch']])&(z.close<z.close.shift(1))&(z.close<z.open)
            signal=down&(rally>=spec['rally'])&touch&reject
        elif family=='FAILED_RECOVERY':
            res=z[f"hi{spec['don']}"]
            pierce=(z.high>res)
            fail=(z.close<res)&(z.close<z.open)&(z.close<z.close.shift(1))
            signal=down&pierce&fail
        else:
            raise ValueError(family)

        idxs=[]
        for i in np.flatnonzero(np.asarray(signal.fillna(False))):
            ts=int(z.open_time.iloc[i])
            if ts not in CTX.index: continue
            if float(CTX.loc[ts,'breadth'])>spec['breadth']: continue
            btc_ok=bool(CTX.loc[ts,'btc_strict']) if spec['btc']=='STRICT' else bool(CTX.loc[ts,'btc_soft'])
            if not btc_ok: continue
            idxs.append(i)
        rows.extend(simulate_short(z,idxs,cost,fund8h,spec['stop'],spec['target'],spec['hold'],sym))
    return pd.DataFrame(rows)

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def weekly_series(d):
    if d.empty:return pd.Series(dtype=float)
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    return x.groupby('week').net_pct.sum()

def bootstrap(d,n=2000):
    w=weekly_series(d).to_numpy(float)
    if len(w)<20:return 0.
    rng=np.random.default_rng(SEED)
    vals=np.empty(n)
    for i in range(n): vals[i]=rng.choice(w,len(w),replace=True).mean()
    return float((vals>0).mean())

def stats(d):
    if d.empty:return {'trades':0}
    r=d.net_pct.to_numpy(float)
    dt=pd.to_datetime(d.entry_time,unit='ms',utc=True)
    x=d.copy();x['year']=dt.dt.year;x['quarter']=dt.dt.to_period('Q').astype(str);x['month']=dt.dt.to_period('M').astype(str)
    y=x.groupby('year').net_pct.sum();yc=x.groupby('year').size()
    q=x.groupby('quarter').net_pct.sum();qc=x.groupby('quarter').size()
    m=x.groupby('month').net_pct.sum()
    sy=x.groupby('symbol').net_pct.sum();pos=sy.clip(lower=0)
    active_years=[yr for yr,n in yc.items() if n>=20]
    active_q=[qq for qq,n in qc.items() if n>=8]
    return {
      'trades':int(len(x)),'avg':float(r.mean()),'pf':pf(r),'win_rate':float((r>0).mean()),
      'weekly_prob_positive':bootstrap(x),
      'active_years':[int(v) for v in active_years],
      'all_active_years_positive':bool(all(float(y.loc[yr])>0 for yr in active_years)) if active_years else False,
      'positive_active_quarter_rate':float(np.mean([float(q.loc[qq])>0 for qq in active_q])) if active_q else 0.0,
      'positive_month_rate':float((m>0).mean()),
      'active_months':int(len(m)),
      'median_month_sum':float(m.median()),
      'max_positive_symbol_share':float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
      'yearly':{str(int(k)):float(v) for k,v in y.items()},
      'trades_by_year':{str(int(k)):int(v) for k,v in yc.items()},
      'year_2022':float(y.get(2022,0.0)),
      'trades_2022':int(yc.get(2022,0))
    }

def portfolio(d):
    if d.empty:return {'end':START_CAP,'return':0.,'max_dd':0.,'accepted':0,'rejected':0}
    eq=START_CAP;curve=[eq];heap=[];active=set();uid=acc=rej=0
    def settle(t):
        nonlocal eq
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym=heapq.heappop(heap);eq+=pnl;active.discard(sym);curve.append(eq)
    for r in d.sort_values(['entry_time','symbol']).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:
            rej+=1;continue
        notional=min(eq*NOTIONAL_CAP,eq*RISK/max(float(r.stop_pct),1e-6))
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));active.add(r.symbol);uid+=1;acc+=1
    settle(10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {'end':float(eq),'return':float(eq/START_CAP-1),'max_dd':float(-dd.min()),'accepted':acc,'rejected':rej}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pre',default='r16_edge_lab/pre2024_history')
    ap.add_argument('--post',default='r15_regime_lab/history')
    ap.add_argument('--output',default='r16_edge_lab/r16_12_bear_rally_fade')
    args=ap.parse_args()
    pre=Path(args.pre);post=Path(args.post);out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)

    print('Loading merged history...',flush=True)
    F={s:load_pair(pre,post,s) for s in SYMBOLS}
    CTX=context(F)

    specs=[]
    # RALLY_FADE: 2 lookbacks * 2 rally sizes * 2 touches * 2 ADX * 2 breadth * 2 BTC * 2 geoms = 128
    for lb in [6,12]:
      for rally in [.04,.07]:
       for touch in ['ema20','ema50']:
        for adx in [18,24]:
         for br in [.35,.45]:
          for btc in ['STRICT','SOFT']:
           for stop,target,hold in [(1.5,3.0,24),(2.0,4.0,30)]:
            specs.append({'family':'RALLY_FADE','lookback':lb,'rally':rally,'touch':touch,'adx':adx,'breadth':br,'btc':btc,'stop':stop,'target':target,'hold':hold,
                          'name':f'RF_L{lb}_R{int(rally*100)}_{touch.upper()}_A{adx}_B{int(br*100)}_{btc}_S{stop}_T{target}_H{hold}'})
    # FAILED_RECOVERY: 2 resistance windows * 2 ADX * 2 breadth * 2 BTC * 2 geoms = 32
    for don in [20,40]:
      for adx in [18,24]:
       for br in [.35,.45]:
        for btc in ['STRICT','SOFT']:
         for stop,target,hold in [(1.5,3.0,24),(2.0,4.0,30)]:
          specs.append({'family':'FAILED_RECOVERY','don':don,'adx':adx,'breadth':br,'btc':btc,'stop':stop,'target':target,'hold':hold,
                        'name':f'FR_D{don}_A{adx}_B{int(br*100)}_{btc}_S{stop}_T{target}_H{hold}'})

    rows=[];cache={}
    for k,spec in enumerate(specs,1):
        if k%10==0: print(f'{k}/{len(specs)}',flush=True)
        b=build_variant(F,CTX,spec,BASE_COST,BASE_FUND_8H)
        s=build_variant(F,CTX,spec,STRESS_COST,STRESS_FUND_8H)
        mb=stats(b);ms=stats(s)
        passed=bool(
          mb.get('trades',0)>=200 and
          mb.get('avg',0)>0 and ms.get('avg',0)>0 and
          mb.get('pf',0)>=1.15 and ms.get('pf',0)>=1.10 and
          mb.get('weekly_prob_positive',0)>=.95 and
          mb.get('all_active_years_positive',False) and
          mb.get('positive_active_quarter_rate',0)>=.70 and
          mb.get('max_positive_symbol_share',1)<=.30 and
          mb.get('year_2022',0)>0 and mb.get('trades_2022',0)>=20
        )
        pb=portfolio(b);ps=portfolio(s)
        rows.append({
          'name':spec['name'],'family':spec['family'],'spec':json.dumps(spec),
          **{f'base_{kk}':vv for kk,vv in mb.items()},
          **{f'stress_{kk}':vv for kk,vv in ms.items()},
          'base_portfolio_return':pb['return'],'base_portfolio_dd':pb['max_dd'],
          'stress_portfolio_return':ps['return'],'stress_portfolio_dd':ps['max_dd'],
          'passes_gate':passed
        })
        cache[spec['name']]=(b,s)

    R=pd.DataFrame(rows)
    R['score']=R.passes_gate.astype(int)*1000+R.base_weekly_prob_positive.fillna(0)*100+R.stress_pf.fillna(0)*10+R.base_positive_active_quarter_rate.fillna(0)
    R=R.sort_values(['passes_gate','score','base_pf'],ascending=[False,False,False])
    R.to_csv(out/'bear_rally_fade_map.csv',index=False)

    passing=R[R.passes_gate]
    selected=passing.iloc[0].to_dict() if len(passing) else None
    if selected:
        b,s=cache[selected['name']]
        b.to_csv(out/'selected_base_trades.csv.gz',index=False,compression='gzip')
        s.to_csv(out/'selected_stress_trades.csv.gz',index=False,compression='gzip')

    family_summary={}
    for fam in ['RALLY_FADE','FAILED_RECOVERY']:
        z=R[R.family.eq(fam)]
        family_summary[fam]={
          'variants':int(len(z)),
          'passes':int(z.passes_gate.sum()),
          'best':z.iloc[0].to_dict() if len(z) else None
        }

    summary={
      'version':'R16.12',
      'period':'2021-01-01..2026-06-30',
      'variants':int(len(R)),
      'strict_pass_count':int(R.passes_gate.sum()),
      'selected':selected,
      'families':family_summary,
      'top10':R.head(10).to_dict('records'),
      'cost_model':{
        'base_one_way':BASE_COST,'stress_one_way':STRESS_COST,
        'base_funding_drag_per_8h':BASE_FUND_8H,'stress_funding_drag_per_8h':STRESS_FUND_8H
      },
      'notes':[
        'No leverage.',
        'No ML.',
        'Raw downside breakout family from R16.11 is not reused.',
        'Gate explicitly requires positive 2022 plus consistency across other active years.'
      ]
    }
    (out/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8')
    print(json.dumps(summary,indent=2,default=float),flush=True)

if __name__=='__main__':
    main()
