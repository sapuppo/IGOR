#!/usr/bin/env python3
"""R16.13 Regime-Specific Failed Recovery

Frozen short signal from R16.12:
- 4h downtrend EMA50 < EMA200
- ADX >= 24
- BTC STRICT bear context
- breadth <= 45%
- high pierces prior 40-bar high
- close fails below that resistance, below open and below prior close
- short next 4h open
- stop 2 ATR / target 4 ATR / max hold 30 bars
- base/stress fees + conservative funding drag

Only the REGIME GATE is explored:
- BTC EMA50/EMA200 spread thresholds
- BTC 42-bar return thresholds
- breadth ceilings
- breadth 6-bar slope thresholds
- coin distance below EMA200

No ML. No leverage. Data ends 2026-06-30.
"""
from __future__ import annotations
import argparse, json, math, heapq
from pathlib import Path
import numpy as np, pandas as pd

START_MS=int(pd.Timestamp("2021-01-01T00:00:00Z").timestamp()*1000)
END_MS=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016;STRESS_COST=.0021
BASE_FUND=.0001;STRESS_FUND=.0002
SEED=16130
START_CAP=10000.;RISK=.0025;MAX_POS=5;NOTIONAL_CAP=.25

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def load_pair(pre,post,sym):
    fs=[]
    for root in [pre,post]:
        p=root/'4h'/f'{sym}.csv.gz'
        if p.exists(): fs.append(pd.read_csv(p))
    if not fs:return pd.DataFrame()
    x=pd.concat(fs,ignore_index=True)
    for c in ['open_time','open','high','low','close','volume']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close']).drop_duplicates('open_time').sort_values('open_time')
    x=x[(x.open_time>=START_MS)&(x.open_time<END_MS)].reset_index(drop=True)
    h,l,c=x.high,x.low,x.close;pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1);atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x['atr']=atr;x['adx']=rma(dx,14)
    x['ema50']=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x['ema200']=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x['ret42']=c.pct_change(42)
    x['hi40']=h.shift(1).rolling(40,min_periods=40).max()
    x['ema_dist']=c/x.ema200-1
    return x

def context(F):
    parts=[]
    for sym,z in F.items():
        if z.empty:continue
        ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),index=z.open_time.astype('int64'),name=sym)
        parts.append(ser[~ser.index.duplicated()])
    b=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
    btc=F['BTCUSDT'].set_index('open_time')
    ctx=pd.DataFrame(index=b.index)
    ctx['breadth']=b
    ctx['breadth_slope6']=b-b.shift(6)
    ctx['btc_ret42']=btc.ret42.reindex(ctx.index)
    ctx['btc_ema_gap']=((btc.ema50/btc.ema200)-1).reindex(ctx.index)
    ctx['btc_strict']=((btc.close<btc.ema200)&(btc.ema50<btc.ema200)&(btc.ret42<0)).reindex(ctx.index).fillna(False)
    return ctx

