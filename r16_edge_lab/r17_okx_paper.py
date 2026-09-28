#!/usr/bin/env python3
"""Append-only, public-data-only OKX 4h paper ledger. No order endpoints."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time

from r17_forward_capture import BAR_MS, CaptureError, canonical_bytes, number, verify_chain
from r17_okx_breakout_signal import signal
from r17_okx_public_capture import PublicOKX
from r17_okx_warmup import CUTOFF_MS, FIRST_COHORT

SCHEMA = 'IGOR_R17_04_OKX_PAPER_DECISION_V1'
START_CAPITAL = Decimal('10000')
FEE = Decimal('0.0005')
SLIPPAGE = Decimal('0.001')
STOP = Decimal('0.025')
TAKE = Decimal('0.05')
MAX_AGE_MS = 120000
WARMUP_SHA256 = 'e86a8f2d0b6e8079e45b8bf3e03f3650e69eb9a547380b8198dacf29d3f80fed'
WARMUP_SOURCE_SHA256 = '21165075a2ee651742c60370e5cbc66c7b0e9980dc8b48fd767be4e8038ae447'


def timestamp(iso):
    return int(datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()*1000)


def dec(v):
    return str(v)


def file_value(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if canonical_bytes(value) != raw:
        raise CaptureError('arquivo não canônico')
    return value, hashlib.sha256(raw).hexdigest()


def init_state():
    return {'cash':dec(START_CAPITAL),'positions':{},'last_closed':{},
            'funding':[],'closed_trades':0,'pnl_unverified':False,
            'funding_data_gaps':0,'risk_gaps':0,
            'last_capture_sha256':None,'last_decision_sha256':None}


def quote(row, clock):
    if row['status']!='COMPLETE' or not row['ticker']:
        return None
    q=row['ticker']
    if not (0 <= clock-int(q['ts']) <= 5000):
        return None
    bid,ask=number(q['bidPx'],'bid'),number(q['askPx'],'ask')
    if bid<=0 or ask<bid or (ask-bid)/((ask+bid)/2)>Decimal('0.002'):
        return None
    return bid,ask


def base_quantity(row, contracts, symbol):
    inst=row['instrument']
    if inst.get('ctValCcy') != symbol.split('-')[0] or inst.get('ctType')!='linear':
        raise CaptureError('valor do contrato não linear/base')
    return number(contracts,'contracts')*number(inst['ctVal'],'ctVal')*number(inst['ctMult'],'ctMult')


def funding_mark(client, symbol, event_ms):
    # after is an exclusive older-than cursor; start one minute after the event.
    rows=client.get('/api/v5/market/history-mark-price-candles',
                    {'instId':symbol,'bar':'1m','after':event_ms+60000,'limit':5})
    match=[r for r in rows if int(r[0])==event_ms//60000*60000 and len(r)>=6 and r[-1]=='1']
    if len(match)!=1:
        raise CaptureError('mark price 1m do funding ausente')
    high,low=number(match[0][2],'mark.high'),number(match[0][3],'mark.low')
    if low<=0 or high<low:
        raise CaptureError('mark price inválido')
    return high,low,match[0]


def settle_funding(state, current, client):
    events=[]
    state['pnl_unverified']=state['funding_data_gaps']>0
    for symbol,pos in state['positions'].items():
        row=current['observations'][symbol]
        if row['status']!='COMPLETE':
            state['funding_data_gaps']+=1
            state['pnl_unverified']=True
            events.append({'type':'FUNDING_DATA_GAP','symbol':symbol})
            continue
        for fund in row['funding']:
            when=int(fund['fundingTime'])
            if when < pos['entry_time_ms']:
                continue
            if any(e['symbol']==symbol and e['time_ms']==when for e in state['funding']):
                continue
            rate=number(fund['realizedRate'],'realizedRate')
            event={'symbol':symbol,'time_ms':when,'rate':dec(rate),
                   'base_quantity':pos['base_quantity'],'side':pos['side'],
                   'status':'UNVERIFIED'}
            state['funding'].append(event)
    for event in state['funding']:
        if event['status']!='UNVERIFIED':
            continue
        if timestamp(current['end_exclusive_utc'])-event['time_ms']>2*BAR_MS:
            state['pnl_unverified']=True
            continue
        try:
            high,low,candle=funding_mark(client,event['symbol'],event['time_ms'])
        except CaptureError:
            state['pnl_unverified']=True
            continue
        qty=number(event['base_quantity'],'quantity')
        rate=number(event['rate'],'rate')
        sign=Decimal('-1') if event['side']=='BUY' else Decimal('1')
        amount=min(sign*qty*rate*high,sign*qty*rate*low)
        event.update(status='ESTIMATED_STRESS',amount_usdt=dec(amount),
                     mark_high=dec(high),mark_low=dec(low),mark_candle=candle)
        state['cash']=dec(number(state['cash'],'cash')+amount)
        events.append({'type':'FUNDING_STRESS_ESTIMATE','symbol':event['symbol'],
                       'time_ms':event['time_ms'],'amount_usdt':dec(amount)})
    if any(e['status']=='UNVERIFIED' for e in state['funding']):
        state['pnl_unverified']=True
    return events


def value(state,current):
    equity=number(state['cash'],'cash')
    gross=Decimal('0')
    for symbol,pos in state['positions'].items():
        book=quote(current['observations'][symbol],int(current['server_time_ms']))
        if book is None:
            return None,None
        bid,ask=book
        px=bid if pos['side']=='BUY' else ask
        qty=number(pos['base_quantity'],'quantity')
        direction=1 if pos['side']=='BUY' else -1
        equity+=direction*qty*(px-number(pos['entry_fill'],'entry_fill'))-qty*px*(FEE+SLIPPAGE)
        gross+=qty*px
    return equity,gross


def step(previous,warmup,history,current,now_ms,client,enabled=False):
    state=json.loads(json.dumps(previous))
    decisions=[]
    clock=int(current['server_time_ms'])
    boundary=timestamp(current['end_exclusive_utc'])
    eligible=(enabled and current['status']=='COMPLETE'
              and current['snapshot_class']=='TIMELY_OBSERVATION'
              and 0 <= now_ms-clock <= MAX_AGE_MS)
    if not eligible:
        if state['positions']:
            state['risk_gaps']+=1
            state['funding_data_gaps']+=1
            state['pnl_unverified']=True
        decisions.append({'type':'SKIP','reason':'NOT_TIMELY_OR_UNVERIFIED'})
        return state,decisions
    decisions.extend(settle_funding(state,current,client))
    for symbol,pos in list(state['positions'].items()):
        row=current['observations'][symbol]
        book=quote(row,clock)
        if book is None or len(row['klines'])!=1 or int(row['klines'][0][0])!=boundary-BAR_MS:
            state['risk_gaps']+=1
            decisions.append({'type':'HOLD_NO_FRESH_EXIT','symbol':symbol})
            continue
        close=number(row['klines'][-1][4],'close')
        entry=number(pos['entry_fill'],'entry')
        direction=1 if pos['side']=='BUY' else -1
        move=direction*(close/entry-1)
        age=boundary-pos['entry_boundary_ms']
        why='STOP' if move<=-STOP else 'TAKE' if move>=TAKE else 'TIME' if age>=48*3600000 else None
        if why is None:
            continue
        bid,ask=book
        exit_px=(bid*(1-SLIPPAGE) if direction==1 else ask*(1+SLIPPAGE))
        qty=number(pos['base_quantity'],'qty')
        net=direction*qty*(exit_px-entry)-qty*exit_px*FEE
        state['cash']=dec(number(state['cash'],'cash')+net)
        state['closed_trades']+=1
        state['last_closed'][symbol]=boundary
        del state['positions'][symbol]
        decisions.append({'type':'EXIT','symbol':symbol,'reason':why,'fill':dec(exit_px),
                          'pnl_before_entry_fee_and_funding_usdt':dec(net)})
    equity,gross=value(state,current)
    if equity is None or equity<=0 or state['pnl_unverified']:
        decisions.append({'type':'SKIP_ENTRY','reason':'RISK_OR_FUNDING_UNVERIFIED'})
        return state,decisions
    past=[{'universe':current['universe'],'observations':warmup['observations'],
           'server_time_ms':CUTOFF_MS-1},*history,current]
    blocked=[s for s,t in state['last_closed'].items() if boundary-t<6*BAR_MS]
    candidate=signal(past,current,dec(equity),state['positions'].keys(),blocked)
    decisions.append({'type':'SIGNAL','status':candidate['status'],
                      'candidate_symbols':[x['symbol'] for x in candidate['candidates']]})
    for item in candidate['candidates']:
        symbol=item['symbol']
        if symbol in state['positions'] or len(state['positions'])>=4:
            continue
        if boundary-state['last_closed'].get(symbol,-10**20)<6*BAR_MS:
            continue
        row=current['observations'][symbol]
        book=quote(row,clock)
        if book is None or int(item['quote_time_ms'])!=int(row['ticker']['ts']):
            continue
        contracts=number(item['contracts'],'contracts')
        qty=base_quantity(row,contracts,symbol)
        bid,ask=book
        entry=(ask*(1+SLIPPAGE) if item['side']=='BUY' else bid*(1-SLIPPAGE))
        notional=qty*entry
        if notional>equity*Decimal('0.10') or gross+notional>equity*Decimal('0.40'):
            continue
        fee=notional*FEE
        if number(state['cash'],'cash')<notional+fee:
            continue
        state['cash']=dec(number(state['cash'],'cash')-fee)
        state['positions'][symbol]={'side':item['side'],'contracts':dec(contracts),
              'base_quantity':dec(qty),'entry_fill':dec(entry),'entry_time_ms':clock,
              'entry_boundary_ms':boundary,'entry_fee_usdt':dec(fee)}
        gross+=notional
        decisions.append({'type':'ENTRY','symbol':symbol,'side':item['side'],
                          'contracts':dec(contracts),'fill':dec(entry),'fee_stress_usdt':dec(fee)})
    return state,decisions


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',required=True)
    p.add_argument('--out-dir',required=True)
    p.add_argument('--event-name',required=True)
    args=p.parse_args()
    archive=Path(args.archive)
    verify_chain(archive)
    captures=sorted(archive.glob('capture-*.json'))
    warmups=list(archive.glob('warmup-20260928T120000Z-*.json'))
    if not captures or len(warmups)!=1 or captures[0].name!=FIRST_COHORT:
        raise CaptureError('fonte inicial ou warmup ausente')
    warmup,whash=file_value(warmups[0])
    first,first_hash=file_value(captures[0])
    if (whash!=WARMUP_SHA256 or warmup['source_sha256']!=WARMUP_SOURCE_SHA256
            or warmup['status']!='COMPLETE' or warmup['universe']!=first['universe']
            or warmup['first_capture_file_sha256']!=first_hash
            or warmup['cutoff_exclusive_utc']!='2026-09-28T12:00:00Z'
            or not warmups[0].name.endswith(whash[:16]+'.json')):
        raise CaptureError('warmup incorreto ou alterado')
    root=Path(args.out_dir)
    root.mkdir(parents=True,exist_ok=True)
    old=sorted(root.glob('decision-*.json'))
    prior=init_state()
    for path in old:
        item,digest=file_value(path)
        if item['schema']!=SCHEMA or item['previous_decision_sha256']!=prior['last_decision_sha256']:
            raise CaptureError('cadeia paper divergente')
        prior=item['state']
        prior['last_decision_sha256']=digest
    found=prior['last_capture_sha256'] is None
    if not found:
        found=any(file_value(f)[1]==prior['last_capture_sha256'] for f in captures)
    if not found:
        raise CaptureError('snapshot do estado paper removido')
    current_time=int(time.time()*1000)
    past=[]
    resume=prior['last_capture_sha256'] is None
    for file in captures:
        capture,digest=file_value(file)
        if digest==prior['last_capture_sha256'] and not resume:
            resume=True
            past.append(capture)
            continue
        if not resume:
            past.append(capture)
            continue
        state,events=step(prior,warmup,past,capture,current_time,PublicOKX(),
                          enabled=args.event_name=='schedule')
        state['last_capture_sha256']=digest
        result={'schema':SCHEMA,'strategy':'R17-OKX-DB24-BTC48-CV1',
                'capture_sha256':digest,'capture_file':file.name,
                'warmup_sha256':whash,'previous_decision_sha256':prior['last_decision_sha256'],
                'processed_at_ms':current_time,'event_name':args.event_name,
                'events':events,'state':{k:v for k,v in state.items() if k!='last_decision_sha256'},
                'pnl_label':'STRESS_PAPER_UNVERIFIED', 'live':False}
        raw=canonical_bytes(result)
        paper_hash=hashlib.sha256(raw).hexdigest()
        name=f"decision-{capture['server_time_ms']}-{paper_hash[:16]}.json"
        with (root/name).open('xb') as out:
            out.write(raw)
        prior=state
        prior['last_decision_sha256']=paper_hash
        past.append(capture)
        print(json.dumps({'file':name,'events':events,'closed_trades':state['closed_trades']}))


if __name__=='__main__':
    main()
