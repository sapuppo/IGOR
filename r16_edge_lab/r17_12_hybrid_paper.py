#!/usr/bin/env python3
"""Two segregated paper wallets, transactional recovery, fresh quotes only.

No account endpoints, credentials or real orders. Inputs are normalized captures;
strategy signals are supplied by the frozen history adapter, not capture contents.
"""
import copy,hashlib,json,math,sqlite3,time
from pathlib import Path

BAR=900000;HOUR=3600000
HERE=Path(__file__).resolve().parent
CONFIG=json.loads((HERE/'r17_12_paper_config.json').read_text())
ENGINES={'CORE':{'wallet':'LONG','side':1,'risk':.0075,'stop_atr':3.,'target_atr':6.,'hold_ms':30*4*HOUR,'maxpos':5},
         'REV1H':{'wallet':'LONG','side':1,'risk':.01,'stop_atr':3.,'target_atr':3.,'hold_ms':24*HOUR,'maxpos':5},
         'SHORT20D':{'wallet':'SHORT','side':-1,'stop_pct':.05,'target_pct':.10,'hold_ms':7*24*HOUR,'maxpos':4}}
class PaperError(ValueError):pass

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def finite(v):
    x=float(v)
    if not math.isfinite(x):raise PaperError('non-finite number')
    return x

def init_state(epoch):
    return {'epoch_ms':epoch,'last_server_ms':None,'last_boundary':None,'pending':{},'seen_signals':{},
      'shadow':{},'shadow_history':{'CORE':[],'REV1H':[]},'clusters':{},'funding_seen':{},
      'halted':False,'risk_gaps':0,'ambiguous_bars':0,'wallets':{k:{'initial':CONFIG['capital']*v['weight'],
      'cash':CONFIG['capital']*v['weight'],'realized':0.,'fees':0.,'funding':0.,'positions':{},'trades':[]}
      for k,v in CONFIG['wallets'].items()}}

def book(snapshot,symbol):
    q=snapshot['quotes'].get(symbol)
    if not q:raise PaperError('missing book '+symbol)
    bid,ask=finite(q['bid']),finite(q['ask']);age=snapshot['server_ms']-int(q['time_ms'])
    if bid<=0 or ask<bid or not 0<=age<=CONFIG['max_quote_age_ms'] or (ask-bid)/((ask+bid)/2)>CONFIG['max_spread']:
        raise PaperError('invalid/stale book '+symbol)
    return bid,ask

def mark_price(snapshot,symbol):
    row=snapshot.get('marks',{}).get(symbol)
    if not row:raise PaperError('official current mark missing '+symbol)
    price=finite(row['mark']);age=snapshot['server_ms']-int(row['time_ms'])
    if price<=0 or not 0<=age<=CONFIG['max_quote_age_ms']:raise PaperError('invalid/stale current mark '+symbol)
    return price

def values(w):
    eq=w['cash']+sum(p['side']*p['qty']*(p['mark']-p['entry']) for p in w['positions'].values())
    gross=sum(p['qty']*p['mark'] for p in w['positions'].values())
    reserve=sum(p['qty']*p['entry'] for p in w['positions'].values())
    risk=sum(p['qty']*(abs(p['entry']-p['stop'])+p['stop']*(CONFIG['fee']+CONFIG['slip'])) for p in w['positions'].values())
    return eq,gross,reserve,risk

def reconcile(s):
    for w in s['wallets'].values():
        expected=w['initial']+w['realized']-w['fees']+w['funding']
        if not math.isclose(expected,w['cash'],rel_tol=1e-10,abs_tol=1e-8):raise PaperError('cash does not reconcile')
        if not all(math.isfinite(x) for x in values(w)):raise PaperError('nonfinite account value')

def close_actual(w,key,ref,clock,reason,events):
    p=w['positions'].pop(key);fill=ref*(1-p['side']*CONFIG['slip']);fee=p['qty']*fill*CONFIG['fee']
    realized=p['side']*p['qty']*(fill-p['entry'])
    w['cash']+=realized-fee;w['realized']+=realized;w['fees']+=fee
    trade={**p,'exit_ms':clock,'exit':fill,'reason':reason,'net':realized-p['entry_fee']-fee+p['funding']}
    w['trades'].append(trade);events.append({'type':'EXIT','id':key,'engine':p['engine'],'fill':fill,'reason':reason})