def raw_events(F,CTX,cost,fund8h):
    rows=[]
    for sym,z in F.items():
        if z.empty:continue
        res=z.hi40
        sig=(z.ema50<z.ema200)&(z.adx>=24)&(z.high>res)&(z.close<res)&(z.close<z.open)&(z.close<z.close.shift(1))
        last=-1
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            if i<=last or i>=len(z)-1:continue
            ts=int(z.open_time.iloc[i])
            if ts not in CTX.index or not bool(CTX.loc[ts,'btc_strict']) or float(CTX.loc[ts,'breadth'])>.45:continue
            atr=float(z.atr.iloc[i])
            if not np.isfinite(atr) or atr<=0:continue
            ei=i+1;entry=float(z.open.iloc[ei]);stop=entry+2*atr;target=entry-4*atr
            end=min(ei+29,len(z)-1);px=float(z.close.iloc[end]);xi=end;reason='TIME'
            for j in range(ei,end+1):
                hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=hi>=stop;ht=lo<=target
                if hs and ht:px=stop;xi=j;reason='STOP_AMBIGUOUS';break
                if hs:px=stop;xi=j;reason='STOP';break
                if ht:px=target;xi=j;reason='TARGET';break
            gross=(entry-px)/entry
            bars=xi-ei+1;fund=max(1,math.ceil((bars*4)/8))*fund8h
            rows.append({
              'symbol':sym,'signal_time':ts,'entry_time':int(z.open_time.iloc[ei]),
              'exit_time':int(z.open_time.iloc[xi])+4*3600_000,
              'stop_pct':2*atr/entry,'net_pct':gross-2*cost-fund,'reason':reason,
              'breadth':float(CTX.loc[ts,'breadth']),
              'breadth_slope6':float(CTX.loc[ts,'breadth_slope6']) if np.isfinite(CTX.loc[ts,'breadth_slope6']) else np.nan,
              'btc_ret42':float(CTX.loc[ts,'btc_ret42']) if np.isfinite(CTX.loc[ts,'btc_ret42']) else np.nan,
              'btc_ema_gap':float(CTX.loc[ts,'btc_ema_gap']) if np.isfinite(CTX.loc[ts,'btc_ema_gap']) else np.nan,
              'coin_ema_dist':float(z.ema_dist.iloc[i]) if np.isfinite(z.ema_dist.iloc[i]) else np.nan
            })
            last=xi
    return pd.DataFrame(rows)

def apply_gate(df,btc_gap,btc_ret,breadth,slope,coin_dist):
    m=(df.btc_ema_gap<=btc_gap)&(df.btc_ret42<=btc_ret)&(df.breadth<=breadth)&(df.coin_ema_dist<=coin_dist)
    if slope is not None:m&=df.breadth_slope6<=slope
    return df[m].copy()

def pf(a):
    a=np.asarray(a,float);gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None
def weekly(d):
    if d.empty:return pd.Series(dtype=float)
    x=d.copy();dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    return x.groupby('week').net_pct.sum()
def boot(d,n=2500):
    w=weekly(d).to_numpy(float)
    if len(w)<15:return 0.
    rng=np.random.default_rng(SEED)
    vals=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
    return float((vals>0).mean())
