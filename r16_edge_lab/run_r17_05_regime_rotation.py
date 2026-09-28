#!/usr/bin/env python3
"""Single retrospective R17-RR7-BTC30-W1 diagnostic; no account or orders."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from r17_candidate_signals import BAR_MS, iso, verified_history

START = int(datetime(2021, 1, 1, tzinfo=timezone.utc).timestamp()*1000)
END = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()*1000)
FEE = .0006
SLIP = .0004
WEIGHT = .15
STOP = .05
ROOT_HASH = 'a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041'


def load_verified(root):
    root=Path(root)
    data=verified_history(root)
    manifest=json.loads((root/'manifest.json').read_text())
    funding={}
    for entry in manifest['files']:
        if entry['kind']!='funding' or entry['symbol'] not in data:
            continue
        raw=(root/'funding'/f"{entry['symbol']}.csv.gz").read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('funding hash mismatch '+entry['symbol'])
        events=defaultdict(list)
        with gzip.open(root/'funding'/f"{entry['symbol']}.csv.gz",'rt') as handle:
            frame=pd.read_csv(handle)
        if frame['fundingTime'].duplicated().any() or not frame['fundingTime'].is_monotonic_increasing:
            raise ValueError('funding timestamps malformed '+entry['symbol'])
        for x in frame.itertuples():
            if START<=x.fundingTime<END:
                events[x.fundingTime//BAR_MS*BAR_MS].append((int(x.fundingTime),float(x.fundingRate)))
        funding[entry['symbol']]=events
    if len(funding)!=38 or len(data)!=38:
        raise ValueError('incomplete fixed cohort')
    return data,funding


def rank(data,signal_at):
    last_open=signal_at-BAR_MS
    wanted=[last_open-k*BAR_MS for k in range(179,-1,-1)]
    btc=data['BTCUSDT'].reindex(wanted)
    if btc['close'].isna().any():
        return None,[]
    last=float(btc['close'].iloc[-1]);mean=float(btc['close'].mean())
    side=1 if last>mean else -1 if last<mean else None
    if side is None:
        return None,[]
    ranked=[]
    for symbol,frame in data.items():
        if symbol=='BTCUSDT':
            continue
        look=frame.reindex(wanted)
        if look[['close','quote_volume']].isna().any().any():
            continue
        if float(look['quote_volume'].iloc[-42:].median())<5_000_000:
            continue
        # Exactly 42 completed 4h returns; closes -43 and -1.
        score=float(look['close'].iloc[-1]/look['close'].iloc[-43]-1)
        if side*score>0:
            ranked.append((symbol,score))
    if len(ranked)<4:
        return side,[]
    ranked.sort(key=lambda x:((-x[1] if side==1 else x[1]),x[0]))
    return side,[s for s,_ in ranked[:4]]


def replay(data,funding):
    cash=10000.
    positions={}
    daily=[{'utc':iso(START),'equity':cash}]
    trades=[]
    stats=defaultdict(float)
    entry_weeks=0
    skipped_weeks=0

    def exit_one(symbol,reference,stamp,reason):
        nonlocal cash
        pos=positions.pop(symbol)
        side=pos['side'];fill=reference*(1-side*SLIP)
        fee=abs(pos['qty']*fill)*FEE
        cash+=side*pos['qty']*(fill-pos['entry'])-fee
        stats['commissions']+=fee
        stats['slippage_proxy']+=abs(pos['qty']*reference)*SLIP
        trades.append({'symbol':symbol,'side':side,'entry_utc':iso(pos['entered']),
                       'exit_utc':iso(stamp),'reason':reason,
                       'net_trade_usdt':side*pos['qty']*(fill-pos['entry'])-fee-pos['entry_fee']+pos['funding'],
                       'funding_proxy_usdt':pos['funding']})

    timeline=sorted(x for x in data['BTCUSDT'].index if START<=x<END)
    for t in timeline:
        dt=datetime.fromtimestamp(t/1000,timezone.utc)
        if dt.weekday()==0 and dt.hour==4:
            for symbol in list(positions):
                if t not in data[symbol].index:
                    raise ValueError('active exit bar missing '+symbol)
                exit_one(symbol,float(data[symbol].at[t,'open']),t,'WEEK')
            side,picks=rank(data,t-BAR_MS)
            if len(picks)==4 and all(t in data[s].index for s in picks) and cash>0:
                # Four entry fees are reserved before determining each notional.
                budget=cash*WEIGHT/(1+4*WEIGHT*FEE)
                for symbol in picks:
                    reference=float(data[symbol].at[t,'open'])
                    fill=reference*(1+side*SLIP)
                    qty=budget/fill
                    entry_fee=budget*FEE
                    cash-=entry_fee
                    stats['commissions']+=entry_fee
                    stats['slippage_proxy']+=qty*reference*SLIP
                    positions[symbol]={'side':side,'qty':qty,'entry':fill,
                      'entry_fee':entry_fee,'entered':t,'stop':fill*(1-side*STOP),'funding':0.}
                entry_weeks+=1
            else:
                skipped_weeks+=1
        for symbol,pos in list(positions.items()):
            if t not in data[symbol].index:
                raise ValueError('active bar missing '+symbol+' '+iso(t))
            row=data[symbol].loc[t]
            lo,hi,op,cl=(float(row[x]) for x in ('low','high','open','close'))
            stop=pos['stop']
            hit=lo<=stop if pos['side']==1 else hi>=stop
            events=[(when,rate) for when,rate in funding[symbol].get(t,[]) if when>pos['entered']]
            if hit and events:
                stats['ambiguous_stop_funding_bars']+=1
            for when,rate in events:
                # Close is a proxy for unavailable official mark, not a tradeable fill.
                payment=-pos['side']*pos['qty']*cl*rate
                stats['ambiguous_funding_abs_upper']+=abs(payment) if hit else 0.
                if hit and payment>0:
                    continue # Favorable funding could settle after the stop.
                pos['funding']+=payment
                cash+=payment
                stats['funding_proxy']+=payment
            if hit:
                reference=min(op,stop) if pos['side']==1 else max(op,stop)
                exit_one(symbol,reference,t if reference!=stop else t+BAR_MS,'STOP')
        if (t+BAR_MS)%(24*60*60*1000)==0:
            equity=cash
            gross=0.
            for symbol,pos in positions.items():
                if t not in data[symbol].index:
                    raise ValueError('active MTM bar missing '+symbol)
                mark=float(data[symbol].at[t,'close'])
                equity+=pos['side']*pos['qty']*(mark-pos['entry'])
                gross+=abs(pos['qty']*mark)
            daily.append({'utc':iso(t+BAR_MS),'equity':equity,'gross':gross})
    for symbol,pos in list(positions.items()):
        exit_one(symbol,float(data[symbol].at[timeline[-1],'close']),END,'END')
    daily[-1]['equity']=cash
    if any(x['equity']<=0 for x in daily):
        raise ValueError('bankrupt or invalid MTM')
    month_end={}
    for d in daily[1:]:
        when=datetime.fromisoformat(d['utc'].replace('Z','+00:00'))
        day=(when-pd.Timedelta(milliseconds=1)).strftime('%Y-%m')
        month_end[day]=d['equity']
    prev=10000.;monthly={}
    for month,value in month_end.items():
        monthly[month]=value/prev-1
        prev=value
    yearly={};begin=10000.
    for year in sorted(set(k[:4] for k in monthly)):
        end=month_end[[k for k in month_end if k.startswith(year)][-1]]
        yearly[year]=end/begin-1
        begin=end
    peak=10000.;drawdown=0.
    for d in daily:
        peak=max(peak,d['equity']);drawdown=max(drawdown,1-d['equity']/peak)
    utilization=sum(d.get('gross',0)/d['equity'] for d in daily if 'gross' in d)/max(1,len(daily)-1)
    return {'strategy':'R17-RR7-BTC30-W1','data_sha256':ROOT_HASH,
            'period':['2021-01-01','2026-07-01 exclusive'],
            'interpretation':'RETROSPECTIVE_CONTAMINATED_FUNDING_MARK_PROXY_SPREAD_UNKNOWN',
            'final_cash':cash,'return':cash/10000-1,'monthly':monthly,'annual':yearly,
            'best_month':max(monthly.values()),'worst_month':min(monthly.values()),
            'months_at_least_20pct':sum(v>=.2 for v in monthly.values()),
            'months':len(monthly),'max_daily_drawdown':drawdown,
            'average_daily_gross_exposure':utilization,'closed_trades':len(trades),
            'entry_weeks':entry_weeks,'skipped_weeks':skipped_weeks,
            'costs_and_ambiguity':dict(stats),'trades':trades,
            'oos_validated':False,'live':False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',required=True)
    p.add_argument('--out',required=True)
    args=p.parse_args()
    result=replay(*load_verified(args.root))
    Path(args.out).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('monthly','annual','trades')}))


if __name__=='__main__':
    main()
