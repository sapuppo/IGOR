#!/usr/bin/env python3
"""R16.16 collect pre-2024 Binance 15m monthly archives."""
from __future__ import annotations
import io,json,time,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,datetime,timedelta,timezone
import urllib.request,urllib.error
import pandas as pd
import numpy as np

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']
BASE='https://data.binance.vision/data/spot/monthly/klines'
START=date(2021,1,1);END=date(2023,12,31)

def months():
    y,m=START.year,START.month
    while (y,m)<=(END.year,END.month):
        yield y,m
        m+=1
        if m==13:y,m=y+1,1

def get(url):
    for k in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'R16-intraday/1.0'})
            with urllib.request.urlopen(req,timeout=45) as r:return r.read()
        except urllib.error.HTTPError as e:
            if e.code==404:return None
            if k==2:raise
        except Exception:
            if k==2:raise
        time.sleep(k+1)
    return None

def parse(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv')]
        if not names:return pd.DataFrame(columns=COLS)
        with z.open(names[0]) as f:x=pd.read_csv(f,header=None,names=COLS)
    for c in COLS:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close'])
    for c in ['open_time','close_time']:
        v=x[c].astype('int64');x[c]=np.where(v>10**14,v//1000,v).astype('int64')
    return x

def fetch(sym,out):
    frames=[];missing=[]
    for y,m in months():
        raw=get(f'{BASE}/{sym}/15m/{sym}-15m-{y:04d}-{m:02d}.zip')
        if raw is None:missing.append(f'{y:04d}-{m:02d}');continue
        x=parse(raw)
        if not x.empty:frames.append(x)
    if not frames:return {'symbol':sym,'rows':0,'first':None,'last':None,'missing':missing}
    x=pd.concat(frames,ignore_index=True).drop_duplicates('open_time').sort_values('open_time')
    lo=int(datetime(2021,1,1,tzinfo=timezone.utc).timestamp()*1000)
    hi=int(datetime(2024,1,1,tzinfo=timezone.utc).timestamp()*1000)
    x=x[(x.open_time>=lo)&(x.open_time<hi)]
    dest=out/'15m';dest.mkdir(parents=True,exist_ok=True)
    keep=['open_time','open','high','low','close','volume','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume']
    x[keep].to_csv(dest/f'{sym}.csv.gz',index=False,compression='gzip')
    return {'symbol':sym,'rows':int(len(x)),'first':pd.to_datetime(x.open_time.min(),unit='ms',utc=True).isoformat(),'last':pd.to_datetime(x.open_time.max(),unit='ms',utc=True).isoformat(),'missing':missing}

out=Path('r16_edge_lab/pre2024_15m');out.mkdir(parents=True,exist_ok=True)
aud=[]
with ThreadPoolExecutor(max_workers=10) as ex:
    fs={ex.submit(fetch,s,out):s for s in SYMBOLS}
    for f in as_completed(fs):
        a=f.result();aud.append(a);print(a['symbol'],a['rows'],flush=True)
A=pd.DataFrame(aud).sort_values('symbol');A.to_csv(out/'coverage_audit.csv',index=False)
(out/'manifest.json').write_text(json.dumps({'start':'2021-01-01','end':'2023-12-31','interval':'15m','rows':int(A.rows.sum()),'items':aud},indent=2),encoding='utf-8')
print(json.dumps({'rows':int(A.rows.sum()),'nonempty':int((A.rows>0).sum())}),flush=True)