def stats(d):
    if d.empty:return {'trades':0}
    x=d.copy();r=x.net_pct.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['year']=dt.dt.year;x['quarter']=dt.dt.to_period('Q').astype(str);x['month']=dt.dt.to_period('M').astype(str)
    y=x.groupby('year').net_pct.sum();yc=x.groupby('year').size()
    q=x.groupby('quarter').net_pct.sum();qc=x.groupby('quarter').size()
    m=x.groupby('month').net_pct.sum();sy=x.groupby('symbol').net_pct.sum();pos=sy.clip(lower=0)
    ay=[yr for yr,n in yc.items() if n>=10];aq=[qq for qq,n in qc.items() if n>=5]
    return {
      'trades':int(len(x)),'avg':float(r.mean()),'pf':pf(r),'win_rate':float((r>0).mean()),
      'weekly_prob_positive':boot(x),
      'all_active_years_positive':bool(all(float(y.loc[yr])>0 for yr in ay)) if ay else False,
      'positive_active_quarter_rate':float(np.mean([float(q.loc[qq])>0 for qq in aq])) if aq else 0.,
      'positive_month_rate':float((m>0).mean()),'active_months':int(len(m)),
      'median_month_sum':float(m.median()),'worst_month_sum':float(m.min()),'best_month_sum':float(m.max()),
      'max_positive_symbol_share':float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
      'yearly':{str(int(k)):float(v) for k,v in y.items()},
      'trades_by_year':{str(int(k)):int(v) for k,v in yc.items()}
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
        if len(heap)>=MAX_POS or r.symbol in active:rej+=1;continue
        notional=min(eq*NOTIONAL_CAP,eq*RISK/max(float(r.stop_pct),1e-6))
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));active.add(r.symbol);uid+=1;acc+=1
    settle(10**30);a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {'end':float(eq),'return':float(eq/START_CAP-1),'max_dd':float(-dd.min()),'accepted':acc,'rejected':rej}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pre',default='r16_edge_lab/pre2024_history')
    ap.add_argument('--post',default='r15_regime_lab/history')
    ap.add_argument('--output',default='r16_edge_lab/r16_13_failed_recovery_regime')
    args=ap.parse_args();pre=Path(args.pre);post=Path(args.post);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    F={s:load_pair(pre,post,s) for s in SYMBOLS};CTX=context(F)
    print('Building frozen FAILED_RECOVERY events...',flush=True)
    B=raw_events(F,CTX,BASE_COST,BASE_FUND);S=raw_events(F,CTX,STRESS_COST,STRESS_FUND)
    B.to_csv(out/'raw_base_events.csv.gz',index=False,compression='gzip')

    rows=[];cache={}
    # 3*3*3*3*3=243 predeclared regime gates
    for gap in [0.,-.02,-.04]:
      for ret in [0.,-.05,-.10]:
       for br in [.25,.35,.45]:
        for sl in [None,0.,-.05]:
         for cd in [0.,-.05,-.10]:
            name=f'G{int(abs(gap)*100)}_R{int(abs(ret)*100)}_B{int(br*100)}_S{"N" if sl is None else int(abs(sl)*100)}_C{int(abs(cd)*100)}'
            b=apply_gate(B,gap,ret,br,sl,cd);s=apply_gate(S,gap,ret,br,sl,cd)
            mb=stats(b);ms=stats(s);pb=portfolio(b);ps=portfolio(s)
            passed=bool(
              mb.get('trades',0)>=80 and mb.get('avg',0)>0 and ms.get('avg',0)>0 and
              mb.get('pf',0)>=1.25 and ms.get('pf',0)>=1.18 and
              mb.get('weekly_prob_positive',0)>=.90 and
              mb.get('all_active_years_positive',False) and
              mb.get('positive_active_quarter_rate',0)>=.70 and
              mb.get('max_positive_symbol_share',1)<=.30 and
              pb.get('return',0)>0 and ps.get('return',0)>0 and ps.get('max_dd',1)<=.12
            )
            rows.append({'name':name,'btc_gap':gap,'btc_ret42':ret,'breadth':br,'breadth_slope6':sl,'coin_ema_dist':cd,
                         **{f'base_{k}':v for k,v in mb.items()},**{f'stress_{k}':v for k,v in ms.items()},
                         'base_portfolio_return':pb['return'],'base_portfolio_dd':pb['max_dd'],
                         'stress_portfolio_return':ps['return'],'stress_portfolio_dd':ps['max_dd'],'passes_gate':passed})
            cache[name]=(b,s)
    R=pd.DataFrame(rows)
    R['score']=R.passes_gate.astype(int)*1000+R.base_weekly_prob_positive.fillna(0)*100+R.stress_pf.fillna(0)*10+R.base_positive_active_quarter_rate.fillna(0)
    R=R.sort_values(['passes_gate','score','base_pf'],ascending=[False,False,False])
    R.to_csv(out/'regime_gate_grid.csv',index=False)
    passing=R[R.passes_gate]
    selected=passing.iloc[0].to_dict() if len(passing) else None
    if selected:
        b,s=cache[selected['name']]
        b.to_csv(out/'selected_base.csv.gz',index=False,compression='gzip')
        s.to_csv(out/'selected_stress.csv.gz',index=False,compression='gzip')
    summary={'version':'R16.13','frozen_signal':'FR_D40_A24_B45_STRICT_S2_T4_H30',
             'raw_base':stats(B),'raw_stress':stats(S),'candidate_gates':int(len(R)),
             'strict_pass_count':int(R.passes_gate.sum()),'selected':selected,'top10':R.head(10).to_dict('records'),
             'period':'2021-01-01..2026-06-30','july_august_used':False,
             'notes':['Only regime gating was varied.','No leverage.','No ML.','September 2026 remains untouched.']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8')
    print(json.dumps(summary,indent=2,default=float),flush=True)

if __name__=='__main__':main()
