from __future__ import annotations

import json, math, os, sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from r13_1_mtf import run_r13_1_mtf as base

VERSION = 'V10-R14-RANGE-BREAKOUT-ENGINE'
DATA_ROOT = Path(os.environ.get('R14_DATA_ROOT', '../r13_1_dataset'))
START = pd.Timestamp('2024-01-01T00:00:00Z')
END_EXCLUSIVE = pd.Timestamp('2026-09-21T00:00:00Z')
ONE_WAY_COST = 0.0016
STRESS_ONE_WAY_COST = 0.0021
INITIAL_EQUITY = 10_000.0
MAX_POSITIONS = 10
TARGET_SLOT = 1.0 / MAX_POSITIONS
MIN_RANGE_WIDTH = 0.018
MAX_RANGE_WIDTH = 0.12
RANGE_POS_EDGE = 0.18
RANGE_EXIT_EDGE = 0.82
RANGE_EFF_MAX = 0.38
RANGE_ADX_MAX = 26.0
MIN_TOUCHES = 2
BREAKOUT_ATR = 0.30
BREAKOUT_VOL_Z = 0.35
TREND_ADX_MIN = 22.0
TREND_TRAIL_ATR = 2.2
CATASTROPHIC_STOP = 0.05
COOLDOWN_BARS = 2
MIN_EDGE_TO_COST = 4.0


def load_universe(symbols):
    old = base.DATA_ROOT
    base.DATA_ROOT = DATA_ROOT
    try:
        d15, d1, d4, skipped = base.load_universe(symbols)
    finally:
        base.DATA_ROOT = old
    return d15, d1, d4, skipped


def rsi(s, n=14):
    d=s.diff(); up=d.clip(lower=0); dn=(-d).clip(lower=0)
    au=up.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=au/ad.replace(0,np.nan)
    return 100-100/(1+rs)


