#!/usr/bin/env python3
import sys, json, time, hashlib, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlencode
ROOT=Path('v09_bridge_bundle').resolve()
sys.path.insert(0,str(ROOT))
import v09_historical_backfill as hb
import v09_lowcap_backfill as lc
EXPECTED={
 'base_engine.py':'516a94dca8aa81ff6529edcac7358d726fa0d8eac9a08edaeb2a6252d353055a',
 'experiment.py':'73f097f22375c3e05512899d53f3f2dc662c7dbab73e76aeb686a70db000cc3e',
 'experiment_v08.py':'caa88546a5f6585a7ceab62ddb8a57ba89e573fd50979b91d07b126b139ba2f6'}
for fn,want in EXPECTED.items():
    got=hashlib.sha256((ROOT/fn).read_bytes()).hexdigest()
    if got!=want: raise SystemExit(f'FROZEN CORE HASH MISMATCH {fn} {got}')
print('FROZEN CORE HASHES PASS',flush=True)
UA='Mozilla/5.0 V09-validation/1.0'

def http_json(base,path,params=None):
    url=base+path
    if params: url+='?'+urlencode(params)
    last=None
    for attempt in range(8):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=45) as r:
                raw=r.read()
            time.sleep(0.075)
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            last=e
            # Invalid/nonexistent symbols are expected during historical contract discovery.
            if e.code in (400,404): raise
            if e.code in (418,429,451,502,503,504):
                wait=min(60,4*(attempt+1)); print(f'HTTP {e.code} retry {attempt+1} wait={wait}s {url[:120]}',flush=True); time.sleep(wait); continue
            raise
        except Exception as e:
            last=e; wait=min(30,2*(attempt+1)); print(f'NET retry {attempt+1} wait={wait}s {type(e).__name__} {url[:120]}',flush=True); time.sleep(wait)
    raise RuntimeError(f'GET failed {url}: {last}')

hb.http_json=http_json

def fetch_klines(symbol,interval,start_ms,end_ms,mark=False):
    path='/fapi/v1/markPriceKlines' if mark else '/fapi/v1/klines'
    # 4h windows have <250 bars. limit=499 cuts Binance request weight from 10 to 2.
    limit=499 if interval=='4h' else 1000
    step=hb.H if interval=='1h' else hb.FOUR_H if interval=='4h' else None
    if step is None: raise ValueError('unsupported interval')
    out=[]; cursor=start_ms
    while cursor<end_ms:
        rows=http_json(hb.FAPI,path,{'symbol':symbol,'interval':interval,'startTime':cursor,'endTime':end_ms-1,'limit':limit})
        if not rows: break
        out.extend(rows); nxt=int(rows[-1][0])+step
        if nxt<=cursor: raise RuntimeError('non-advancing kline cursor')
        cursor=nxt
        if len(rows)<limit: break
    by={int(r[0]):r for r in out if start_ms<=int(r[0])<end_ms}
    return [by[k] for k in sorted(by)]
hb.fetch_klines=fetch_klines

def fetch_cmc_snapshot(date_iso,cache_dir,limit):
    cache_dir.mkdir(parents=True,exist_ok=True)
    cache=cache_dir/f'cmc_{date_iso.replace("-","")}_top{limit}.json'
    if cache.exists():
        rows=json.loads(cache.read_text(encoding='utf-8'))
        if len(rows)>=limit: return rows[:limit]
    base='https://api.coinmarketcap.com'
    path='/data-api/v3/cryptocurrency/listings/historical'
    payload=http_json(base,path,{'date':date_iso,'start':1,'limit':limit,'convert':'USD'})
    raw=payload.get('data') if isinstance(payload,dict) else None
    if not isinstance(raw,list) or len(raw)<limit: raise ValueError(f'CMC PIT incomplete {date_iso}: {0 if not isinstance(raw,list) else len(raw)}/{limit}')
    rows=[{'rank':int(x['cmcRank']),'name':x.get('name') or x.get('symbol'),'cmc_symbol':str(x.get('symbol') or '').upper(),'cmc_id':x.get('id')} for x in raw[:limit]]
    if [x['rank'] for x in rows] != list(range(1,limit+1)): raise ValueError(f'CMC rank sequence mismatch {date_iso}')
    cache.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    return rows
lc.fetch_cmc_snapshot=fetch_cmc_snapshot

# Run exactly the pre-registered 101-300 bucket. Strategy/risk/exit core is untouched.
out=Path('v09_out/lowcap_101_300.json').resolve(); out.parent.mkdir(parents=True,exist_ok=True)
sys.argv=['v09_lowcap_backfill.py','--rank-min','101','--rank-max','300','--cmc-limit','300','--windows','all','--stress','1,2,3','--output',str(out)]
lc.main()
print('RESULT',out,flush=True)
