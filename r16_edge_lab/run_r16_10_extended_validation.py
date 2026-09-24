#!/usr/bin/env python3
"""R16.10 Extended Historical Validation.

Signal rules are frozen BEFORE opening 2021-2023 history.

Evaluates:
1) Frozen CORE: D55 / ADX30 / breadth55 / BTC strict / S2-T6-H30.
2) Frozen FLUSH H6_N3_SEVERITY:
   ret6<=-9%, volz>=2, RSI<=32, body_pos>=.60,
   stop1.25 ATR / target2.5 ATR / hold18h,
   6h cluster, max 3 signals ranked by deepest 6h decline.
3) Frozen FLUSH H1_N3_SEVERITY:
   same trade rule, 1h cluster, max 3, severity ranking.

Data: pre2024 root + existing 2024-2026 root, truncated at 2026-07-01.
No tuning. No ML. No leverage.
"""
from __future__ import annotations
import argparse, json, heapq
from pathlib import Path
import numpy as np
import pandas as pd

DEV_END=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016
STRESS_COST=.0021
SEED=16100
START_CAP=10_000.
CORE_RISK=.0025
CORE_MAX=5
FLUSH_RISK=.0010
FLUSH_MAX=2
NOTIONAL_CAP=.25

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):
    return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def load_pair(pre,post,iv,sym):
    frames=[]
    for root in [pre,post]:
        p=root/iv/f'{sym}.csv.gz'
        if p.exists():
            x=pd.read_csv(p)
            frames.append(x)
    if not frames:
        return pd.DataFrame()
    x=pd.concat(frames,ignore_index=True)
    for c in ['open_time','open','high','low','close','volume']:
        x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close']).drop_duplicates('open_time').sort_values('open_time')
    x=x[x.open_time<DEV_END].reset_index(drop=True)
    h,l,c,v=x.high,x.low,x.close,x.volume
    pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x['atr']=atr
    x['adx']=rma(dx,14)
    x['ema50']=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x['ema200']=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x['ret6']=c.pct_change(6)
    x['ret42']=c.pct_change(42)
    x['rsi14']=100-(100/(1+rma(c.diff().clip(lower=0),14)/rma((-c.diff()).clip(lower=0),14).replace(0,np.nan)))
    x['volz48']=(v-v.rolling(48,min_periods=36).mean())/v.rolling(48,min_periods=36).std().replace(0,np.nan)
    x['body_pos']=(c-l)/(h-l).replace(0,np.nan)
    return x

def build_context(F4):
    parts=[]
    for sym,z in F4.items():
        if z.empty:
            continue
        ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),
                      index=z.open_time.astype('int64'),name=sym)
        parts.append(ser[~ser.index.duplicated()])
    b=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
    btc=F4['BTCUSDT'].set_index('open_time')
    ctx=pd.DataFrame(index=b.index)
    ctx['breadth']=b
    ctx['btc_strict']=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0)).reindex(ctx.index).fillna(False)
    return ctx

def simulate(z,i,stop_atr,target_atr,hold,cost,sym,bar_ms):
    if i>=len(z)-1:
        return None
    atr=float(z.atr.iloc[i])
    if not np.isfinite(atr) or atr<=0:
        return None
    ei=i+1
    entry=float(z.open.iloc[ei])
    stop=entry-stop_atr*atr
    target=entry+target_atr*atr
    end=min(ei+hold-1,len(z)-1)
    px=float(z.close.iloc[end])
    xi=end
    reason='TIME'
    for j in range(ei,end+1):
        hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j])
        hs=lo<=stop;ht=hi>=target
        if hs and ht:
            px=stop;xi=j;reason='STOP_AMBIGUOUS';break
        if hs:
            px=stop;xi=j;reason='STOP';break
        if ht:
            px=target;xi=j;reason='TARGET';break
    return {
        'symbol':sym,'signal_time':int(z.open_time.iloc[i]),
        'entry_time':int(z.open_time.iloc[ei]),
        'exit_time':int(z.open_time.iloc[xi])+bar_ms,
        'stop_pct':stop_atr*atr/entry,
        'net_pct':(px-entry)/entry-2*cost,
        'reason':reason
    }

def core_trades(F4,ctx,cost):
    rows=[]
    for sym,z in F4.items():
        if z.empty:
            continue
        hi55=z.high.shift(1).rolling(55,min_periods=55).max()
        sig=(z.close>hi55)&(z.close.shift(1)<=hi55.shift())&(z.ema50>z.ema200)&(z.adx>=30)
        last_exit=-1
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            if i<=last_exit:
                continue
            ts=int(z.open_time.iloc[i])
            if ts not in ctx.index:
                continue
            if not bool(ctx.loc[ts,'btc_strict']) or float(ctx.loc[ts,'breadth'])<.55:
                continue
            r=simulate(z,i,2.,6.,30,cost,sym,4*3600_000)
            if r:
                rows.append(r)
                last_exit=int(np.searchsorted(z.open_time.to_numpy(),r['exit_time']-4*3600_000,side='left'))
    return pd.DataFrame(rows)

