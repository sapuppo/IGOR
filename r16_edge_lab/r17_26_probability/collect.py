"""Verified public Binance archives. No credentials; no trading endpoints."""
from pathlib import Path
import urllib.request,urllib.error,hashlib,json,concurrent.futures,time,zipfile,io
import pandas as pd
R=Path(__file__).resolve().parent;P=json.loads((R/'protocol.json').read_text());O=R/'raw';O.mkdir(exist_ok=True)
def jobs():
 rows=[]
 for s in P['symbols']:
  for m in pd.period_range('2025-12','2026-10',freq='M'):
   rows.append((s,'klines',str(m),'monthly'))
   if str(m)>='2026-04':rows.append((s,'fundingRate',str(m),'monthly'))
  for d in pd.date_range('2026-11-01','2026-11-24'):
   rows.append((s,'klines',d.strftime('%Y-%m-%d'),'daily'))
  for d in pd.date_range(P['book_start'],'2026-11-24'):
   rows.append((s,'bookDepth',d.strftime('%Y-%m-%d'),'daily'))
 return rows

def fetch(job):
 s,k,period,frequency=job;filename=f'{s}-'+('1m-' if k=='klines' else k+'-')+period+'.zip'
 tail=f'{frequency}/{k}/{s}/'+('1m/' if k=='klines' else '')+filename
 url='https://data.binance.vision/data/futures/um/'+tail;path=O/filename
 for attempt in range(3):
  try:
   checksum=urllib.request.urlopen(url+'.CHECKSUM',timeout=25).read().decode().split()[0]
   raw=path.read_bytes() if path.exists() else urllib.request.urlopen(url,timeout=30).read()
   if hashlib.sha256(raw).hexdigest()!=checksum:raise ValueError('SHA256 mismatch '+filename)
   with zipfile.ZipFile(io.BytesIO(raw)) as z:assert len(z.namelist())==1
   if not path.exists():
    tmp=path.with_suffix('.tmp');tmp.write_bytes(raw);tmp.replace(path)
   return dict(symbol=s,kind=k,period=period,file=filename,url=url,sha256=checksum,bytes=len(raw),status='verified')
  except urllib.error.HTTPError as e:
   if e.code==404:return dict(symbol=s,kind=k,period=period,file=filename,url=url,status='missing_404')
   err=str(e)
  except Exception as e:err=str(e)
 return dict(symbol=s,kind=k,period=period,file=filename,url=url,status='error',error=err)

if __name__=='__main__':
 out=[];start=time.time()
 with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
  for x in pool.map(fetch,jobs()):
   out.append(x)
   if len(out)%50==0:print('progress',len(out),'elapsed',round(time.time()-start),flush=True)
 (R/'manifest.json').write_text(json.dumps(out,indent=2)+'\n')
 from collections import Counter
 print('COMPLETE',Counter(x['status'] for x in out),flush=True)
 if any(x['status']=='error' for x in out):raise SystemExit(2)
