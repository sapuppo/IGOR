#!/usr/bin/env python3
"""R16.28 Binance USD-M perpetual point-in-time historical data collector."""
from __future__ import annotations
import argparse,hashlib,io,json,time,urllib.error,urllib.request,zipfile
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import pandas as pd,numpy as np

SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']
INTERVALS=['15m','1h','4h']
IVMS={'15m':900000,'1h':3600000,'4h':14400000}
BASE='https://data.binance.vision/data/futures/um'
FAPI='https://fapi.binance.com'
KCOL=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']

def get(url,retries=5):
 for i in range(retries):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'IGOR-R16-integrity/1.0'})
   with urllib.request.urlopen(req,timeout=90) as r:return r.read()
  except urllib.error.HTTPError as e:
   if e.code==404:return None
   if e.code in (418,429):time.sleep(3*(i+1));continue
   if i==retries-1:raise
  except Exception:
   if i==retries-1:raise
  time.sleep(1.5*(i+1))
 return None

def js(url):
 raw=get(url)
 if raw is None:return None
 return json.loads(raw)

def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def months(a,b):
 y,m=a.year,a.month
 while (y,m)<=(b.year,b.month):
  yield y,m
  m+=1
  if m==13:y,m=y+1,1

def parse_zip(raw,cols):
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  n=next((n for n in z.namelist() if n.endswith('.csv')),None)
  if not n:return pd.DataFrame(columns=cols)
  with z.open(n) as f:return pd.read_csv(f,header=None,names=cols)

def norm_k(x):
 if x.empty:return x
 for c in KCOL:x[c]=pd.to_numeric(x[c],errors='coerce')
 x=x.dropna(subset=['open_time','open','high','low','close'])
 for c in ['open_time','close_time']:
  v=x[c].astype('int64');x[c]=np.where(v>10**14,v//1000,v).astype('int64')
 return x

def fetch_klines(sym,iv,start,end):
 frames=[]
 for y,m in months(start,end):
  url=f'{BASE}/monthly/klines/{sym}/{iv}/{sym}-{iv}-{y:04d}-{m:02d}.zip'
  raw=get(url)
  if raw is not None:frames.append(norm_k(parse_zip(raw,KCOL)));continue
  d=max(start,date(y,m,1)); nxt=date(y+1,1,1) if m==12 else date(y,m+1,1); stop=min(end,nxt-timedelta(days=1))
  while d<=stop:
   raw=get(f'{BASE}/daily/klines/{sym}/{iv}/{sym}-{iv}-{d.isoformat()}.zip')
   if raw is not None:frames.append(norm_k(parse_zip(raw,KCOL)))
   d+=timedelta(days=1)
 if not frames:return pd.DataFrame(columns=KCOL)
 x=pd.concat(frames,ignore_index=True).drop_duplicates('open_time').sort_values('open_time')
 lo=int(datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)
 hi=int((datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)-1)
 return x[(x.open_time>=lo)&(x.open_time<=hi)].copy()

def funding(sym,start_ms,end_ms):
 rows=[];cur=start_ms
 while cur<=end_ms:
  u=f'{FAPI}/fapi/v1/fundingRate?symbol={sym}&startTime={cur}&endTime={end_ms}&limit=1000'
  a=js(u) or []
  if not a:break
  rows.extend(a);last=max(int(r['fundingTime']) for r in a)
  if last<cur:break
  cur=last+1
  if len(a)<1000:break
  time.sleep(.08)
 if not rows:return pd.DataFrame(columns=['symbol','fundingTime','fundingRate','markPrice'])
 x=pd.DataFrame(rows).drop_duplicates(['symbol','fundingTime']).sort_values('fundingTime')
 x['fundingTime']=pd.to_numeric(x.fundingTime);x['fundingRate']=pd.to_numeric(x.fundingRate);return x

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--start',default='2021-01-01');ap.add_argument('--end',default='2026-06-30')
 ap.add_argument('--output',default='r16_edge_lab/usdm_history');ap.add_argument('--symbols',default=','.join(SYMBOLS));ap.add_argument('--intervals',default=','.join(INTERVALS))
 a=ap.parse_args();start=date.fromisoformat(a.start);end=date.fromisoformat(a.end);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 info=js(FAPI+'/fapi/v1/exchangeInfo');meta={s['symbol']:s for s in info['symbols']}
 manifest={'version':'R16.28','venue':'Binance USD-M Futures','contractType':'PERPETUAL','start':a.start,'end':a.end,'files':[],'symbols':[]}
 for sym in [x.strip().upper() for x in a.symbols.split(',') if x.strip()]:
  m=meta.get(sym)
  if not m or m.get('contractType')!='PERPETUAL':
   manifest['symbols'].append({'symbol':sym,'eligible':False,'reason':'not_current_usdm_perpetual'});continue
  onboard=int(m['onboardDate']);sdate=max(start,datetime.fromtimestamp(onboard/1000,tz=timezone.utc).date())
  manifest['symbols'].append({'symbol':sym,'eligible':True,'onboardDate':onboard,'status':m.get('status'),'effective_start':sdate.isoformat()})
  if sdate>end:continue
  for iv in [x.strip() for x in a.intervals.split(',') if x.strip()]:
   print('KLINES',sym,iv,flush=True);x=fetch_klines(sym,iv,sdate,end)
   if not x.empty:
    x=x[x.open_time>=onboard];p=out/'klines'/iv/f'{sym}.csv.gz';p.parent.mkdir(parents=True,exist_ok=True)
    keep=['open_time','open','high','low','close','volume','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume'];x[keep].to_csv(p,index=False,compression='gzip')
    manifest['files'].append({'kind':'kline','symbol':sym,'interval':iv,'path':str(p),'rows':len(x),'first':int(x.open_time.min()),'last':int(x.open_time.max()),'sha256':sha(p)})
  print('FUNDING',sym,flush=True);lo=max(onboard,int(datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000));hi=int(datetime.combine(end,datetime.max.time(),tzinfo=timezone.utc).timestamp()*1000)
  fd=funding(sym,lo,hi)
  if not fd.empty:
   p=out/'funding'/f'{sym}.csv.gz';p.parent.mkdir(parents=True,exist_ok=True);fd.to_csv(p,index=False,compression='gzip')
   manifest['files'].append({'kind':'funding','symbol':sym,'path':str(p),'rows':len(fd),'first':int(fd.fundingTime.min()),'last':int(fd.fundingTime.max()),'sha256':sha(p)})
 mp=out/'manifest.json';mp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 print(json.dumps({'symbols':len(manifest['symbols']),'files':len(manifest['files']),'manifest_payload_sha256':hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()},indent=2))
if __name__=='__main__':main()
