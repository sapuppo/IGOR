#!/usr/bin/env python3
"""R15.2 Binance historical OHLCV collector: 2024-01-01 -> requested end date.
Downloads official Binance public Spot kline archives, normalizes ms/us timestamps,
deduplicates and audits continuity. Monthly archives first; daily archives for
the current/incomplete month. No API key required.
"""
from __future__ import annotations
import argparse, io, json, time, zipfile
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import urllib.request, urllib.error
import pandas as pd
import numpy as np

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']
INTERVALS=['15m','1h','4h','1d']
COLS=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']
BASE='https://data.binance.vision/data/spot'
IVMS={'15m':900000,'1h':3600000,'4h':14400000,'1d':86400000}

def months(a,b):
    y,m=a.year,a.month
    while (y,m)<=(b.year,b.month):
        yield y,m
        m+=1
        if m==13:y,m=y+1,1

def get_zip(url,retries=3):
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'R15-regime-research/1.0'})
            with urllib.request.urlopen(req,timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code==404:return None
            if i==retries-1:raise
        except Exception:
            if i==retries-1:raise
        time.sleep(1.5*(i+1))
    return None

def parse_zip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv')]
        if not names:return pd.DataFrame(columns=COLS)
        with z.open(names[0]) as f:
            x=pd.read_csv(f,header=None,names=COLS)
    return x

def normalize(x):
    if x.empty:return x
    for c in COLS:x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open_time','open','high','low','close'])
    # Binance Spot archives use microseconds from 2025 onward; normalize to ms.
    for c in ['open_time','close_time']:
        v=x[c].astype('int64')
        x[c]=np.where(v>10**14,v//1000,v).astype('int64')
    return x

def fetch_symbol_interval(sym,iv,start,end):
    frames=[]; missing=[]
    current_month=(end.year,end.month)
    for y,m in months(start,end):
        month_start=date(y,m,1)
        next_month=date(y+1,1,1) if m==12 else date(y,m+1,1)
        month_end=next_month-timedelta(days=1)
        # For complete past months prefer compact monthly archive.
        if (y,m)<current_month:
            url=f'{BASE}/monthly/klines/{sym}/{iv}/{sym}-{iv}-{y:04d}-{m:02d}.zip'
            raw=get_zip(url)
            if raw is not None:
                frames.append(normalize(parse_zip(raw))); continue
        # Missing monthly archive (new listing) or current month: daily fallback.
        d=max(start,month_start); stop=min(end,month_end)
        while d<=stop:
            url=f'{BASE}/daily/klines/{sym}/{iv}/{sym}-{iv}-{d.isoformat()}.zip'
            raw=get_zip(url)
            if raw is not None: frames.append(normalize(parse_zip(raw)))
            else: missing.append(d.isoformat())
            d+=timedelta(days=1)
    if not frames:return pd.DataFrame(columns=COLS),missing
    x=pd.concat(frames,ignore_index=True).drop_duplicates('open_time').sort_values('open_time')
    lo=int(datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)
    hi=int((datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)-1)
    x=x[(x.open_time>=lo)&(x.open_time<=hi)].copy()
    return x,missing

def audit(sym,iv,x,start,end):
    if x.empty:return {'symbol':sym,'interval':iv,'rows':0,'start':None,'end':None,'gaps':None,'estimated_missing':None,'duplicates':0}
    d=x.open_time.diff().dropna(); step=IVMS[iv]
    miss=np.maximum(np.rint(d/step)-1,0)
    return {'symbol':sym,'interval':iv,'rows':len(x),
      'start':pd.to_datetime(x.open_time.min(),unit='ms',utc=True).isoformat(),
      'end':pd.to_datetime(x.open_time.max(),unit='ms',utc=True).isoformat(),
      'gaps':int((d>step*1.5).sum()),'estimated_missing':int(miss.sum()),
      'duplicates':int(x.open_time.duplicated().sum()),
      'bad_ohlc':int(((x.high<x[['open','close','low']].max(axis=1))|(x.low>x[['open','close','high']].min(axis=1))).sum()),
      'zero_volume':int((x.volume<=0).sum())}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',default='2024-01-01')
    ap.add_argument('--end',default=date.today().isoformat())
    ap.add_argument('--output',default='r15_regime_lab/history')
    ap.add_argument('--symbols',default=','.join(SYMBOLS))
    ap.add_argument('--intervals',default=','.join(INTERVALS))
    args=ap.parse_args()
    start=date.fromisoformat(args.start); end=date.fromisoformat(args.end)
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    audits=[]; manifest={'start':args.start,'end':args.end,'source':'Binance Spot public archive','items':[]}
    for sym in [s.strip().upper() for s in args.symbols.split(',') if s.strip()]:
      for iv in [s.strip() for s in args.intervals.split(',') if s.strip()]:
        print(f'FETCH {sym} {iv}',flush=True)
        x,missing_days=fetch_symbol_interval(sym,iv,start,end)
        dest=out/iv; dest.mkdir(parents=True,exist_ok=True)
        if not x.empty:
            keep=['open_time','open','high','low','close','volume','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume']
            x[keep].to_csv(dest/f'{sym}.csv.gz',index=False,compression='gzip')
        a=audit(sym,iv,x,start,end); audits.append(a)
        manifest['items'].append({**a,'missing_archive_days':missing_days})
    A=pd.DataFrame(audits)
    A.to_csv(out/'coverage_audit.csv',index=False)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(A.groupby('interval').agg(symbols=('symbol','count'),rows=('rows','sum'),gaps=('gaps','sum'),estimated_missing=('estimated_missing','sum')).to_string())
if __name__=='__main__':main()
