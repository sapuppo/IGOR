#!/usr/bin/env python3
"""Preregistered daily USD-M cross-sectional portfolio experiments. Research only."""
from collections import Counter
from datetime import datetime, timezone
import hashlib, json, math
from pathlib import Path

import numpy as np
import pandas as pd
from r17_candidate_signals import BAR_MS, iso
from run_r17_05_regime_rotation import load_verified, START, END

ROOT=Path(__file__).resolve().parent
PROTOCOL=ROOT/'r17_08_protocol.json'
FEE=.0006; SLIP=.0004; STOP=.05; DAY=6*BAR_MS
CAPITAL=10000.

def rank_daily(data,signal,days):
    """Use fully completed bars strictly earlier than the midnight signal."""
    last=signal-BAR_MS
    needed=[last-i*BAR_MS for i in range(days*6,-1,-1)]
    ranks=[]
    for sym,frame in data.items():
        if sym=='BTCUSDT': continue
        rows=frame.reindex(needed)
        if rows[['close','quote_volume']].isna().any().any(): continue
        med=frame.reindex([last-i*BAR_MS for i in range(41,-1,-1)])['quote_volume'].median()
        if not np.isfinite(med) or med<5_000_000: continue
        ranks.append((sym,float(rows['close'].iloc[-1]/rows['close'].iloc[0]-1)))
    ranks.sort(key=lambda x:(-x[1],x[0]))
    return ranks

def build_plans(data):
    plans={5:{},20:{}}; btc30={}
    dates=range(START,END,DAY)
    btc=data['BTCUSDT']
    for t in dates:
        prev=t-BAR_MS; history=btc.reindex([prev-i*BAR_MS for i in range(30*6,-1,-1)])
        btc30[t]=(None if history['close'].isna().any() else bool(float(history['close'].iloc[-1])>float(history['close'].mean())))
        for d in plans: plans[d][t]=rank_daily(data,t,d)
    return plans,btc30

