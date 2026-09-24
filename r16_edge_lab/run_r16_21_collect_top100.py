#!/usr/bin/env python3
"""R16.21 current-liquid top100 USDT universe + 2024-Jun2026 15m history.

Universe is selected for present deployability using current Binance Spot
exchangeInfo + 24h quote volume, not backtest outcome.
This introduces current-survivor selection, so results are treated as
cross-universe development evidence, not untouched temporal holdout.
"""
from __future__ import annotations
import io,json,time,zipfile,urllib.request,urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import pandas as pd,numpy as np

OUT=Path('r16_edge_lab/r16_21_top100_history');OUT.mkdir(parents=True,exist_ok=True)
BASE_ARCH='https://data.binance.vision/data/spot/monthly/klines'
API=['https://api.binance.com','https://data-api.binance.vision']
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']
DEV39=set(['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT'])
EXCLUDE_BASE={'USDT','USDC','FDUSD','TUSD','BUSD','DAI','USDP','EUR','EURI','AEUR','TRY','BRL','ARS','BIDR','IDRT','UAH','RUB','GBP','AUD','JPY','ZAR','NGN','PLN','RON','CZK','MXN'}

def api_get(path):
    last=None
    for base in API:
        try:
            req=urllib.request.Request(base+path,headers={'User-Agent':'R16.21/1.0'})
            with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read())
        except Exception as e:last=e
    raise last

def select_universe():
    ex=api_get('/api/v3/exchangeInfo')
    tick=api_get('/api/v3/ticker/24hr')
    qv={x['symbol']:float(x.get('quoteVolume') or 0) for x in tick}
    rows=[]
    for s in ex['symbols']:
        sym=s['symbol'];base=s['baseAsset']
        if s.get('quoteAsset')!='USDT' or s.get('status')!='TRADING' or not s.get('isSpotTradingAllowed',False):continue
        if base in EXCLUDE_BASE:continue
        if base.endswith(('UP','DOWN','BULL','BEAR')):continue
        rows.append((sym,base,qv.get(sym,0.0)))
    rows.sort(key=lambda x:x[2],reverse=True)
    top=rows[:100]
    return [{'symbol':s,'base':b,'quote_volume_24h':q,'was_in_dev39':s in DEV39} for s,b,q in top]

def get(url):
    for k in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'R16.21/1.0'})
            with urllib.request.urlopen(req,timeout=45) as r:return r.read()
        except urllib.error.HTTPError as e:
            if e.code==404:return None
            if k==2:raise
        except Exception:
            if k==2:raise
        time.sleep(k+1)

def parse(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        if not names:return pd.DataFrame(columns=COLS)
        with z.open(names[0]) as f:x=pd.read_csv(f,header=None,names=COLS)
    for c in COLS:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close'])
    for c in ['open_time','close_time']:
        v=x[c].astype('int64');x[c]=np.where(v>10**14,v//1000,v).astype('int64')
    return x

def one(sym):
    fs=[];missing=[]
    for y in [2024,2025,2026]:
      maxm=12 if y<2026 else 6
      for m in range(1,maxm+1):
        raw=get(f'{BASE_ARCH}/{sym}/15m/{sym}-15m-{y:04d}-{m:02d}.zip')
        if raw is None:missing.append(f'{y:04d}-{m:02d}');continue
        x=parse(raw)
        if not x.empty:fs.append(x)
    if not fs:return {'symbol':sym,'rows':0,'first':None,'last':None,'gaps':None,'missing':missing}
    x=pd.concat(fs,ignore_index=True).drop_duplicates('open_time').sort_values('open_time')
    dest=OUT/'15m';dest.mkdir(parents=True,exist_ok=True)
    keep=['open_time','open','high','low','close','volume','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume']
    x[keep].to_csv(dest/f'{sym}.csv.gz',index=False,compression='gzip')
    d=x.open_time.diff().dropna()
    return {'symbol':sym,'rows':int(len(x)),'first':pd.to_datetime(x.open_time.min(),unit='ms',utc=True).isoformat(),
            'last':pd.to_datetime(x.open_time.max(),unit='ms',utc=True).isoformat(),'gaps':int((d>15*60_000*1.5).sum()),'missing':missing}

def main():
    uni=select_universe()
    (OUT/'universe.json').write_text(json.dumps(uni,indent=2),encoding='utf-8')
    print('top100 selected; dev39 overlap',sum(x['was_in_dev39'] for x in uni),flush=True)
    audits=[]
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs=[ex.submit(one,u['symbol']) for u in uni]
        for f in as_completed(futs):
            a=f.result();audits.append(a);print(a['symbol'],a['rows'],flush=True)
    A=pd.DataFrame(audits).sort_values('symbol');A.to_csv(OUT/'coverage.csv',index=False)
    manifest={'period':'2024-01-01..2026-06-30','top100':len(uni),'dev39_overlap':sum(x['was_in_dev39'] for x in uni),
              'new_symbols':sum(not x['was_in_dev39'] for x in uni),'rows':int(A.rows.sum()),'nonempty':int((A.rows>0).sum()),
              'selection':'current Binance spot USDT top100 by 24h quote volume; no backtest outcome used'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2),flush=True)
if __name__=='__main__':main()
