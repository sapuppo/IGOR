#!/usr/bin/env python3
"""Whitelisted public GET-only Binance USD-M feed; credentials are not supported."""
import argparse,hashlib,json,time,urllib.parse,urllib.request
from pathlib import Path
from r17_12_hybrid_paper import BAR,PaperError,CONFIG,canonical
INTERVAL={'15m':BAR,'1h':BAR*4,'4h':BAR*16}
COLS=['open_time','open','high','low','close','volume','quote_volume']
ALLOWED={'/fapi/v1/time','/fapi/v1/klines','/fapi/v1/fundingRate','/fapi/v1/ticker/bookTicker','/fapi/v1/premiumIndex'}
class PublicBinance:
    def __init__(self,timeout=8):self.timeout=timeout;self.last_call=0.
    def get(self,path,params=None):
        if path not in ALLOWED:raise PaperError('non-public/non-whitelisted endpoint')
        # Bound maximum 1500-kline request weight even during long backfills.
        delay=.3-(time.monotonic()-self.last_call)
        if delay>0:time.sleep(delay)
        self.last_call=time.monotonic()
        u='https://fapi.binance.com'+path+('?' + urllib.parse.urlencode(params) if params else '')
        req=urllib.request.Request(u,headers={'User-Agent':'IGOR-R17.12-PUBLIC-PAPER/1.0'})
        with urllib.request.urlopen(req,timeout=self.timeout) as r:
            raw=r.read()
            if len(raw)>8_000_000:raise PaperError('oversized API response')
        value=json.loads(raw)
        if isinstance(value,dict) and 'code' in value:raise PaperError('API response error '+str(value['code']))
        return value

def normalize(rows,interval,boundary):
    out=[]
    for r in rows:
        if not isinstance(r,list) or len(r)<8:raise PaperError('malformed candle response')
        if int(r[0])+INTERVAL[interval]<=boundary:
            out.append(dict(zip(COLS,[int(r[0])]+[float(x) for x in r[1:6]]+[float(r[7])])) )
    out.sort(key=lambda r:r['open_time'])
    if len({x['open_time'] for x in out})!=len(out):raise PaperError('duplicate source candle')
    return out

def universe(root):
    value=json.loads((Path(root)/'manifest.json').read_text())
    if value['dataset_manifest_sha256']!=CONFIG['dataset_manifest_sha256']:raise PaperError('wrong universe manifest')
    return sorted(x['symbol'] for x in value['symbols'] if x['eligible'])

def capture(client,symbols,epoch,since,clock=None):
    local=lambda:int(time.time()*1000) if clock is None else clock
    server=int(client.get('/fapi/v1/time')['serverTime']);began=local()
    if abs(server-began)>5000:raise PaperError('server/local clock mismatch')
    boundary=server//BAR*BAR
    bars={};funds=[]
    for s in symbols:
        if local()-began>80000:raise PaperError('capture exceeded 80s budget')
        bars[s]={iv:normalize(client.get('/fapi/v1/klines',{'symbol':s,'interval':iv,'limit':3}),iv,boundary) for iv in INTERVAL}
        start=max(epoch,since)
        rows=client.get('/fapi/v1/fundingRate',{'symbol':s,'startTime':start,'endTime':server,'limit':1000})
        if len(rows)>=1000:raise PaperError('funding response truncated; reconcile before paper')
        for f in rows:
            if f['symbol']!=s or not f.get('markPrice'):raise PaperError('official funding mark missing')
            funds.append({'symbol':s,'time_ms':int(f['fundingTime']),'rate':float(f['fundingRate']),'mark':float(f['markPrice'])})
    # Quote calls follow candle/history calls to avoid stale entry quotes.
    rawquotes=client.get('/fapi/v1/ticker/bookTicker');rawmarks=client.get('/fapi/v1/premiumIndex')
    end=int(client.get('/fapi/v1/time')['serverTime'])
    if abs(end-local())>5000:raise PaperError('final clock mismatch')
    quotes={x['symbol']:{'bid':float(x['bidPrice']),'ask':float(x['askPrice']),'time_ms':int(x['time'])} for x in rawquotes if x['symbol'] in symbols}
    marks={x['symbol']:{'mark':float(x['markPrice']),'time_ms':int(x['time'])} for x in rawmarks if x['symbol'] in symbols}
    problems=[]
    for s in symbols:
        if s not in quotes or s not in marks:problems.append('missing_quote_or_mark:'+s)
        for iv,step in INTERVAL.items():
            target=boundary//step*step-step
            if not bars[s][iv] or bars[s][iv][-1]['open_time']!=target:problems.append('missing_closed_bar:'+s+':'+iv)
    latest={s:{'open_ms':bars[s]['15m'][-1]['open_time'],'low':bars[s]['15m'][-1]['low'],'high':bars[s]['15m'][-1]['high']} for s in symbols if bars[s]['15m']}
    return {'schema':'IGOR_R17_12_BINANCE_CAPTURE_V1','venue':CONFIG['venue'],'server_ms':end,'boundary_ms':boundary,
            'class':'TIMELY' if 0<=end-boundary<=CONFIG['max_capture_age_ms'] else 'BACKFILL',
            'status':'COMPLETE' if not problems else 'INCOMPLETE','problems':problems,
            'bars':bars,'quotes':quotes,'marks':marks,'closed_15m':latest,'funding':funds,
            'funding_complete_through_ms':server,'capture_elapsed_ms':end-server,'live_orders':False}

def backfill(client,symbols,since,boundary,out):
    # Historical packets import feature data only; they can never open paper trades.
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    count=0
    for s in symbols:
        for iv,step in INTERVAL.items():
            cursor=since//step*step
            while cursor+step<=boundary:
                rows=client.get('/fapi/v1/klines',{'symbol':s,'interval':iv,'startTime':cursor,'endTime':boundary-1,'limit':1500})
                closed=normalize(rows,iv,boundary)
                if not closed:raise PaperError('backfill returned no candles: '+s+' '+iv)
                if [r['open_time'] for r in closed]!=list(range(cursor,closed[-1]['open_time']+step,step)):raise PaperError('backfill candle gap: '+s+' '+iv)
                packet={'schema':'IGOR_R17_12_BACKFILL_V1','venue':CONFIG['venue'],'boundary_ms':boundary,
                        'class':'BACKFILL','bars':{s:{iv:closed}}}
                text=canonical(packet);sha=hashlib.sha256(text.encode()).hexdigest();p=out/(sha+'.json')
                if not p.exists():p.write_text(text)
                cursor=closed[-1]['open_time']+step;count+=len(closed)
    return count

def main():
    p=argparse.ArgumentParser();p.add_argument('--probe',action='store_true');p.add_argument('--history-root');p.add_argument('--backfill-since',type=int);p.add_argument('--through',type=int);p.add_argument('--out')
    a=p.parse_args();client=PublicBinance()
    if a.probe:print(json.dumps({'venue':CONFIG['venue'],'public_time':client.get('/fapi/v1/time'),'live_orders':False}));return
    if a.backfill_since is None or a.through is None or not a.out:p.error('backfill requires --history-root --backfill-since --through --out')
    print(json.dumps({'imported_candles':backfill(client,universe(a.history_root),a.backfill_since,a.through,a.out),'live_orders':False}))
if __name__=='__main__':main()
