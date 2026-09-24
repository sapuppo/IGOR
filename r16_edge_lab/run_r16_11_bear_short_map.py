#!/usr/bin/env python3
"""R16.11 Bear/Short Alpha Map

Purpose:
Build a deterministic short engine that can complement the frozen LONG CORE in
bear regimes. No ML. No leverage beyond 1x notional exposure.

Data: 2021-01-01 through 2026-06-30.

Signal family:
- 4h Donchian downside breakout
- EMA50 < EMA200
- ADX filter
- BTC bearish context
- market breadth ceiling

Grid:
- Donchian: 40 / 55 / 70
- ADX: 20 / 25 / 30
- breadth ceiling: 25% / 35% / 45%
- BTC mode:
  STRICT = BTC close<EMA200, EMA50<EMA200, ret42<0
  SOFT   = BTC close<EMA200 and ret42<0
- geometry:
  S2.0/T4.0/H30
  S2.0/T6.0/H30

Execution:
- signal on completed 4h candle
- enter next 4h open
- short gross return = (entry - exit) / entry
- same-bar stop+target -> stop first
- costs: base/stress one-way costs + conservative funding drag
- base funding drag = 0.01% per 8h held
- stress funding drag = 0.02% per 8h held

Gate is evaluated on aggregate robustness, not max return.
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
SEED=16110

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):
    return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def load_pair(pre,post,sym):
    frames=[]
    for root in [pre,post]:
        p=root/'4h'/f'{sym}.csv.gz'
        if p.exists():
            frames.append(pd.read_csv(p))
    if not frames:
        return pd.DataFrame()
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
    x['ema50']=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x['ema200']=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x['ret42']=c.pct_change(42)
    for n in [40,55,70]:
        x[f'lo{n}']=l.shift(1).rolling(n,min_periods=n).min()
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

def simulate_variant(F,CTX,don,adx_thr,breadth_ceiling,btc_mode,stop_atr,target_atr,hold_bars,cost,fund8h):
    rows=[]
    for sym,z in F.items():
        if z.empty: continue
        lo=z[f'lo{don}']
        c=z.close
        prev=c.shift()
        signal=(c<lo)&(prev>=lo.shift())&(z.ema50<z.ema200)&(z.adx>=adx_thr)
        last_exit=-1
        for i in np.flatnonzero(np.asarray(signal.fillna(False))):
            if i<=last_exit or i>=len(z)-1:
                continue
            ts=int(z.open_time.iloc[i])
            if ts not in CTX.index:
                continue
            if float(CTX.loc[ts,'breadth'])>breadth_ceiling:
                continue
            btc_ok=bool(CTX.loc[ts,'btc_strict']) if btc_mode=='STRICT' else bool(CTX.loc[ts,'btc_soft'])
            if not btc_ok:
                continue
            atr=float(z.atr.iloc[i])
            if not np.isfinite(atr) or atr<=0:
                continue

            ei=i+1
            entry=float(z.open.iloc[ei])
            stop=entry+stop_atr*atr
            target=entry-target_atr*atr
            end=min(ei+hold_bars-1,len(z)-1)
            px=float(z.close.iloc[end]);xi=end;reason='TIME'
            for j in range(ei,end+1):
                hi=float(z.high.iloc[j]);lo_j=float(z.low.iloc[j])
                hs=hi>=stop
                ht=lo_j<=target
                if hs and ht:
                    px=stop;xi=j;reason='STOP_AMBIGUOUS';break
                if hs:
                    px=stop;xi=j;reason='STOP';break
                if ht:
                    px=target;xi=j;reason='TARGET';break

            gross=(entry-px)/entry
            bars_held=xi-ei+1
            hours_held=bars_held*4
            funding_units=max(1,math.ceil(hours_held/8))
            funding_drag=funding_units*fund8h
            net=gross-2*cost-funding_drag
            rows.append({
                'symbol':sym,'signal_time':ts,
                'entry_time':int(z.open_time.iloc[ei]),
                'exit_time':int(z.open_time.iloc[xi])+4*3600_000,
                'entry':entry,'exit':px,
                'stop_pct':stop_atr*atr/entry,
                'gross_pct':gross,'funding_drag':funding_drag,'net_pct':net,
                'bars_held':bars_held,'reason':reason,
                'breadth':float(CTX.loc[ts,'breadth'])
            })
            last_exit=xi
    return pd.DataFrame(rows)

def pf(a):
    a=np.asarray(a,float)
    gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def weekly_series(d):
    if d.empty:return pd.Series(dtype=float)
    x=d.copy()
    dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    return x.groupby('week').net_pct.sum()

def bootstrap(d,n=2000):
    w=weekly_series(d).to_numpy(float)
    if len(w)<20:return 0.0
    rng=np.random.default_rng(SEED)
    vals=np.empty(n)
    for i in range(n):
        vals[i]=rng.choice(w,len(w),replace=True).mean()
    return float((vals>0).mean())

def stats(d):
    if d.empty:return {'trades':0}
    r=d.net_pct.to_numpy(float)
    dt=pd.to_datetime(d.entry_time,unit='ms',utc=True)
    x=d.copy()
    x['year']=dt.dt.year
    x['quarter']=dt.dt.to_period('Q').astype(str)
    x['month']=dt.dt.to_period('M').astype(str)
    y=x.groupby('year').net_pct.sum()
    yc=x.groupby('year').size()
    q=x.groupby('quarter').net_pct.sum()
    qc=x.groupby('quarter').size()
    m=x.groupby('month').net_pct.sum()
    sy=x.groupby('symbol').net_pct.sum();pos=sy.clip(lower=0)

    active_years=[yr for yr,n in yc.items() if n>=20]
    active_q=[qq for qq,n in qc.items() if n>=8]
    all_active_years_positive=bool(all(float(y.loc[yr])>0 for yr in active_years)) if active_years else False
    pos_active_q=float(np.mean([float(q.loc[qq])>0 for qq in active_q])) if active_q else 0.0

    return {
        'trades':int(len(x)),
        'avg':float(r.mean()),
        'pf':pf(r),
        'win_rate':float((r>0).mean()),
        'weekly_prob_positive':bootstrap(x),
        'active_years':[int(v) for v in active_years],
        'all_active_years_positive':all_active_years_positive,
        'positive_active_quarter_rate':pos_active_q,
        'positive_month_rate':float((m>0).mean()),
        'active_months':int(len(m)),
        'median_month_sum':float(m.median()),
        'max_positive_symbol_share':float(pos.max()/pos.sum()) if pos.sum()>0 else 1.0,
        'yearly':{str(int(k)):float(v) for k,v in y.items()},
        'trades_by_year':{str(int(k)):int(v) for k,v in yc.items()},
        'year_2022':float(y.get(2022,0.0)),
        'trades_2022':int(yc.get(2022,0))
    }

def portfolio(d):
    if d.empty:
        return {'start':START_CAP,'end':START_CAP,'return':0.0,'max_dd':0.0,'accepted':0,'rejected':0}
    eq=START_CAP;curve=[eq];heap=[];active=set();uid=acc=rej=0
    def settle(until):
        nonlocal eq
        while heap and heap[0][0]<=until:
            ex,_,pnl,sym=heapq.heappop(heap)
            eq+=pnl;active.discard(sym);curve.append(eq)
    for r in d.sort_values(['entry_time','symbol']).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=MAX_POS or r.symbol in active:
            rej+=1;continue
        notional=min(eq*NOTIONAL_CAP,eq*RISK/max(float(r.stop_pct),1e-6))
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol))
        active.add(r.symbol);uid+=1;acc+=1
    settle(10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {'start':START_CAP,'end':float(eq),'return':float(eq/START_CAP-1),'max_dd':float(-dd.min()),'accepted':acc,'rejected':rej}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pre',default='r16_edge_lab/pre2024_history')
    ap.add_argument('--post',default='r15_regime_lab/history')
    ap.add_argument('--output',default='r16_edge_lab/r16_11_bear_short_map')
    args=ap.parse_args()
    pre=Path(args.pre);post=Path(args.post);out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)

    print('Loading merged 4h history...',flush=True)
    F={s:load_pair(pre,post,s) for s in SYMBOLS}
    CTX=context(F)

    variants=[]
    cache={}
    geoms=[(2.0,4.0,30),(2.0,6.0,30)]
    for don in [40,55,70]:
      for adx in [20,25,30]:
       for br in [.25,.35,.45]:
        for btc_mode in ['STRICT','SOFT']:
         for stop,target,hold in geoms:
            name=f'D{don}_A{adx}_B{int(br*100)}_{btc_mode}_S{stop}_T{target}_H{hold}'
            print(name,flush=True)
            b=simulate_variant(F,CTX,don,adx,br,btc_mode,stop,target,hold,BASE_COST,BASE_FUND_8H)
            s=simulate_variant(F,CTX,don,adx,br,btc_mode,stop,target,hold,STRESS_COST,STRESS_FUND_8H)
            mb=stats(b);ms=stats(s)
            passed=bool(
                mb.get('trades',0)>=250 and
                mb.get('avg',0)>0 and ms.get('avg',0)>0 and
                mb.get('pf',0)>=1.15 and ms.get('pf',0)>=1.10 and
                mb.get('weekly_prob_positive',0)>=.95 and
                mb.get('all_active_years_positive',False) and
                mb.get('positive_active_quarter_rate',0)>=.70 and
                mb.get('max_positive_symbol_share',1)<=.30 and
                mb.get('year_2022',0)>0 and mb.get('trades_2022',0)>=20
            )
            variants.append({
                'name':name,'don':don,'adx':adx,'breadth_ceiling':br,'btc_mode':btc_mode,
                'stop_atr':stop,'target_atr':target,'hold_bars':hold,
                **{f'base_{k}':v for k,v in mb.items()},
                **{f'stress_{k}':v for k,v in ms.items()},
                'passes_gate':passed,
                'base_portfolio_return':portfolio(b)['return'],
                'base_portfolio_dd':portfolio(b)['max_dd'],
                'stress_portfolio_return':portfolio(s)['return'],
                'stress_portfolio_dd':portfolio(s)['max_dd']
            })
            cache[name]=(b,s)

    R=pd.DataFrame(variants)
    R['score']=(
        R.passes_gate.astype(int)*1000 +
        R.base_weekly_prob_positive.fillna(0)*100 +
        R.stress_pf.fillna(0)*10 +
        R.base_positive_active_quarter_rate.fillna(0)
    )
    R=R.sort_values(['passes_gate','score','base_pf'],ascending=[False,False,False])
    R.to_csv(out/'short_map.csv',index=False)

    passing=R[R.passes_gate]
    selected=passing.iloc[0].to_dict() if len(passing) else None
    if selected:
        b,s=cache[selected['name']]
        b.to_csv(out/'selected_base_trades.csv.gz',index=False,compression='gzip')
        s.to_csv(out/'selected_stress_trades.csv.gz',index=False,compression='gzip')

    summary={
        'version':'R16.11',
        'purpose':'deterministic bear/short alpha map',
        'period':'2021-01-01..2026-06-30',
        'variants':int(len(R)),
        'strict_pass_count':int(R.passes_gate.sum()),
        'selected':selected,
        'top10':R.head(10).to_dict('records'),
        'cost_model':{
            'base_one_way':BASE_COST,'stress_one_way':STRESS_COST,
            'base_funding_drag_per_8h':BASE_FUND_8H,
            'stress_funding_drag_per_8h':STRESS_FUND_8H
        },
        'notes':[
            'Short return is modeled at 1x notional; no leverage.',
            'Funding is conservatively treated as a cost even though actual perpetual funding can be positive or negative.',
            'Same-bar stop+target is resolved stop-first.',
            'The gate explicitly requires positive 2022 performance.'
        ]
    }
    (out/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8')
    print(json.dumps(summary,indent=2,default=float),flush=True)

if __name__=='__main__':
    main()
