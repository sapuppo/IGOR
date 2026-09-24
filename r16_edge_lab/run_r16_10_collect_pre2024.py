#!/usr/bin/env python3
"""R16.10 pre-2024 Binance collector.

Downloads official Binance Spot monthly archives for 1h/4h from 2021-01-01
through 2023-12-31. Monthly-only by design: a 404 in a complete historical
month is treated as unavailable/not-listed, avoiding expensive daily fallback.
"""
from __future__ import annotations
import argparse, io, json, time, zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import urllib.request, urllib.error
import pandas as pd
import numpy as np

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']
INTERVALS=['1h','4h']
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']
BASE='https://data.binance.vision/data/spot/monthly/klines'
IVMS={'1h':3600000,'4h':14400000}

def months(start,end):
    y,m=start.year,start.month
    while (y,m)<=(end.year,end.month):
        yield y,m
        m+=1
        if m==13:
            y,m=y+1,1

def get_zip(url,retries=3):
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'R16-extended-history/1.0'})
            with urllib.request.urlopen(req,timeout=45) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code==404:
                return None
            if i==retries-1:
                raise
        except Exception:
            if i==retries-1:
                raise
        time.sleep(1.0*(i+1))
    return None

def parse(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv')]
        if not names:
            return pd.DataFrame(columns=COLS)
        with z.open(names[0]) as f:
            x=pd.read_csv(f,header=None,names=COLS)
    for c in COLS:
        x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close'])
    for c in ['open_time','close_time']:
        v=x[c].astype('int64')
        x[c]=np.where(v>10**14,v//1000,v).astype('int64')
    return x

def fetch_one(sym,iv,start,end,out):
    frames=[]
    missing=[]
    for y,m in months(start,end):
        url=f'{BASE}/{sym}/{iv}/{sym}-{iv}-{y:04d}-{m:02d}.zip'
        raw=get_zip(url)
        if raw is None:
            missing.append(f'{y:04d}-{m:02d}')
            continue
        x=parse(raw)
        if not x.empty:
            frames.append(x)
    if not frames:
        return {'symbol':sym,'interval':iv,'rows':0,'first':None,'last':None,'gaps':None,'missing_months':missing}
    x=pd.concat(frames,ignore_index=True).drop_duplicates('open_time').sort_values('open_time')
    lo=int(datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)
    hi=int(datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)-1
    x=x[(x.open_time>=lo)&(x.open_time<=hi)].copy()
    dest=out/iv
    dest.mkdir(parents=True,exist_ok=True)
    keep=['open_time','open','high','low','close','volume','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume']
    x[keep].to_csv(dest/f'{sym}.csv.gz',index=False,compression='gzip')
    step=IVMS[iv]
    d=x.open_time.diff().dropna()
    gaps=int((d>step*1.5).sum())
    return {
        'symbol':sym,'interval':iv,'rows':int(len(x)),
        'first':pd.to_datetime(x.open_time.min(),unit='ms',utc=True).isoformat(),
        'last':pd.to_datetime(x.open_time.max(),unit='ms',utc=True).isoformat(),
        'gaps':gaps,'missing_months':missing
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',default='2021-01-01')
    ap.add_argument('--end',default='2023-12-31')
    ap.add_argument('--output',default='r16_edge_lab/pre2024_history')
    ap.add_argument('--workers',type=int,default=8)
    args=ap.parse_args()
    start=date.fromisoformat(args.start)
    end=date.fromisoformat(args.end)
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)

    tasks=[]
    audits=[]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for sym in SYMBOLS:
            for iv in INTERVALS:
                tasks.append(ex.submit(fetch_one,sym,iv,start,end,out))
        for fut in as_completed(tasks):
            a=fut.result()
            audits.append(a)
            print(f"{a['symbol']} {a['interval']} rows={a['rows']} first={a['first']}",flush=True)

    A=pd.DataFrame(audits).sort_values(['interval','symbol'])
    A.to_csv(out/'coverage_audit.csv',index=False)
    manifest={
        'start':args.start,'end':args.end,
        'source':'Binance Spot public monthly archive',
        'intervals':INTERVALS,
        'symbols':len(SYMBOLS),
        'total_rows':int(A.rows.sum()),
        'nonempty_series':int((A.rows>0).sum()),
        'items':audits
    }
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({k:manifest[k] for k in ['start','end','total_rows','nonempty_series']},indent=2),flush=True)

if __name__=='__main__':
    main()
