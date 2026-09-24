#!/usr/bin/env python3
"""R16.16 collect Binance Spot 15m history for 2021-2023."""
from __future__ import annotations
import io,json,time,zipfile,urllib.request,urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import pandas as pd,numpy as np

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']
BASE='https://data.binance.vision/data/spot/monthly/klines'
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']

def get(url):
    for k in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'R16.16/1.0'})
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

def one(sym,out):
    fs=[];missing=[]
    for y in [2021,2022,2023]:
      for m in range(1,13):
        url=f'{BASE}/{sym}/15m/{sym}-15m-{y:04d}-{m:02d}.zip'
        raw=get(url)
        if raw is None:
            missing.append(f'{y:04d}-{m:02d}');continue
        x=parse(raw)
        if not x.empty:fs.append(x)
    if not fs:return {'symbol':sym,'rows':0,'first':None,'last':None,'gaps':None,'missing':missing}
    x=pd.concat(fs,ignore_index=True).drop_duplicates('open_time').sort_values('open_time')
    keep=['open_time','open','high','low','close','volume','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume']
    dest=out/'15m';dest.mkdir(parents=True,exist_ok=True)
    x[keep].to_csv(dest/f'{sym}.csv.gz',index=False,compression='gzip')
    d=x.open_time.diff().dropna()
    return {'symbol':sym,'rows':int(len(x)),
            'first':pd.to_datetime(x.open_time.min(),unit='ms',utc=True).isoformat(),
            'last':pd.to_datetime(x.open_time.max(),unit='ms',utc=True).isoformat(),
            'gaps':int((d>15*60_000*1.5).sum()),'missing':missing}

def main():
    out=Path('r16_edge_lab/pre2024_history_15m');out.mkdir(parents=True,exist_ok=True)
    audits=[]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(one,s,out) for s in SYMBOLS]
        for f in as_completed(futs):
            a=f.result();audits.append(a);print(a['symbol'],a['rows'],flush=True)
    A=pd.DataFrame(audits).sort_values('symbol');A.to_csv(out/'coverage_audit.csv',index=False)
    manifest={'period':'2021-01-01..2023-12-31','source':'Binance Spot monthly archive','interval':'15m',
              'symbols':len(SYMBOLS),'nonempty':int((A.rows>0).sum()),'rows':int(A.rows.sum()),'items':audits}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({k:manifest[k] for k in ['period','nonempty','rows']},indent=2),flush=True)
if __name__=='__main__':main()
