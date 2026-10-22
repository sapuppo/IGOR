"""Download public metrics archives with published SHA256; no API auth/orders."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date,timedelta
import json,hashlib,io,zipfile,time,sys
import urllib.request,urllib.error
import numpy as np,pandas as pd
from types import SimpleNamespace
def get(url,timeout):
 try:
  with urllib.request.urlopen(url,timeout=timeout) as r:raw=r.read();code=r.status
 except urllib.error.HTTPError as ex:
  if ex.code!=404:raise
  raw=b"";code=404
 def raise_error():
  if code!=200:raise ValueError(str(code))
 return SimpleNamespace(status_code=code,content=raw,text=raw.decode("utf-8",errors="replace"),raise_for_status=raise_error)
R=Path(__file__).resolve().parent;D=R/'r17_23_data';C=D/'archive_cache';C.mkdir(exist_ok=True);P=json.loads((R/'r17_23_protocol.json').read_text());BAR=14400000

def task(sym,day):
 name=f'{sym}-metrics-{day}.zip';url=f'https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{name}';folder=C/sym;folder.mkdir(exist_ok=True);zpath=folder/name;hpath=folder/(name+'.CHECKSUM')
 for attempt in range(3):
  try:
   if zpath.exists() and hpath.exists():raw=zpath.read_bytes();checksum=hpath.read_text()
   else:
    a=get(url,timeout=20)
    if a.status_code==404:return {'symbol':sym,'day':day,'status':'missing_404','url':url}
    a.raise_for_status();b=get(url+'.CHECKSUM',timeout=20);b.raise_for_status();raw=a.content;checksum=b.text
   expected=checksum.strip().split()[0];actual=hashlib.sha256(raw).hexdigest()
   if actual!=expected:raise ValueError('SHA256 mismatch')
   with zipfile.ZipFile(io.BytesIO(raw)) as z:
    names=z.namelist()
    if len(names)!=1:raise ValueError('unexpected members')
    f=pd.read_csv(io.BytesIO(z.read(names[0])),usecols=['create_time','symbol','sum_open_interest'])
   if len(f)==0:raise ValueError('empty metrics')
   if not (f.symbol==sym).all():raise ValueError('wrong symbol')
   times=pd.to_datetime(f.create_time,utc=True).astype('int64')//1000000+300000
   vals=pd.to_numeric(f.sum_open_interest,errors='raise');valid=np.isfinite(vals)&(vals>0)
   bad=int((~valid).sum());f=pd.DataFrame({'timestamp':times[valid],'oi':vals[valid]});f['bucket']=f.timestamp//BAR
   samples=f.sort_values('timestamp').groupby('bucket').tail(1)[['timestamp','oi']].to_dict('records')
   if not zpath.exists():zpath.write_bytes(raw);hpath.write_text(checksum)
   return {'symbol':sym,'day':day,'status':'verified','url':url,'sha256':actual,'bytes':len(raw),'rows':len(times),'invalid_rows_excluded':bad,'samples':samples}
  except Exception as ex:
   if attempt==2:return {'symbol':sym,'day':day,'status':'error','url':url,'error':str(ex)[:200]}
 return None

def main():
 start=date.fromisoformat(P['download_start']);end=date.fromisoformat(P['download_end_inclusive']);days=[str(start+timedelta(days=n)) for n in range((end-start).days+1)];jobs=[(s,d) for s in P['symbols'] for d in days];rows=[];sample={s:[] for s in P['symbols']};t0=time.time()
 if '--reverse' in sys.argv:jobs.reverse()
 with ThreadPoolExecutor(max_workers=48) as pool:
  fut={pool.submit(task,*j):j for j in jobs}
  for n,ff in enumerate(as_completed(fut),1):
   x=ff.result();sample[x['symbol']].extend(x.pop('samples',[]));rows.append(x)
   if n%100==0:print('PROGRESS',n,'/',len(jobs),'verified',sum(v['status']=='verified' for v in rows),'errors',sum(v['status']=='error' for v in rows),'seconds',int(time.time()-t0),flush=True)
   if n%500==0:(D/'download_checkpoint.json').write_text(json.dumps(rows))
 cov={}
 for sym,values in sample.items():
  f=pd.DataFrame(values).sort_values('timestamp');f['bucket']=f.timestamp//BAR;f=f.groupby('bucket').tail(1);f=f.drop(columns=['bucket']);assert not f.timestamp.duplicated().any();f.to_csv(D/(sym+'_oi_4h.csv.gz'),index=False,compression='gzip')
  cov[sym]={'samples':len(f),'start':int(f.timestamp.min()),'end':int(f.timestamp.max()),'verified_days':sum(x['symbol']==sym and x['status']=='verified' for x in rows),'missing_days':[x['day'] for x in rows if x['symbol']==sym and x['status']!='verified']}
 manifest={'protocol_sha256':hashlib.sha256((R/'r17_23_protocol.json').read_bytes()).hexdigest(),'records':sorted(rows,key=lambda x:(x['symbol'],x['day'])),'coverage':cov,'elapsed_seconds':time.time()-t0}
 (D/'manifest.json').write_text(json.dumps(manifest,indent=2));print('COMPLETE',json.dumps(cov),flush=True)
if __name__=='__main__':main()
