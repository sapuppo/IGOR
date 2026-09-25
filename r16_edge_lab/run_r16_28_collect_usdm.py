#!/usr/bin/env python3
"""R16.28.1 Binance USD-M perpetual PIT collector, Binance Vision only."""
from __future__ import annotations
import argparse,hashlib,io,json,time,urllib.error,urllib.request,zipfile
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import pandas as pd,numpy as np
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']
INTERVALS=['15m','1h','4h']; BASE='https://data.binance.vision/data/futures/um'
KCOL=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']
def get(url,retries=4):
 for i in range(retries):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'IGOR-R16/1.0'}),timeout=90) as r:return r.read()
  except urllib.error.HTTPError as e:
   if e.code==404:return None
   if i==retries-1:raise
  except Exception:
   if i==retries-1:raise
  time.sleep(1+i)
 return None
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def months(a,b):
 y,m=a.year,a.month
 while (y,m)<=(b.year,b.month):
  yield y,m;m+=1
  if m==13:y,m=y+1,1
def parse(raw,names):
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  n=next(n for n in z.namelist() if n.endswith('.csv'))
  with z.open(n) as f:return pd.read_csv(f,header=None,names=names)
def klines(sym,iv,start,end):
 fs=[]
 for y,m in months(start,end):
  raw=get(f'{BASE}/monthly/klines/{sym}/{iv}/{sym}-{iv}-{y:04d}-{m:02d}.zip')
  if raw is None:continue
  x=parse(raw,KCOL)
  for c in KCOL:x[c]=pd.to_numeric(x[c],errors='coerce')
  x=x.dropna(subset=['open_time','open','high','low','close'])
  if not x.empty:fs.append(x)
 if not fs:return pd.DataFrame(columns=KCOL)
 x=pd.concat(fs,ignore_index=True).drop_duplicates('open_time').sort_values('open_time')
 v=x.open_time.astype('int64');x['open_time']=np.where(v>10**14,v//1000,v).astype('int64')
 lo=int(datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000);hi=int(datetime.combine(end,datetime.max.time(),tzinfo=timezone.utc).timestamp()*1000)
 return x[(x.open_time>=lo)&(x.open_time<=hi)]
def funding(sym,start,end):
 cols=['calc_time','funding_interval_hours','last_funding_rate'];fs=[]
 for y,m in months(start,end):
  raw=get(f'{BASE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{y:04d}-{m:02d}.zip')
  if raw is None:continue
  x=parse(raw,cols)
  for c in cols:x[c]=pd.to_numeric(x[c],errors='coerce')
  x=x.dropna(subset=['calc_time','last_funding_rate'])
  if not x.empty:fs.append(x)
 if not fs:return pd.DataFrame(columns=['symbol','fundingTime','fundingRate'])
 x=pd.concat(fs,ignore_index=True).drop_duplicates('calc_time').sort_values('calc_time');v=x.calc_time.astype('int64');x['fundingTime']=np.where(v>10**14,v//1000,v).astype('int64');x['symbol']=sym;x['fundingRate']=x.last_funding_rate.astype(float)
 return x[['symbol','fundingTime','fundingRate']]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--start',default='2021-01-01');ap.add_argument('--end',default='2026-06-30');ap.add_argument('--output',default='r16_edge_lab/usdm_history');ap.add_argument('--symbols',default=','.join(SYMBOLS));ap.add_argument('--intervals',default=','.join(INTERVALS));a=ap.parse_args()
 start=date.fromisoformat(a.start);end=date.fromisoformat(a.end);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
 man={'version':'R16.28.1','venue':'Binance USD-M Futures public archive','contractType':'PERPETUAL','start':a.start,'end':a.end,'symbols':[],'files':[]}
 for sym in [s.strip().upper() for s in a.symbols.split(',') if s.strip()]:
  print('FUNDING',sym,flush=True);fd=funding(sym,start,end)
  if fd.empty:man['symbols'].append({'symbol':sym,'eligible':False,'reason':'no_funding_archive'});continue
  first=int(fd.fundingTime.min());eff=datetime.fromtimestamp(first/1000,tz=timezone.utc).date();man['symbols'].append({'symbol':sym,'eligible':True,'pit_evidence':'first USD-M funding archive timestamp','firstFundingTime':first,'effective_start':eff.isoformat()})
  p=out/'funding'/f'{sym}.csv.gz';p.parent.mkdir(parents=True,exist_ok=True);fd.to_csv(p,index=False,compression='gzip');man['files'].append({'kind':'funding','symbol':sym,'path':str(p),'rows':len(fd),'first':first,'last':int(fd.fundingTime.max()),'sha256':sha(p)})
  for iv in [v.strip() for v in a.intervals.split(',') if v.strip()]:
   print('KLINES',sym,iv,flush=True);x=klines(sym,iv,eff,end);x=x[x.open_time>=first]
   if x.empty:continue
   p=out/'klines'/iv/f'{sym}.csv.gz';p.parent.mkdir(parents=True,exist_ok=True);keep=['open_time','open','high','low','close','volume','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume'];x[keep].to_csv(p,index=False,compression='gzip');man['files'].append({'kind':'kline','symbol':sym,'interval':iv,'path':str(p),'rows':len(x),'first':int(x.open_time.min()),'last':int(x.open_time.max()),'sha256':sha(p)})
 (out/'manifest.json').write_text(json.dumps(man,indent=2),encoding='utf-8');print(json.dumps({'symbols':len(man['symbols']),'files':len(man['files']),'manifest_payload_sha256':hashlib.sha256(json.dumps(man,sort_keys=True).encode()).hexdigest()},indent=2))
if __name__=='__main__':main()
