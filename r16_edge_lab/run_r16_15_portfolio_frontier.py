#!/usr/bin/env python3
"""R16.15 Frozen CORE + Extreme Reversion Portfolio Frontier

Frozen engines:
CORE:
  4h D55 breakout, EMA50>EMA200, ADX>=30, BTC strict up, breadth>=55%,
  stop2 ATR / target6 ATR / hold30x4h.
REV:
  1h LONG after ret6<=-8%, volz>=1.5, RSI<=35, body_pos>=.60,
  stop1.5 ATR / target3 ATR / hold24h,
  3h cluster, max 3 signals ranked by deepest decline.

Portfolio grid:
- CORE risk/trade: 0.25%, 0.50%, 0.75%, 1.00%
- REV risk/trade: 0.25%, 0.50%, 0.75%, 1.00%, 1.50%
- REV max positions: 3 or 5
- CORE max positions: 5
- per-position notional cap 25%
- GLOBAL gross notional cap 100% of realized equity (no leverage)

Base/stress costs.
Outputs realized-equity monthly returns plus conservative open-risk drawdown.
Data through 2026-06-30 only.
"""
from __future__ import annotations
import argparse,json,heapq
from pathlib import Path
import numpy as np,pandas as pd

START=int(pd.Timestamp("2021-01-01T00:00:00Z").timestamp()*1000)
END=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
BASE_COST=.0016;STRESS_COST=.0021
START_CAP=10000.;PER_POS_CAP=.25;GLOBAL_CAP=1.0
SEED=16150
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n):return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def load_pair(pre,post,iv,sym):
    fs=[]
    for root in [pre,post]:
        p=root/iv/f'{sym}.csv.gz'
        if p.exists():fs.append(pd.read_csv(p))
    if not fs:return pd.DataFrame()
    x=pd.concat(fs,ignore_index=True)
    for c in ['open_time','open','high','low','close','volume']:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close']).drop_duplicates('open_time').sort_values('open_time')
    x=x[(x.open_time>=START)&(x.open_time<END)].reset_index(drop=True)
    h,l,c,v=x.high,x.low,x.close,x.volume;pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1);atr=rma(tr,14)
    x['atr']=atr
    if iv=='4h':
        up=h.diff();dn=-l.diff()
        plus=100*rma(up.where((up>dn)&(up>0),0.),14)/atr.replace(0,np.nan)
        minus=100*rma(dn.where((dn>up)&(dn>0),0.),14)/atr.replace(0,np.nan)
        dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
        x['adx']=rma(dx,14);x['ema50']=c.ewm(span=50,adjust=False,min_periods=50).mean();x['ema200']=c.ewm(span=200,adjust=False,min_periods=200).mean()
        x['ret42']=c.pct_change(42);x['hi55']=h.shift(1).rolling(55,min_periods=55).max()
    else:
        x['ret6']=c.pct_change(6)
        gain=rma(c.diff().clip(lower=0),14);loss=rma((-c.diff()).clip(lower=0),14)
        x['rsi14']=100-(100/(1+gain/loss.replace(0,np.nan)))
        x['volz48']=(v-v.rolling(48,min_periods=36).mean())/v.rolling(48,min_periods=36).std().replace(0,np.nan)
        x['body_pos']=(c-l)/(h-l).replace(0,np.nan)
    return x

def build_core(F4,cost):
    parts=[]
    for s,z in F4.items():
        if z.empty:continue
        ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),index=z.open_time.astype('int64'),name=s)
        parts.append(ser[~ser.index.duplicated()])
    breadth=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
    btc=F4['BTCUSDT'].set_index('open_time')
    strict=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0)).reindex(breadth.index).fillna(False)
    rows=[]
    for sym,z in F4.items():
        if z.empty:continue
        sig=(z.close>z.hi55)&(z.close.shift(1)<=z.hi55.shift())&(z.ema50>z.ema200)&(z.adx>=30)
        last=-1
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            if i<=last or i>=len(z)-1:continue
            ts=int(z.open_time.iloc[i])
            if ts not in breadth.index or not bool(strict.loc[ts]) or float(breadth.loc[ts])<.55:continue
            atr=float(z.atr.iloc[i]);ei=i+1
            if not np.isfinite(atr) or atr<=0:continue
            entry=float(z.open.iloc[ei]);stop=entry-2*atr;target=entry+6*atr
            end=min(ei+29,len(z)-1);px=float(z.close.iloc[end]);xi=end
            for j in range(ei,end+1):
                hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=lo<=stop;ht=hi>=target
                if hs and ht:px=stop;xi=j;break
                if hs:px=stop;xi=j;break
                if ht:px=target;xi=j;break
            rows.append({'engine':'CORE','symbol':sym,'entry_time':int(z.open_time.iloc[ei]),'exit_time':int(z.open_time.iloc[xi])+4*3600_000,
                         'stop_pct':2*atr/entry,'net_pct':(px-entry)/entry-2*cost})
            last=xi
    return pd.DataFrame(rows)