def atr(df,n=14):
    pc=df.close.shift(1)
    tr=pd.concat([(df.high-df.low),(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()


def adx(df,n=14):
    up=df.high.diff(); dn=-df.low.diff()
    plus=np.where((up>dn)&(up>0),up,0.0); minus=np.where((dn>up)&(dn>0),dn,0.0)
    tr=atr(df,n)
    plus_di=100*pd.Series(plus,index=df.index).ewm(alpha=1/n,adjust=False,min_periods=n).mean()/tr
    minus_di=100*pd.Series(minus,index=df.index).ewm(alpha=1/n,adjust=False,min_periods=n).mean()/tr
    dx=100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False,min_periods=n).mean()


def features15(df):
    q=df.copy()
    q['atr']=atr(q); q['atr_pct']=q.atr/q.close
    q['rsi']=rsi(q.close)
    q['ema20']=q.close.ewm(span=20,adjust=False,min_periods=20).mean()
    q['ema50']=q.close.ewm(span=50,adjust=False,min_periods=50).mean()
    q['ret1']=q.close.pct_change(); q['ret4']=q.close.pct_change(4)
    q['vol_mean']=q.volume.rolling(32,min_periods=16).mean(); q['vol_std']=q.volume.rolling(32,min_periods=16).std()
    q['vol_z']=(q.volume-q.vol_mean)/q.vol_std.replace(0,np.nan)
    # Prior rolling range only: shift prevents current bar from defining its own support/resistance.
    q['range_hi']=q.high.shift(1).rolling(32,min_periods=24).max()
    q['range_lo']=q.low.shift(1).rolling(32,min_periods=24).min()
    q['range_width']=q.range_hi/q.range_lo-1.0
    q['range_pos']=(q.close-q.range_lo)/(q.range_hi-q.range_lo).replace(0,np.nan)
    # Efficiency: directional displacement / travelled path.
    net=(q.close-q.close.shift(16)).abs()
    path=q.close.diff().abs().rolling(16,min_periods=12).sum()
    q['eff16']=net/path.replace(0,np.nan)
    tol=(q.range_width*0.08).clip(lower=0.002)
    q['near_lo']=((q.low/q.range_lo-1.0).abs()<=tol).astype(float)
    q['near_hi']=((q.high/q.range_hi-1.0).abs()<=tol).astype(float)
    q['touch_lo']=q.near_lo.shift(1).rolling(32,min_periods=24).sum()
    q['touch_hi']=q.near_hi.shift(1).rolling(32,min_periods=24).sum()
    q['swing_low4']=q.low.shift(1).rolling(4,min_periods=4).min()
    q['swing_high4']=q.high.shift(1).rolling(4,min_periods=4).max()
    return q


def features1h(df):
    q=df.copy()
    q['atr1h']=atr(q); q['atr1h_pct']=q.atr1h/q.close
    q['ema20_1h']=q.close.ewm(span=20,adjust=False,min_periods=20).mean()
    q['ema50_1h']=q.close.ewm(span=50,adjust=False,min_periods=50).mean()
    q['ema20_slope']=q.ema20_1h.pct_change(4)
    q['adx1h']=adx(q)
    q['ret4h']=q.close.pct_change(4)
    q['ret12h']=q.close.pct_change(12)
    return q[['ema20_1h','ema50_1h','ema20_slope','adx1h','ret4h','ret12h','atr1h_pct']]


def build_symbol(d15,d1):
    a=features15(d15)
    h=features1h(d1).reindex(a.index,method='ffill')
    return a.join(h,how='left')


def state_from_row(r):
    if not np.isfinite(r.range_width) or not np.isfinite(r.atr_pct) or not np.isfinite(r.adx1h): return 'UNKNOWN'
    range_ok=(MIN_RANGE_WIDTH<=r.range_width<=MAX_RANGE_WIDTH and r.eff16<=RANGE_EFF_MAX and r.adx1h<=RANGE_ADX_MAX and r.touch_lo>=MIN_TOUCHES and r.touch_hi>=MIN_TOUCHES and r.range_width >= MIN_EDGE_TO_COST*2*ONE_WAY_COST)
    if range_ok: return 'RANGE'
    if r.adx1h>=TREND_ADX_MIN and r.ema20_1h>r.ema50_1h and r.ema20_slope>0: return 'TREND_UP'
    if r.adx1h>=TREND_ADX_MIN and r.ema20_1h<r.ema50_1h and r.ema20_slope<0: return 'TREND_DOWN'
    return 'TRANSITION'


def signals(r):
    st=state_from_row(r)
    out={'regime':st,'range_long':False,'range_short':False,'breakout_up':False,'breakout_down':False,'trend_exit_long':False,'trend_exit_short':False,'score_long':0.0,'score_short':0.0}
    if not np.isfinite(r.atr_pct): return out
    bull_reject=(r.close>r.open and r.close>r.low+0.55*(r.high-r.low))
    bear_reject=(r.close<r.open and r.close<r.low+0.45*(r.high-r.low))
    if st=='RANGE':
        out['range_long']=bool(r.range_pos<=RANGE_POS_EDGE and bull_reject and r.rsi<=48)
        out['range_short']=bool(r.range_pos>=1-RANGE_POS_EDGE and bear_reject and r.rsi>=52)
        quality=max(0.0,1-r.eff16/RANGE_EFF_MAX)*min(r.touch_lo,r.touch_hi)/4.0
        out['score_long']=quality*max(0,0.5-r.range_pos)*r.range_width
        out['score_short']=quality*max(0,r.range_pos-0.5)*r.range_width
    bu=(r.close>r.range_hi*(1+BREAKOUT_ATR*r.atr_pct) and r.vol_z>=BREAKOUT_VOL_Z and r.ret4>0 and r.ema20_1h>=r.ema50_1h)
    bd=(r.close<r.range_lo*(1-BREAKOUT_ATR*r.atr_pct) and r.vol_z>=BREAKOUT_VOL_Z and r.ret4<0 and r.ema20_1h<=r.ema50_1h)
    out['breakout_up']=bool(bu); out['breakout_down']=bool(bd)
    if bu: out['score_long']=max(out['score_long'],r.range_width*(1+r.vol_z))
    if bd: out['score_short']=max(out['score_short'],r.range_width*(1+r.vol_z))
    out['trend_exit_long']=bool(r.close<r.ema20 and r.ret4<0 and (r.close<r.swing_low4 or r.adx1h<TREND_ADX_MIN))
    out['trend_exit_short']=bool(r.close>r.ema20 and r.ret4>0 and (r.close>r.swing_high4 or r.adx1h<TREND_ADX_MIN))
    return out


def simulate(feat, one_way_cost):
    syms=sorted(feat)
    start=max(x.index.min() for x in feat.values()); end=min(END_EXCLUSIVE,max(x.index.max() for x in feat.values())+pd.Timedelta(minutes=15))
    timeline=pd.date_range(max(start,START),end-pd.Timedelta(minutes=15),freq='15min',tz='UTC')
    realized=INITIAL_EQUITY; positions={}; cooldown={}; pending={}; pending_entries=[]; trades=[]; curve=[]; peak=INITIAL_EQUITY; last={}

    def equity(prices):
        u=0.0
        for s,p in positions.items():
            px=prices.get(s)
            if px is not None: u+=p['notional']*p['side']*(px/p['entry']-1)
        return realized+u

    def close(s,t,px,reason):
        nonlocal realized
        p=positions.pop(s); gross=p['side']*(px/p['entry']-1); exit_cost=p['notional']*one_way_cost
        pnl=p['notional']*gross-p['entry_cost']-exit_cost; realized+=p['notional']*gross-exit_cost
        trades.append({'symbol':s,'side':'LONG' if p['side']>0 else 'SHORT','entry_time':p['time'],'exit_time':t,'entry_price':p['entry'],'exit_price':float(px),'gross_return':float(gross),'net_return':float(gross-2*one_way_cost),'pnl_cash':float(pnl),'hold_hours':float((t-p['time'])/pd.Timedelta(hours=1)),'entry_mode':p['mode'],'exit_reason':reason})
        cooldown[s]=t+COOLDOWN_BARS*pd.Timedelta(minutes=15)

    for t in timeline:
        rows={}; opens={}; highs={}; lows={}; closes={}; sig={}
        for s in syms:
            if t not in feat[s].index: continue
            r=feat[s].loc[t]
            if not np.isfinite(r.close): continue
            rows[s]=r; opens[s]=float(r.open); highs[s]=float(r.high); lows[s]=float(r.low); closes[s]=float(r.close); last[s]=float(r.close); sig[s]=signals(r)
        # Execute pending exits/reversals at this open.
        for s in list(pending):
            if s not in opens: continue
            act=pending.pop(s); reverse=act.get('reverse')
            if s in positions: close(s,t,opens[s],act['reason'])
            if reverse and len(positions)<MAX_POSITIONS and cooldown.get(s,pd.Timestamp.min.tz_localize('UTC'))<=t:
                eq=max(equity(opens),1.0); notional=min(eq*TARGET_SLOT,eq)
                side=1 if reverse=='LONG' else -1; cost=notional*one_way_cost; realized-=cost
                positions[s]={'side':side,'entry':opens[s],'time':t,'notional':notional,'entry_cost':cost,'mode':'TREND','best':opens[s],'stop':opens[s]*(1-CATASTROPHIC_STOP if side>0 else 1+CATASTROPHIC_STOP)}
        # Execute entries signaled by the PREVIOUS completed 15m bar at this bar's open.
        if pending_entries:
            queued=sorted(pending_entries, reverse=True)
            pending_entries=[]
            used=set()
            for score,s,side,mode in queued:
                if len(positions)>=MAX_POSITIONS or s in used or s in positions or s not in opens:
                    continue
                if cooldown.get(s,pd.Timestamp.min.tz_localize('UTC'))>t:
                    continue
                eq=max(equity(opens),1.0); notional=min(eq*TARGET_SLOT,eq); cost=notional*one_way_cost; realized-=cost
                positions[s]={'side':side,'entry':opens[s],'time':t,'notional':notional,'entry_cost':cost,'mode':mode,'best':opens[s],'stop':opens[s]*(1-CATASTROPHIC_STOP if side>0 else 1+CATASTROPHIC_STOP)}
                used.add(s)
        # Manage existing positions using current completed-bar signal, action executes next open.
        for s,p in list(positions.items()):
            if s not in rows: continue
            r=rows[s]; sg=sig[s]; side=p['side']; gross=side*(closes[s]/p['entry']-1)
            if side>0: p['best']=max(p['best'],highs[s])
            else: p['best']=min(p['best'],lows[s])
            # Catastrophic intrabar cap.
            if side>0 and lows[s]<=p['stop']:
                close(s,t,p['stop'],'CATASTROPHIC_STOP'); continue
            if side<0 and highs[s]>=p['stop']:
                close(s,t,p['stop'],'CATASTROPHIC_STOP'); continue
            if p['mode']=='RANGE':
                if side>0:
                    if sg['breakout_up']:
                        p['mode']='TREND'; continue
                    if sg['breakout_down']:
                        pending[s]={'reason':'BREAKOUT_AGAINST','reverse':'SHORT'}; continue
                    if r.range_pos>=RANGE_EXIT_EDGE and (r.close<r.open or r.ret1<0):
                        pending[s]={'reason':'RANGE_TARGET','reverse':'SHORT' if sg['range_short'] else None}; continue
                else:
                    if sg['breakout_down']:
                        p['mode']='TREND'; continue
                    if sg['breakout_up']:
                        pending[s]={'reason':'BREAKOUT_AGAINST','reverse':'LONG'}; continue
                    if r.range_pos<=1-RANGE_EXIT_EDGE and (r.close>r.open or r.ret1>0):
                        pending[s]={'reason':'RANGE_TARGET','reverse':'LONG' if sg['range_long'] else None}; continue
            else: # TREND mode
                if side>0:
                    trail=p['best']*(1-TREND_TRAIL_ATR*max(float(r.atr_pct),0.001))
                    if closes[s]<trail or sg['trend_exit_long'] or sg['breakout_down']:
                        pending[s]={'reason':'TREND_LOST','reverse':'SHORT' if sg['breakout_down'] else None}
                else:
                    trail=p['best']*(1+TREND_TRAIL_ATR*max(float(r.atr_pct),0.001))
                    if closes[s]>trail or sg['trend_exit_short'] or sg['breakout_up']:
                        pending[s]={'reason':'TREND_LOST','reverse':'LONG' if sg['breakout_up'] else None}
        # Flat candidates from THIS completed bar are queued for the NEXT 15m open.
        slots=MAX_POSITIONS-len(positions)
        pending_entries=[]
        if slots>0:
            candidates=[]
            for s,r in rows.items():
                if s in positions or s in pending or cooldown.get(s,pd.Timestamp.min.tz_localize('UTC'))>t: continue
                sg=sig[s]
                if sg['range_long']: candidates.append((sg['score_long'],s,1,'RANGE'))
                if sg['range_short']: candidates.append((sg['score_short'],s,-1,'RANGE'))
                if sg['breakout_up']: candidates.append((sg['score_long'],s,1,'TREND'))
                if sg['breakout_down']: candidates.append((sg['score_short'],s,-1,'TREND'))
            pending_entries=sorted(candidates,reverse=True)[:slots]
        eq=equity(closes); peak=max(peak,eq); dd=1-eq/peak if peak>0 else 1
        curve.append({'time':t,'equity':eq,'drawdown':dd,'open_positions':len(positions)})
        if eq<=0: break
    if timeline.size:
        ft=timeline[-1]
        for s in list(positions):
            if s in last: close(s,ft,last[s],'END')
    td=pd.DataFrame(trades); cd=pd.DataFrame(curve)
    if td.empty: return td,cd,{'trades':0,'return':realized/INITIAL_EQUITY-1,'pf':None}
    win=td.loc[td.pnl_cash>0,'pnl_cash'].sum(); loss=-td.loc[td.pnl_cash<0,'pnl_cash'].sum(); pf=float(win/loss) if loss>0 else math.inf
    winners=td[td.net_return>0].net_return; losers=td[td.net_return<0].net_return
    return td,cd,{'trades':len(td),'return':float(realized/INITIAL_EQUITY-1),'pf':pf,'win_rate':float((td.pnl_cash>0).mean()),'avg_net':float(td.net_return.mean()),'avg_winner':float(winners.mean()) if len(winners) else None,'avg_loser':float(losers.mean()) if len(losers) else None,'payoff':float(winners.mean()/abs(losers.mean())) if len(winners) and len(losers) else None,'max_dd':float(cd.drawdown.max()) if len(cd) else 0,'avg_hold_h':float(td.hold_hours.mean()),'median_hold_h':float(td.hold_hours.median()),'range_trades':int((td.entry_mode=='RANGE').sum()),'trend_trades':int((td.entry_mode=='TREND').sum()),'exit_reasons':td.exit_reason.value_counts().to_dict()}


def monthly_folds(trades):
    if trades.empty:return []
    q=trades.copy(); q['month']=pd.to_datetime(q.entry_time,utc=True).dt.to_period('M').astype(str)
    out=[]
    for m,g in q.groupby('month'):
        pnl=g.pnl_cash.sum(); win=g.loc[g.pnl_cash>0,'pnl_cash'].sum(); loss=-g.loc[g.pnl_cash<0,'pnl_cash'].sum(); pf=float(win/loss) if loss>0 else math.inf
        out.append({'month':m,'trades':len(g),'pnl_cash':float(pnl),'pf':pf,'win_rate':float((g.pnl_cash>0).mean())})
    return out


def main():
    requested=[s for s in base.DEV_CANDIDATES if s!='MNTUSDT']
    d15,d1,d4,skipped=load_universe(requested)
    dev=[s for s in requested if s in d15 and s in d1]
    print('BUILD_FEATURES',len(dev),flush=True)
    feat={s:build_symbol(d15[s],d1[s]) for s in dev}
    td,cd,normal=simulate(feat,ONE_WAY_COST)
    std,scd,stress=simulate(feat,STRESS_ONE_WAY_COST)
    result={'version':VERSION,'period':[str(START),str(END_EXCLUSIVE)],'symbols':dev,'symbol_count':len(dev),'skipped':skipped,'architecture':{'scan_every':'15m','holding_minimum':None,'holding_target':None,'states':['RANGE_LONG','RANGE_SHORT','TREND_LONG','TREND_SHORT','FLAT'],'range_window_bars_15m':32,'max_positions':MAX_POSITIONS,'cost_one_way':ONE_WAY_COST,'stress_one_way':STRESS_ONE_WAY_COST},'normal':normal,'stress':stress,'monthly':monthly_folds(td),'outer_holdout_opened':False,'outer_holdout':base.OUTER_HOLDOUT,'note':'R14 is a deterministic causal baseline. All regime/support/resistance inputs use completed bars; rolling range levels are shifted so the current bar cannot define its own boundaries. Both entries and normal exits triggered by a completed 15m bar execute only at the next 15m open. Only a pre-existing fixed catastrophic stop may execute intrabar.'}
    Path('r14_result.json').write_text(json.dumps(result,indent=2,default=str))
    Path('r14_report.md').write_text('# V10 R14 Range/Breakout Engine\n\n```json\n'+json.dumps(result,indent=2,default=str)+'\n```\n')
    td.to_csv('r14_trades.csv',index=False); std.to_csv('r14_trades_stress.csv',index=False)
    cd.to_parquet('r14_equity.parquet',index=False,compression='zstd'); scd.to_parquet('r14_equity_stress.parquet',index=False,compression='zstd')
    print('===R14_RESULT_JSON==='); print(json.dumps(result,separators=(',',':'),default=str)); print('===END_R14_RESULT_JSON===')

if __name__=='__main__': main()