def replay(spec,data,funding,plans,btc30):
    cash=CAPITAL; positions={}; trades=[]; daily=[]; stats=Counter()
    # Each key identifies the daily basket selected at 00:00 and filled at 04:00.
    selection={}; entered=0; skipped=0; peak=CAPITAL; maxdd=0.; maxgross=0.
    for t in range(START,END,BAR_MS):
        phase=(t-START)//BAR_MS % 6
        if phase==0:
            ranks=plans[spec['lookback_days']][t]
            longs=[s for s,_ in ranks[:spec['long']]]
            shorts=[s for s,_ in ranks[-spec['short']:] if s not in longs] if spec['short'] else []
            regime=btc30[t]
            if spec['regime']=='btc_30day':
                longs=longs if regime is True else []
                shorts=shorts if regime is False else []
            elif spec['regime']=='btc_positive_only' and regime is not True: longs=[]
            if len(ranks)<12 or (not longs and not shorts): selection[t+BAR_MS]=[];skipped+=1
            else: selection[t+BAR_MS]=[(s,1) for s in longs]+[(s,-1) for s in shorts]
        if phase==1:
            for sym in list(positions):
                if t not in data[sym].index: raise ValueError('active exit bar missing '+sym+' '+iso(t))
                close_position(sym,float(data[sym].at[t,'open']),t,'REBALANCE',cash,positions,trades,stats)
                cash=stats['cash']
            names=selection.pop(t,[])
            if names:
                # Fee reserve ensures 1x configuration does not use fee money as collateral.
                budget=cash*spec['gross']/(len(names)*(1+spec['gross']*FEE))
                for sym,side in names:
                    if t not in data[sym].index: raise ValueError('entry bar missing '+sym+' '+iso(t))
                    ref=float(data[sym].at[t,'open']); fill=ref*(1+side*SLIP)
                    qty=budget/fill; fee=budget*FEE; cash-=fee;stats['fees']+=fee
                    stats['slippage_proxy']+=qty*ref*SLIP
                    positions[sym]={'side':side,'entry':fill,'qty':qty,'entered':t,
                         'fee':fee,'funding':0.,'stop':fill*(1-side*STOP)}
                entered+=1
        for sym in list(positions):
            if t not in data[sym].index: raise ValueError('active bar missing '+sym+' '+iso(t))
            p=positions[sym];row=data[sym].loc[t];op=float(row['open']);cl=float(row['close'])
            side=p['side'];stop=p['stop']
            gap=(op<=stop if side==1 else op>=stop)
            hit=(float(row['low'])<=stop if side==1 else float(row['high'])>=stop)
            if gap:
                close_position(sym,op,t,'GAP',cash,positions,trades,stats);cash=stats['cash'];continue
            events=[(when,rate) for when,rate in funding[sym].get(t,[]) if when>=p['entered']]
            for when,rate in events:
                payment=-side*p['qty']*cl*rate
                if hit:
                    stats['ambiguous_funding_bars']+=1
                    if payment>0: continue
                p['funding']+=payment;cash+=payment;stats['funding']+=payment
            if hit:
                close_position(sym,stop,t+BAR_MS,'STOP',cash,positions,trades,stats);cash=stats['cash']
        if phase==5:
            equity=cash
            gross=0.
            for sym,p in positions.items():
                cl=float(data[sym].at[t,'close'])
                equity+=p['side']*p['qty']*(cl-p['entry'])
                gross+=p['qty']*cl
            if equity<=0: raise ValueError('portfolio bankruptcy')
            peak=max(peak,equity);maxdd=max(maxdd,1-equity/peak);maxgross=max(maxgross,gross/equity)
            daily.append({'timestamp':t+BAR_MS,'equity':equity,'gross':gross})
    for sym in list(positions):
        close_position(sym,float(data[sym].at[END-BAR_MS,'close']),END,'END',cash,positions,trades,stats);cash=stats['cash']
    assert len(daily)==(END-START)//DAY
    daily[-1]['equity']=cash
    assert not positions
    assert math.isclose(CAPITAL+sum(x['net'] for x in trades),cash,rel_tol=1e-9), 'independent trades vs cash'
    dates=pd.to_datetime([x['timestamp']-1 for x in daily],unit='ms',utc=True)
    series=pd.Series([x['equity'] for x in daily],index=dates)
    monthly=(series.resample('ME').last()/series.resample('ME').last().shift(fill_value=CAPITAL)-1)
    annual=(series.resample('YE').last()/series.resample('YE').last().shift(fill_value=CAPITAL)-1)
    # Recompute after final-day liquidation, which can slightly change the final drawdown.
    vals=np.array([CAPITAL]+[x['equity'] for x in daily]);maxdd=float((1-vals/np.maximum.accumulate(vals)).max())
    return {'id':spec['id'],'spec':spec,'return':cash/CAPITAL-1,
            'compound_monthly':(cash/CAPITAL)**(1/len(monthly))-1,
            'max_daily_mtm_drawdown':maxdd,'months_ge_20':int((monthly>=.2).sum()),
            'monthly':{str(k.to_period('M')):float(v) for k,v in monthly.items()},
            'annual':{str(k.year):float(v) for k,v in annual.items()},
            'entries':entered,'skipped_days':skipped,'trades':len(trades),
            'costs':{k:float(v) for k,v in stats.items() if k!='cash'},
            'max_daily_gross_to_equity':maxgross,
            'trade_sha256':hashlib.sha256(json.dumps(trades,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'daily_sha256':hashlib.sha256(json.dumps(daily,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'trades_detail':trades,'daily_detail':daily}

def close_position(sym,ref,when,reason,cash,positions,trades,stats):
    p=positions.pop(sym);side=p['side'];fill=ref*(1-side*SLIP)
    exit_fee=p['qty']*fill*FEE
    pnl=side*p['qty']*(fill-p['entry'])-exit_fee
    cash+=pnl
    stats['cash']=cash;stats['fees']+=exit_fee;stats['slippage_proxy']+=p['qty']*ref*SLIP
    trades.append({'symbol':sym,'side':side,'entry':p['entered'],'exit':when,'reason':reason,
                   'net':pnl-p['fee']+p['funding'],'funding':p['funding']})

def main():
    protocol=json.loads(PROTOCOL.read_text());out=ROOT/'r17_08_results';out.mkdir(exist_ok=True)
    data,funding=load_verified(ROOT/'usdm_history')
    print('Verified 152 files, planning signals',flush=True)
    plans,btc30=build_plans(data)
    reports={}
    for spec in protocol['variants']:
        print('RUN',spec['id'],flush=True)
        r=replay(spec,data,funding,plans,btc30)
        daily=r.pop('daily_detail');trades=r.pop('trades_detail')
        pd.DataFrame(daily).to_csv(out/(spec['id']+'_daily.csv'),index=False)
        pd.DataFrame(trades).to_csv(out/(spec['id']+'_trades.csv'),index=False)
        train=[v for k,v in r['monthly'].items() if k<'2025-01']
        train_daily=np.array([CAPITAL]+[x['equity'] for x in daily if x['timestamp']<int(pd.Timestamp('2025-01-01T00:00Z').timestamp()*1000)])
        r['train_2023_2024']={'return':float(np.prod(1+np.array(train))-1),
               'max_daily_mtm_drawdown':float((1-train_daily/np.maximum.accumulate(train_daily)).max())}
        (out/(spec['id']+'.json')).write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
        reports[spec['id']]=r
        print(json.dumps({k:r[k] for k in ['id','return','compound_monthly','max_daily_mtm_drawdown','months_ge_20','annual','trades']}),flush=True)
    elig=[r for r in reports.values() if r['train_2023_2024']['return']>0 and r['train_2023_2024']['max_daily_mtm_drawdown']<=.2]
    selected=max(elig,key=lambda x:(x['train_2023_2024']['return'],-x['train_2023_2024']['max_daily_mtm_drawdown']))['id'] if elig else None
    summary={'version':'R17.08','protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
             'selected_by_train':selected,'results':reports,'data_manifest_sha256':protocol['dataset_manifest_sha256'],
             'caveat':'RETROSPECTIVE_CONTAMINATED_MARK_PRICE_PROXY_NO_SPREAD_OR_EXCHANGE_ORDERBOOK'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print('COMPLETE selected',selected,flush=True)
if __name__=='__main__':main()
