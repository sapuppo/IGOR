#!/usr/bin/env python3
import json, pathlib, urllib.request, time
DATES=['2026-02-01','2026-03-01','2026-04-05','2026-05-03','2026-06-07','2026-07-05']
BASE='https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical'
OUT=pathlib.Path('v09_out/cmc'); OUT.mkdir(parents=True,exist_ok=True)
headers={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept':'application/json','Accept-Language':'en-US,en;q=0.9'}
manifest=[]
for date in DATES:
    url=f'{BASE}?date={date}&start=1&limit=300&convert=USD'
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=60) as r: payload=json.loads(r.read())
    rows=payload.get('data') if isinstance(payload,dict) else None
    if not isinstance(rows,list) or len(rows)<300:
        raise SystemExit(f'{date}: incomplete CMC response {0 if not isinstance(rows,list) else len(rows)}')
    slim=[]
    for x in rows[:300]:
        slim.append({'rank':int(x['cmcRank']),'cmc_id':x.get('id'),'name':x.get('name'),'cmc_symbol':str(x.get('symbol') or '').upper(),'slug':x.get('slug')})
    if [x['rank'] for x in slim] != list(range(1,301)):
        raise SystemExit(f'{date}: rank sequence mismatch')
    p=OUT/f'cmc_{date.replace("-","")}_top300.json'; p.write_text(json.dumps(slim,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest.append({'date':date,'rows':len(slim),'rank101':slim[100]['cmc_symbol'],'rank200':slim[199]['cmc_symbol'],'rank201':slim[200]['cmc_symbol'],'rank300':slim[299]['cmc_symbol']})
    print(date, manifest[-1], flush=True); time.sleep(1)
pathlib.Path('v09_out/cmc_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
