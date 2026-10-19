#!/usr/bin/env python3
"""Audited research engine: explicit funding boundary, complete terminal DD, risk sizing and loss cooldown."""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,json,math
import numpy as np,pandas as pd
from r17_candidate_signals import BAR_MS, iso
from run_r17_05_regime_rotation import load_verified,START,END
ROOT=Path(__file__).resolve().parent
PROTOCOL=ROOT/'r17_10_protocol.json';OUT=ROOT/'r17_10_results'
FEE=.0006;SLIP=.0004;STOP=.05;TARGET=.10;CAPITAL=10000.;DAY=BAR_MS*6

def precompute(data,variants):
    btc=data['BTCUSDT']; btc_ma=btc['close'].rolling(180,min_periods=180).mean()
    btc_side=pd.Series(np.where(btc['close']>btc_ma,1,-1),index=btc.index)
    signals={}
    for n in set(v['lookback_bars'] for v in variants):
        for side in (1,-1):
            events=defaultdict(list)
            for sym,frame in data.items():
                liq=frame['quote_volume'].rolling(42,min_periods=42).median()>=5_000_000
                prior=(frame['high'].shift(1).rolling(n,min_periods=n).max() if side==1
                       else frame['low'].shift(1).rolling(n,min_periods=n).min())
                ratio=frame['close']/prior
                mask=liq & ((ratio>1) if side==1 else (ratio<1))
                for ts,value in ratio[mask].items():
                    entry=int(ts)+BAR_MS
                    if START<=entry<END:
                        # Strongest penetration first; deterministic tie on symbol.
                        events[entry].append((sym,side,abs(float(value)-1)))
            for t in events:events[t].sort(key=lambda x:(-x[2],x[0]))
            signals[n,side]=events
    return signals,btc_side

