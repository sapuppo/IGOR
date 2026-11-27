"""Official public Binance archives, verified bytes. No trading or API keys."""
from pathlib import Path
import urllib.request,urllib.error,hashlib,json,zipfile,io,concurrent.futures,time
import pandas as pd
R=Path(__file__).resolve().parent;P=json.loads((R/'protocol.json').read_text());O=R/'raw';O.mkdir(exist_ok=True)
def fetch(job):
 sym,kind,period,freq=job;name=sym+('-1h-' if kind=='klines' else '-fundingRate-')+period+'.zip';url='https://data.binance.vision/data/futures/um/'+freq+'/'+kind+'/'+sym+'/'+('1h/' if kind=='klines' else '')+name;path=O/name
 for attempt in range(3):
  try:
   expected=urllib.request.urlopen(url+'.CHECKSUM',timeout=25).read().decode().split()[0];raw=path.read_bytes() if path.exists() else urllib.request.urlopen(url,timeout=30).read();assert hashlib.sha256(raw).hexdigest()==expected
   with zipfile.ZipFile(io.BytesIO(raw)) as z:assert len(z.namelist())==1
   if not path.exists():path.write_bytes(raw)
   return dict(symbol=sym,kind=kind,period=period,frequency=freq,file=name,url=url,sha256=expected,bytes=len(raw),status='verified')
  except urllib.error.HTTPError as e:
   if e.code==404:return dict(symbol=sym,kind=kind,period=period,frequency=freq,file=name,url=url,status='missing_404')
   err=str(e)
  except Exception as e:err=str(e)
 return dict(symbol=sym,kind=kind,period=period,frequency=freq,file=name,url=url,status='error',error=err)
def main():
 jobs=[]
 for s in P['symbols']:
  for m in pd.period_range('2024-05','2026-10',freq='M'):
   for k in ['klines','fundingRate']:jobs.append((s,k,str(m),'monthly'))
  for d in pd.date_range('2026-11-01','2026-11-26'):jobs.append((s,'klines',str(d.date()),'daily'))
 rows=[];t=time.time()
 with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
  for x in pool.map(fetch,jobs):
   rows.append(x)
   if len(rows)%50==0:print('COLLECT',len(rows),'/',len(jobs),'seconds',round(time.time()-t),flush=True)
 (R/'DATA_MANIFEST.json').write_text(json.dumps(rows,indent=2)+'\n')
 from collections import Counter
 print('COMPLETE',Counter(x['status'] for x in rows),flush=True)
 if any(x['status']=='error' for x in rows):raise SystemExit(2)
if __name__=='__main__':main()