def raw_flush(F1,cost):
    rows=[]
    for sym,z in F1.items():
        if z.empty:
            continue
        sig=(z.ret6<=-.09)&(z.volz48>=2.)&(z.rsi14<=32)&(z.body_pos>=.60)
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            r=simulate(z,i,1.25,2.5,18,cost,sym,3600_000)
            if r:
                r.update({
                    'ret6':float(z.ret6.iloc[i]),
                    'volz48':float(z.volz48.iloc[i]),
                    'body_pos':float(z.body_pos.iloc[i]),
                    'rsi14':float(z.rsi14.iloc[i])
                })
                rows.append(r)
    return pd.DataFrame(rows)

def cluster_severity(df,hours,max_entries=3):
    if df.empty:
        return df.copy()
    x=df.copy()
    ms=hours*3600_000
    x['cluster']=(x.signal_time//ms)*ms
    x['rank_score']=-x.ret6
    x=x.sort_values(['cluster','rank_score'],ascending=[True,False]).groupby('cluster',sort=False).head(max_entries)
    x=x.sort_values(['symbol','entry_time'])
    keep=[];last={}
    for idx,r in x.iterrows():
        le=last.get(r.symbol,-1)
        if int(r.entry_time)<=le:
            continue
        keep.append(idx)
        last[r.symbol]=int(r.exit_time)
    return x.loc[keep].sort_values('entry_time').reset_index(drop=True)

def pf(a):
    a=np.asarray(a,float)
    gp=a[a>0].sum();gl=-a[a<0].sum()
    return float(gp/gl) if gl>0 else None

def weekly_series(d):
    if d.empty:
        return pd.Series(dtype=float)
    x=d.copy()
    dt=pd.to_datetime(x.entry_time,unit='ms',utc=True)
    x['week']=(dt-dt.dt.weekday.astype('timedelta64[D]')).dt.floor('D')
    return x.groupby('week').net_pct.sum()

def bootstrap(d,n=3000):
    w=weekly_series(d).to_numpy(float)
    if len(w)<15:
        return 0.
    rng=np.random.default_rng(SEED)
    vals=np.empty(n)
    for i in range(n):
        vals[i]=rng.choice(w,len(w),replace=True).mean()
    return float((vals>0).mean())

def metrics(d,core_week=None):
    if d.empty:
        return {'trades':0}
    r=d.net_pct.to_numpy(float)
    dt=pd.to_datetime(d.entry_time,unit='ms',utc=True)
    x=d.copy()
    x['year']=dt.dt.year
    x['quarter']=dt.dt.to_period('Q').astype(str)
    x['month']=dt.dt.to_period('M').astype(str)
    y=x.groupby('year').net_pct.sum()
    q=x.groupby('quarter').net_pct.sum()
    m=x.groupby('month').net_pct.sum()
    sy=x.groupby('symbol').net_pct.sum();pos=sy.clip(lower=0)
    w=weekly_series(x)
    corr=None
    if core_week is not None:
        common=w.index.intersection(core_week.index)
        if len(common)>=10:
            corr=float(w.loc[common].corr(core_week.loc[common]))
    return {
        'trades':int(len(x)),
        'avg':float(r.mean()),
        'pf':pf(r),
        'win_rate':float((r>0).mean()),
        'all_years_positive':bool((y>0).all()),
        'positive_quarter_rate':float((q>0).mean()),
        'weekly_prob_positive':bootstrap(x),
        'positive_month_rate':float((m>0).mean()),
        'active_months':int(len(m)),
        'median_month_sum':float(m.median()),
        'max_positive_symbol_share':float(pos.max()/pos.sum()) if pos.sum()>0 else 1.,
        'weekly_corr_core':corr,
        'yearly':{str(int(k)):float(v) for k,v in y.items()},
        'trades_by_year':{str(int(k)):int(v) for k,v in x.groupby('year').size().items()}
    }

def core_portfolio(core):
    if core.empty:
        return {'end':START_CAP,'return':0.,'max_dd':0.,'accepted':0}
    eq=START_CAP;curve=[eq];heap=[];syms=set();uid=acc=rej=0
    def settle(t):
        nonlocal eq
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym=heapq.heappop(heap)
            eq+=pnl;syms.discard(sym);curve.append(eq)
    for r in core.sort_values(['entry_time','symbol']).itertuples(index=False):
        settle(int(r.entry_time))
        if len(heap)>=CORE_MAX or r.symbol in syms:
            rej+=1;continue
        notional=min(eq*NOTIONAL_CAP,eq*CORE_RISK/max(float(r.stop_pct),1e-6))
        pnl=notional*float(r.net_pct)
        heapq.heappush(heap,(int(r.exit_time),uid,pnl,r.symbol));syms.add(r.symbol);uid+=1;acc+=1
    settle(10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {'end':float(eq),'return':float(eq/START_CAP-1),'max_dd':float(-dd.min()),'accepted':acc,'rejected':rej}

def combined_portfolio(core,flush,flush_risk=FLUSH_RISK,flush_max=FLUSH_MAX):
    events=[]
    for r in core.itertuples(index=False):
        events.append(('CORE',int(r.entry_time),int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    for r in flush.itertuples(index=False):
        events.append(('FLUSH',int(r.entry_time),int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    events.sort(key=lambda z:(z[1],0 if z[0]=='CORE' else 1,z[3]))
    eq=START_CAP;curve=[eq]
    ch=[];fh=[];cs=set();fs=set();uid=ca=fa=rej=0
    def settle(heap,syms,t):
        nonlocal eq
        while heap and heap[0][0]<=t:
            ex,_,pnl,sym=heapq.heappop(heap)
            eq+=pnl;syms.discard(sym);curve.append(eq)
    for kind,et,xt,sym,sp,nr in events:
        settle(ch,cs,et);settle(fh,fs,et)
        if kind=='CORE':
            if len(ch)>=CORE_MAX or sym in cs or sym in fs:
                rej+=1;continue
            risk=CORE_RISK;heap=ch;syms=cs;ca+=1
        else:
            if len(fh)>=flush_max or sym in cs or sym in fs:
                rej+=1;continue
            risk=flush_risk;heap=fh;syms=fs;fa+=1
        notional=min(eq*NOTIONAL_CAP,eq*risk/max(sp,1e-6))
        pnl=notional*nr
        heapq.heappush(heap,(xt,uid,pnl,sym));syms.add(sym);uid+=1
    settle(ch,cs,10**30);settle(fh,fs,10**30)
    a=np.asarray(curve,float);peak=np.maximum.accumulate(a);dd=a/peak-1
    return {
        'end':float(eq),'return':float(eq/START_CAP-1),'max_dd':float(-dd.min()),
        'core_accepted':ca,'flush_accepted':fa,'rejected':rej
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pre',default='r16_edge_lab/pre2024_history')
    ap.add_argument('--post',default='r15_regime_lab/history')
    ap.add_argument('--output',default='r16_edge_lab/r16_10_extended_validation')
    args=ap.parse_args()
    pre=Path(args.pre);post=Path(args.post);out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)

    print('Loading merged 2021-2026 data...',flush=True)
    F1={s:load_pair(pre,post,'1h',s) for s in SYMBOLS}
    F4={s:load_pair(pre,post,'4h',s) for s in SYMBOLS}
    ctx=build_context(F4)

    results={}
    for cname,cost in [('base',BASE_COST),('stress',STRESS_COST)]:
        print(f'Simulating {cname}...',flush=True)
        core=core_trades(F4,ctx,cost)
        raw=raw_flush(F1,cost)
        h6=cluster_severity(raw,6,3)
        h1=cluster_severity(raw,1,3)
        cw=weekly_series(core)
        results[cname]={
            'core_df':core,'h6_df':h6,'h1_df':h1,
            'core':metrics(core),
            'h6':metrics(h6,cw),
            'h1':metrics(h1,cw),
            'core_portfolio':core_portfolio(core),
            'core_plus_h6_risk_0_10':combined_portfolio(core,h6,.0010,2),
            'core_plus_h1_risk_0_10':combined_portfolio(core,h1,.0010,2)
        }

    # Frozen pass rule from R16.9B: now sample >=100 is expected from extended history.
    def passes(m,stress):
        return bool(
            m.get('trades',0)>=100 and
            m.get('pf',0)>=1.25 and stress.get('pf',0)>=1.20 and
            m.get('avg',0)>0 and stress.get('avg',0)>0 and
            m.get('all_years_positive',False) and
            m.get('positive_quarter_rate',0)>=.70 and
            m.get('weekly_prob_positive',0)>=.90 and
            m.get('max_positive_symbol_share',1)<=.30 and
            (m.get('weekly_corr_core') is None or abs(m.get('weekly_corr_core'))<=.40)
        )

    h6_pass=passes(results['base']['h6'],results['stress']['h6'])
    h1_pass=passes(results['base']['h1'],results['stress']['h1'])

    for cost in ['base','stress']:
        for name in ['core_df','h6_df','h1_df']:
            df=results[cost].pop(name)
            df.to_csv(out/f'{cost}_{name.replace("_df","")}_trades.csv.gz',index=False,compression='gzip')

    summary={
        'version':'R16.10',
        'period':'2021-01-01..2026-06-30',
        'validation_type':'extended historical out-of-sample for 2021-2023; frozen rules',
        'frozen_candidates':{
            'H6_N3_SEVERITY':'D9_R60 + 6h cluster + max3 + severity ranking',
            'H1_N3_SEVERITY':'D9_R60 + 1h cluster + max3 + severity ranking'
        },
        'base':results['base'],
        'stress':results['stress'],
        'frozen_gate':{
            'H6_passes':h6_pass,
            'H1_passes':h1_pass
        },
        'july_august_used':False,
        'no_rule_changes_after_pre2024_open':True,
        'notes':[
            'No leverage.',
            'No ML.',
            '2021-2023 were not used to discover or tune H6/H1 rules.',
            'Portfolio scenario uses fixed 0.10% risk per FLUSH trade and max 2 FLUSH positions; it is descriptive, not tuned on pre-2024.'
        ]
    }
    (out/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8')
    print(json.dumps(summary,indent=2,default=float),flush=True)

if __name__=='__main__':
    main()