def replay(v,data,funding,signals,btc_side):
    cash=CAPITAL;pos={};trades=[];cooldown={};seen_trades=0;daily=[];stats=Counter();peak=CAPITAL;maxdd=0.;maxgross=0.
    sides=([1,-1] if v['direction']=='both' else ([1] if v['direction']=='long' else [-1]))
    eventmaps=[signals[v['lookback_bars'],side] for side in sides]
    for t in range(START,END,BAR_MS):
        # Boundary convention: pre-existing positions pay t funding before open exits;
        # new positions at t enter just after settlement. Price is open proxy, NOT mark.
        for sym,p in pos.items():
            for when,rate in funding[sym].get(t,[]):
                if when==t:
                    pay=-p['side']*p['qty']*float(data[sym].at[t,'open'])*rate
                    p['funding']+=pay;cash+=pay;stats['funding']+=pay
        for tr in trades[seen_trades:]:
            if tr['net']<0:cooldown[tr['symbol']]=tr['exit']+v.get('cooldown_bars',0)*BAR_MS
        seen_trades=len(trades)
        # Exit at the new bar's open if maximum holding time is reached.
        for sym in list(pos):
            p=pos[sym]
            if t not in data[sym].index:raise ValueError('missing active exit '+sym+' '+iso(t))
            if t-p['entered']>=v['hold_bars']*BAR_MS:
                cash=exit_position(sym,float(data[sym].at[t,'open']),t,'TIME',cash,pos,trades,stats)
        for tr in trades[seen_trades:]:
            if tr['net']<0:cooldown[tr['symbol']]=tr['exit']+v.get('cooldown_bars',0)*BAR_MS
        seen_trades=len(trades)
        eligible=[]
        for ev in eventmaps:eligible.extend(ev.get(t,[]))
        eligible.sort(key=lambda x:(-x[2],x[0]))
        for sym,side,strength in eligible:
            if len(pos)>=4:break
            if sym in pos:continue
            if t<cooldown.get(sym,0):stats["cooldown_skips"]+=1;continue
            if t not in data[sym].index:continue
            if v['btc_gate']:
                signal_t=t-BAR_MS
                if signal_t not in btc_side.index or btc_side.at[signal_t]!=side:continue
            equity=cash;gross=0.
            for k,p in pos.items():
                if t not in data[k].index:raise ValueError('missing active mark '+k+' '+iso(t))
                ref=float(data[k].at[t,'open'])
                equity+=p['side']*p['qty']*(ref-p['entry']);gross+=p['qty']*ref
            if equity<=0:raise ValueError('bankrupt before entry')
            stop_fraction=STOP
            if v.get('atr_stop'):
                if t-BAR_MS not in data[sym].index:stats['missing_atr_skips']+=1;continue
                atr=float(data[sym].at[t-BAR_MS,'atr'])
                if not np.isfinite(atr) or atr<=0:stats['missing_atr_skips']+=1;continue
                ref=float(data[sym].at[t,'open'])
                stop_fraction=max(.02,min(.12,v['atr_stop']*atr/ref))
            weight=v.get('max_weight',.25)
            if 'risk_fraction' in v:weight=min(weight,v['risk_fraction']/(stop_fraction+2*(FEE+SLIP)))
            notional=min(weight*equity,max(0.,v.get('max_exposure',1.)*equity-gross)/(1+FEE))
            if notional<equity*.005:continue
            ref=float(data[sym].at[t,'open']);fill=ref*(1+side*SLIP)
            qty=notional/fill;fee=notional*FEE;cash-=fee
            stats['fees']+=fee;stats['slippage_proxy']+=qty*ref*SLIP;stats['entries']+=1
            pos[sym]={'side':side,'qty':qty,'entry':fill,'entry_fee':fee,'entered':t,'funding':0.,
                      'stop':fill*(1-side*stop_fraction),'target':(float('inf') if side==1 else float('-inf')) if 'trail_atr' in v else fill*(1+side*TARGET)}
        for sym in list(pos):
            if t not in data[sym].index:raise ValueError('missing active bar '+sym+' '+iso(t))
            p=pos[sym];side=p['side'];row=data[sym].loc[t]
            op=float(row['open']);lo=float(row['low']);hi=float(row['high']);cl=float(row['close'])
            gapstop=(op<=p['stop'] if side==1 else op>=p['stop'])
            gaptarget=(op>=p['target'] if side==1 else op<=p['target'])
            if gapstop or gaptarget:
                cash=exit_position(sym,op,t,'GAP_STOP' if gapstop else 'GAP_TARGET',cash,pos,trades,stats)
                continue
            stophit=(lo<=p['stop'] if side==1 else hi>=p['stop'])
            targethit=(hi>=p['target'] if side==1 else lo<=p['target'])
            if stophit and targethit:stats['ambiguous_stop_target_bars']+=1
            events=[(when,rate) for when,rate in funding[sym].get(t,[]) if when>t and when>=p['entered']]
            for when,rate in events:
                pay=-side*p['qty']*cl*rate
                if stophit or targethit:
                    stats['ambiguous_funding_bars']+=1
                    if pay>0:continue
                p['funding']+=pay;cash+=pay;stats['funding']+=pay
            if stophit or targethit:
                reason='STOP' if stophit else 'TARGET'
                cash=exit_position(sym,p['stop'] if stophit else p['target'],t+BAR_MS,reason,cash,pos,trades,stats)
            elif 'trail_atr' in v:
                # Today's close/ATR become known only here; stop is used next bar.
                atr=float(row['atr'])
                if not np.isfinite(atr) or atr<=0:raise ValueError('bad trailing ATR')
                old_stop=p['stop'];candidate=cl-side*v['trail_atr']*atr
                p['stop']=max(old_stop,candidate) if side==1 else min(old_stop,candidate)
                assert side*(p['stop']-old_stop)>=0
        equity=cash;gross=0.
        for sym,p in pos.items():
            cl=float(data[sym].at[t,'close']);equity+=p['side']*p['qty']*(cl-p['entry']);gross+=p['qty']*cl
        if equity<=0:raise ValueError('bankrupt during mark')
        peak=max(peak,equity);maxdd=max(maxdd,1-equity/peak);maxgross=max(maxgross,gross/equity)
        if (t+BAR_MS)%DAY==0:daily.append({'timestamp':t+BAR_MS,'equity':equity,'gross':gross})
    for sym in list(pos):
        cash=exit_position(sym,float(data[sym].at[END-BAR_MS,'close']),END,'END',cash,pos,trades,stats)
    assert len(daily)==(END-START)//DAY
    daily[-1]['equity']=cash
    daily[-1]['gross']=0.
    maxdd=max(maxdd,1-cash/peak)
    assert math.isclose(CAPITAL+sum(x['net'] for x in trades),cash,rel_tol=1e-9)
    d=pd.Series([x['equity'] for x in daily],index=pd.to_datetime([x['timestamp']-1 for x in daily],unit='ms',utc=True))
    m=d.resample('ME').last();y=d.resample('YE').last()
    mr=m/m.shift(fill_value=CAPITAL)-1;yr=y/y.shift(fill_value=CAPITAL)-1
    return {'id':v['id'],'spec':v,'return':cash/CAPITAL-1,'compound_monthly':(cash/CAPITAL)**(1/len(m))-1,
            'max_4h_mtm_drawdown':maxdd,'max_gross_equity':maxgross,'monthly':{str(k.to_period('M')):float(x) for k,x in mr.items()},
            'annual':{str(k.year):float(x) for k,x in yr.items()},'months_ge_20':int((mr>=.2).sum()),
            'trades':len(trades),'costs':dict(stats),
            'trade_sha256':hashlib.sha256(json.dumps(trades,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'daily_sha256':hashlib.sha256(json.dumps(daily,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'trade_details':trades,'daily_details':daily}

def exit_position(sym,ref,when,reason,cash,pos,trades,stats):
    p=pos.pop(sym);side=p['side'];fill=ref*(1-side*SLIP);fee=p['qty']*fill*FEE
    realized=side*p['qty']*(fill-p['entry'])-fee
    cash+=realized;stats['fees']+=fee;stats['slippage_proxy']+=p['qty']*ref*SLIP;stats['exit_'+reason]+=1
    trades.append({'symbol':sym,'side':side,'entry':p['entered'],'exit':when,'reason':reason,
                   'net':realized-p['entry_fee']+p['funding'],'funding':p['funding'],
                   'entry_fill':p['entry'],'exit_fill':fill,'qty':p['qty'],'entry_fee':p['entry_fee'],'exit_fee':fee,
                   'price_pnl':side*p['qty']*(fill-p['entry'])})
    return cash