def reason_for(p,snapshot):
    bid,ask=book(snapshot,p['symbol']);ref=bid if p['side']==1 else ask
    stop=ref<=p['stop'] if p['side']==1 else ref>=p['stop']
    target=ref>=p['target'] if p['side']==1 else ref<=p['target']
    row=snapshot.get('closed_15m',{}).get(p['symbol'])
    ambiguity=False
    if row and int(row['open_ms'])+BAR>p['entered_ms']:
        # Crossing may have happened before entry within its first bar; conservative
        # trigger is allowed, but execution reference always remains the current book.
        lo,hi=finite(row['low']),finite(row['high'])
        stop=stop or (lo<=p['stop'] if p['side']==1 else hi>=p['stop'])
        target=target or (hi>=p['target'] if p['side']==1 else lo<=p['target'])
        ambiguity=(stop and target) or int(row['open_ms'])<p['entered_ms']
    return ('STOP' if stop else 'TARGET' if target else 'TIME' if snapshot['server_ms']>=p['deadline'] else None),ref,ambiguity

def advance(old,snapshot,candidates,now_ms):
    s=copy.deepcopy(old);events=[]
    if snapshot.get('venue')!=CONFIG['venue']:raise PaperError('venue mismatch')
    clock=int(snapshot['server_ms']);boundary=int(snapshot['boundary_ms'])
    if boundary%BAR or boundary>clock:raise PaperError('invalid closed-bar boundary')
    if s['last_server_ms'] is not None and clock<=s['last_server_ms']:raise PaperError('out-of-order capture')
    eligible=(snapshot.get('class')=='TIMELY' and snapshot.get('status')=='COMPLETE'
              and 0<=now_ms-clock<=CONFIG['max_capture_age_ms'] and 0<=clock-boundary<=CONFIG['max_capture_age_ms'])
    if not eligible:
        s['risk_gaps']+=int(any(w['positions'] for w in s['wallets'].values()))
        events.append({'type':'SKIP','reason':'STALE_OR_BACKFILL'})
        # Historical imports do not advance the paper execution watermark.
        return s,events
    if s['last_boundary'] is not None and boundary-s['last_boundary']>BAR:
        s['risk_gaps']+=1;s['halted']=True;events.append({'type':'GAP','reason':'MISSING_OBSERVATION'})
    allpos=[p for w in s['wallets'].values() for p in w['positions'].values()]+list(s['shadow'].values())
    for p in allpos:book(snapshot,p['symbol']);mark_price(snapshot,p['symbol'])
    # Settle timestamped funding with the official event mark, deduplicated by event.
    for f in sorted(snapshot.get('funding',[]),key=lambda f:(int(f['time_ms']),f['symbol'])):
        when=int(f['time_ms']);symbol=f['symbol'];rate=finite(f['rate']);mark=finite(f['mark'])
        if not s['epoch_ms']<=when<=clock or mark<=0:raise PaperError('invalid funding time/mark')
        eventkey=f'{symbol}:{when}';signature=digest(f)
        if eventkey in s['funding_seen']:
            if s['funding_seen'][eventkey]!=signature:raise PaperError('funding revision')
            continue
        # Current state alone cannot settle late events for already closed positions.
        # Reject rather than silently losing a debit/credit after a prior close.
        if s['last_server_ms'] is not None and when<s['last_server_ms']:raise PaperError('late funding requires reconciliation')
        for w in s['wallets'].values():
            for p in w['positions'].values():
                if p['symbol']==symbol and p['entered_ms']<when:
                    amount=-p['side']*p['qty']*mark*rate
                    w['cash']+=amount;w['funding']+=amount;p['funding']+=amount
                    events.append({'type':'FUNDING','symbol':symbol,'amount':amount,'time_ms':when})
        for p in s['shadow'].values():
            if p['symbol']==symbol and p['entered_ms']<when:p['funding']-=mark*rate
        s['funding_seen'][eventkey]=signature
    funding_ok=int(snapshot.get('funding_complete_through_ms',-1))>=boundary
    if not funding_ok and allpos:raise PaperError('incomplete funding with open risk')
    # Observe existing positions and close at the newly observed executable side.
    for w in s['wallets'].values():
        for key,p in list(w['positions'].items()):
            bid,ask=book(snapshot,p['symbol']);p['mark']=mark_price(snapshot,p['symbol'])
            why,ref,amb=reason_for(p,snapshot)
            if why:
                s['ambiguous_bars']+=int(amb);close_actual(w,key,ref,clock,why,events)
    for key,p in list(s['shadow'].items()):
        why,ref,amb=reason_for(p,snapshot)
        if why:
            fill=ref*(1-CONFIG['slip']);net=fill-p['entry']-CONFIG['fee']*(fill+p['entry'])+p['funding']
            s['shadow_history'][p['engine']].append({'exit_ms':clock,'net_pct':net/p['entry']})
            del s['shadow'][key]
    for sig in candidates:
        e=sig['engine'];symbol=sig['symbol'];knowledge=int(sig['knowledge_ms'])
        if e not in ENGINES or knowledge!=boundary-1:raise PaperError('invalid/old/future strategy signal')
        if knowledge<s['epoch_ms']:continue
        key=f'{e}:{symbol}:{knowledge}'
        if key in s['seen_signals']:continue
        s['seen_signals'][key]=True
        if e=='REV1H':
            bucket=str(knowledge//(3*HOUR));count=s['clusters'].get(bucket,0)
            if count>=3:continue
            s['clusters'][bucket]=count+1
        s['pending'][key]={**sig,'id':key,'earliest_ms':boundary+BAR if e!='SHORT20D' else boundary}
        events.append({'type':'SIGNAL','id':key,'engine':e})
    month=time.gmtime(clock/1000);year=month.tm_year;mon=month.tm_mon-6
    while mon<=0:year-=1;mon+=12
    from datetime import datetime,timezone
    cutoff=int(datetime(year,mon,1,tzinfo=timezone.utc).timestamp()*1000)
    scores={}
    for e,h in s['shadow_history'].items():
        s['shadow_history'][e]=[x for x in h if x['exit_ms']>=cutoff]
        h=s['shadow_history'][e];scores[e]=sum(x['net_pct'] for x in h)/len(h) if h else 0.
    hot=sum(scores.values())>0 and sum(x>0 for x in scores.values())>=2
    for key,order in list(s['pending'].items()):
        if clock<order['earliest_ms']:continue
        del s['pending'][key]
        if clock-order['earliest_ms']>CONFIG['max_capture_age_ms']:
            events.append({'type':'REJECT','id':key,'reason':'MISSED_FILL_WINDOW'});continue
        e=order['engine'];cfg=ENGINES[e];side=cfg['side'];symbol=order['symbol']
        try:bid,ask=book(snapshot,symbol);current_mark=mark_price(snapshot,symbol)
        except PaperError:events.append({'type':'REJECT','id':key,'reason':'NO_FRESH_BOOK'});continue
        ref=ask if side==1 else bid;fill=ref*(1+side*CONFIG['slip'])
        if side==1:
            atr=finite(order['atr']);stop=fill-cfg['stop_atr']*atr;target=fill+cfg['target_atr']*atr
        else:stop=fill*(1+cfg['stop_pct']);target=fill*(1-cfg['target_pct'])
        if stop<=0:continue
        entry={'engine':e,'symbol':symbol,'side':side,'entry':fill,'mark':current_mark,'stop':stop,'target':target,
               'entered_ms':clock,'deadline':clock+cfg['hold_ms'],'funding':0.}
        if side==1:s['shadow'][key]=dict(entry)
        w=s['wallets'][cfg['wallet']];lim=CONFIG['wallets'][cfg['wallet']]
        if s['halted']:events.append({'type':'REJECT','id':key,'reason':'HALTED_AFTER_GAP'});continue
        if not funding_ok:events.append({'type':'REJECT','id':key,'reason':'FUNDING_COVERAGE'});continue
        if e in scores and scores[e]<0 and not(e=='CORE' and not hot):continue
        if len(w['positions'])>=lim['max_positions'] or sum(p['engine']==e for p in w['positions'].values())>=cfg['maxpos']:continue
        if any(p['symbol']==symbol for p in w['positions'].values()):continue
        eq,gross,reserve,risk=values(w);distance=abs(fill-stop)/fill
        if eq<=0:continue
        desired=min(eq*lim['cap'],eq*cfg['risk']/distance) if side==1 else eq*lim['cap']
        unitrisk=distance+(stop/fill)*(CONFIG['fee']+CONFIG['slip'])
        mark=current_mark
        entry_drag=CONFIG['fee']+side*(fill-mark)/fill
        cap=min(max(0.,w['cash']-reserve)/(1+CONFIG['fee']),
                max(0.,eq-gross)/(mark/fill+entry_drag),
                max(0.,eq*lim['max_stop_risk']-risk)/(unitrisk+lim['max_stop_risk']*entry_drag))
        notional=min(desired,cap)
        if notional<eq*.005:continue
        qty=notional/fill;fee=notional*CONFIG['fee'];entry.update(qty=qty,entry_fee=fee)
        w['cash']-=fee;w['fees']+=fee;w['positions'][key]=entry
        after_eq,after_gross,after_reserve,after_risk=values(w)
        if after_gross>after_eq+1e-7 or after_reserve>w['cash']+1e-7 or after_risk>lim['max_stop_risk']*after_eq+1e-7:
            raise PaperError('entry exceeds wallet risk/collateral')
        events.append({'type':'ENTRY','id':key,'engine':e,'wallet':cfg['wallet'],'fill':fill,'qty':qty})
    s['last_server_ms']=clock;s['last_boundary']=boundary
    reconcile(s)
    events.append({'type':'VALUATION','equity':sum(values(w)[0] for w in s['wallets'].values()),
                   'wallet_equity':{k:values(w)[0] for k,w in s['wallets'].items()},
                   'risk_gaps':s['risk_gaps'],'ambiguous_bars':s['ambiguous_bars'],'return_status':'PAPER_ESTIMATE_ONLY'})
    return s,events

class Journal:
    def __init__(self,path,epoch,source_hash):
        self.conn=sqlite3.connect(path,timeout=10)
        self.conn.execute('PRAGMA journal_mode=WAL');self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id=1), epoch INTEGER, source TEXT, cfg TEXT)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS decisions (seq INTEGER PRIMARY KEY, input_sha TEXT UNIQUE, previous_sha TEXT, sha TEXT, payload TEXT)')
        self.conn.execute('INSERT OR IGNORE INTO meta VALUES(1,?,?,?)',(epoch,source_hash,digest(CONFIG)))
        row=self.conn.execute('SELECT epoch,source,cfg FROM meta').fetchone()
        if row!=(epoch,source_hash,digest(CONFIG)):raise PaperError('epoch/code/config changed')
        self.conn.commit();self.epoch=epoch
    def latest(self):
        previous=None;state=init_state(self.epoch)
        for seq,input_sha,prev,sha,payload in self.conn.execute('SELECT * FROM decisions ORDER BY seq'):
            value=json.loads(payload)
            if prev!=previous or digest(value)!=sha or value['input_sha']!=input_sha:raise PaperError('journal tampered')
            previous=sha;state=value['state']
        return state,previous
    def process(self,snapshot,candidates,now_ms):
        input_sha=digest({'capture':snapshot,'signals':candidates})
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            state,prev=self.latest()
            found=self.conn.execute('SELECT payload FROM decisions WHERE input_sha=?',(input_sha,)).fetchone()
            if found:self.conn.rollback();return json.loads(found[0]),False
            state,events=advance(state,snapshot,candidates,now_ms)
            payload={'input_sha':input_sha,'previous_sha':prev,'state':state,'events':events}
            sha=digest(payload)
            self.conn.execute('INSERT INTO decisions(input_sha,previous_sha,sha,payload) VALUES(?,?,?,?)',(input_sha,prev,sha,canonical(payload)))
            self.conn.commit();return payload,True
        except Exception:self.conn.rollback();raise