def build_rev(F1,cost):
    raw=[]
    for sym,z in F1.items():
        if z.empty:continue
        sig=(z.ret6<=-.08)&(z.volz48>=1.5)&(z.rsi14<=35)&(z.body_pos>=.60)
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            if i>=len(z)-1:continue
            atr=float(z.atr.iloc[i])
            if not np.isfinite(atr) or atr<=0:continue
            ei=i+1;entry=float(z.open.iloc[ei]);stop=entry-1.5*atr;target=entry+3*atr
            end=min(ei+23,len(z)-1);px=float(z.close.iloc[end]);xi=end
            for j in range(ei,end+1):
                hi=float(z.high.iloc[j]);lo=float(z.low.iloc[j]);hs=lo<=stop;ht=hi>=target
                if hs and ht:px=stop;xi=j;break
                if hs:px=stop;xi=j;break
                if ht:px=target;xi=j;break
            raw.append({'engine':'REV','symbol':sym,'signal_time':int(z.open_time.iloc[i]),'entry_time':int(z.open_time.iloc[ei]),
                        'exit_time':int(z.open_time.iloc[xi])+3600_000,'stop_pct':1.5*atr/entry,
                        'net_pct':(px-entry)/entry-2*cost,'ret6':float(z.ret6.iloc[i])})
    x=pd.DataFrame(raw)
    if x.empty:return x
    x['cluster']=(x.signal_time//(3*3600_000))*(3*3600_000);x['rank_score']=-x.ret6
    x=x.sort_values(['cluster','rank_score'],ascending=[True,False]).groupby('cluster',sort=False).head(3)
    x=x.sort_values(['symbol','entry_time'])
    keep=[];last={}
    for idx,r in x.iterrows():
        if int(r.entry_time)<=last.get(r.symbol,-1):continue
        keep.append(idx);last[r.symbol]=int(r.exit_time)
    return x.loc[keep].sort_values('entry_time').drop(columns=['cluster','rank_score']).reset_index(drop=True)

def simulate(core,rev,core_risk,rev_risk,rev_max):
    events=[]
    for r in core.itertuples(index=False):events.append(('CORE',int(r.entry_time),int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    for r in rev.itertuples(index=False):events.append(('REV',int(r.entry_time),int(r.exit_time),r.symbol,float(r.stop_pct),float(r.net_pct)))
    events.sort(key=lambda z:(z[1],0 if z[0]=='CORE' else 1,z[3]))
    eq=START_CAP;peak=eq;worst_openrisk_dd=0.;uid=0
    heaps={'CORE':[],'REV':[]};active={'CORE':set(),'REV':set()};all_active={}
    monthly_pnl={};accepted={'CORE':0,'REV':0};rejected=0
    maxpos={'CORE':5,'REV':rev_max};risks={'CORE':core_risk,'REV':rev_risk}
    gross_notional=0.
    def settle_until(t):
        nonlocal eq,gross_notional,peak,worst_openrisk_dd
        due=[]
        for eng in ['CORE','REV']:
            while heaps[eng] and heaps[eng][0][0]<=t:
                due.append(heapq.heappop(heaps[eng]))
        due.sort()
        for ex,_,pnl,sym,eng,notional,risk_amt in due:
            eq+=pnl;gross_notional-=notional;active[eng].discard(sym);all_active.pop((eng,sym),None)
            mo=str(pd.to_datetime(ex,unit='ms',utc=True).to_period('M'));monthly_pnl[mo]=monthly_pnl.get(mo,0.)+pnl
            peak=max(peak,eq)
            openrisk=sum(v[1] for v in all_active.values())
            conservative_eq=eq-openrisk
            worst_openrisk_dd=max(worst_openrisk_dd,1-conservative_eq/peak)
    for eng,et,xt,sym,sp,nr in events:
        settle_until(et)
        if len(heaps[eng])>=maxpos[eng] or sym in active['CORE'] or sym in active['REV']:
            rejected+=1;continue
        risk_amt=eq*risks[eng]
        desired=min(eq*PER_POS_CAP,risk_amt/max(sp,1e-6))
        capacity=max(0.,eq*GLOBAL_CAP-gross_notional)
        notional=min(desired,capacity)
        if notional<eq*.01:
            rejected+=1;continue
        actual_risk=notional*sp
        pnl=notional*nr
        heapq.heappush(heaps[eng],(xt,uid,pnl,sym,eng,notional,actual_risk));uid+=1
        active[eng].add(sym);all_active[(eng,sym)]=(notional,actual_risk);gross_notional+=notional;accepted[eng]+=1
        openrisk=sum(v[1] for v in all_active.values());peak=max(peak,eq)
        worst_openrisk_dd=max(worst_openrisk_dd,1-(eq-openrisk)/peak)
    settle_until(10**30)
    months=pd.period_range('2021-01','2026-06',freq='M').astype(str)
    vals=[];e=START_CAP
    for mo in months:
        p=monthly_pnl.get(mo,0.);ret=p/e if e>0 else 0.;vals.append(ret);e+=p
    a=np.asarray(vals,float)
    return {'end':float(eq),'return':float(eq/START_CAP-1),'open_risk_dd':float(worst_openrisk_dd),
            'accepted':accepted,'rejected':rejected,'monthly_mean':float(a.mean()),'monthly_median':float(np.median(a)),
            'positive_month_rate':float((a>0).mean()),'months_ge_10pct':int((a>=.10).sum()),'months_ge_20pct':int((a>=.20).sum()),
            'best_month':float(a.max()),'worst_month':float(a.min()),'monthly_returns':vals}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pre',default='r16_edge_lab/pre2024_history');ap.add_argument('--post',default='r15_regime_lab/history');ap.add_argument('--output',default='r16_edge_lab/r16_15_portfolio_frontier')
    args=ap.parse_args();pre=Path(args.pre);post=Path(args.post);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    F4={s:load_pair(pre,post,'4h',s) for s in SYMBOLS};F1={s:load_pair(pre,post,'1h',s) for s in SYMBOLS}
    CB=build_core(F4,BASE_COST);CS=build_core(F4,STRESS_COST);RB=build_rev(F1,BASE_COST);RS=build_rev(F1,STRESS_COST)
    rows=[]
    for cr in [.0025,.005,.0075,.01]:
      for rr in [.0025,.005,.0075,.01,.015]:
       for rm in [3,5]:
        b=simulate(CB,RB,cr,rr,rm);s=simulate(CS,RS,cr,rr,rm)
        robust=bool(b['open_risk_dd']<=.20 and s['open_risk_dd']<=.25 and s['return']>0)
        rows.append({'core_risk':cr,'rev_risk':rr,'rev_max':rm,
                     'base_return':b['return'],'base_dd':b['open_risk_dd'],'base_month_mean':b['monthly_mean'],'base_month_median':b['monthly_median'],
                     'base_pos_month_rate':b['positive_month_rate'],'base_m20':b['months_ge_20pct'],'base_best_month':b['best_month'],'base_worst_month':b['worst_month'],
                     'stress_return':s['return'],'stress_dd':s['open_risk_dd'],'stress_month_mean':s['monthly_mean'],'stress_month_median':s['monthly_median'],
                     'stress_pos_month_rate':s['positive_month_rate'],'stress_m20':s['months_ge_20pct'],'stress_best_month':s['best_month'],'stress_worst_month':s['worst_month'],
                     'robust':robust})
    R=pd.DataFrame(rows).sort_values(['robust','stress_return','stress_dd'],ascending=[False,False,True])
    R.to_csv(out/'portfolio_frontier.csv',index=False)
    robust=R[R.robust]
    selected=robust.iloc[0].to_dict() if len(robust) else R.iloc[0].to_dict()
    b=simulate(CB,RB,float(selected['core_risk']),float(selected['rev_risk']),int(selected['rev_max']))
    s=simulate(CS,RS,float(selected.core_risk),float(selected.rev_risk),int(selected.rev_max))
    months=pd.period_range('2021-01','2026-06',freq='M').astype(str)
    pd.DataFrame({'month':months,'base_return':b['monthly_returns'],'stress_return':s['monthly_returns']}).to_csv(out/'selected_monthly_returns.csv',index=False)
    summary={'version':'R16.15','period':'2021-01-01..2026-06-30','frozen_engines':['CORE','LONG_M8_V15_B60_G1_C3'],
             'global_gross_cap':1.0,'per_position_cap':.25,'grid_size':int(len(R)),'selected':selected,
             'selected_base':{k:v for k,v in b.items() if k!='monthly_returns'},'selected_stress':{k:v for k,v in s.items() if k!='monthly_returns'},
             'project_target_monthly':.20,'target_hit_note':'Reports actual count of realized-equity months >=20%; target is not forced.',
             'notes':['No leverage: global gross notional is capped at 100% of realized equity.','Drawdown is conservatively adjusted by open risk-at-stop.','September 2026 remains untouched.']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,default=float),encoding='utf-8')
    print(json.dumps(summary,indent=2,default=float),flush=True)
if __name__=='__main__':main()
