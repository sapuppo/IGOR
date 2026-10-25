"""Download public archives and published SHA256; does not execute strategies."""
from pathlib import Path
import urllib.request,hashlib,json,concurrent.futures,zipfile,io
R=Path(__file__).resolve().parent;O=R/'holdout';O.mkdir(exist_ok=True)
p=json.loads((R/'protocol.json').read_text())
def get(job):
 sym,month,kind=job
 if kind=='klines':tail=f'klines/{sym}/15m/{sym}-15m-{month}.zip'
 else:tail=f'fundingRate/{sym}/{sym}-fundingRate-{month}.zip'
 url='https://data.binance.vision/data/futures/um/monthly/'+tail
 path=O/tail.split('/')[-1]
 checksum=urllib.request.urlopen(url+'.CHECKSUM',timeout=30).read().decode().split()[0]
 raw=path.read_bytes() if path.exists() else urllib.request.urlopen(url,timeout=30).read()
 assert hashlib.sha256(raw).hexdigest()==checksum,(sym,month,kind)
 with zipfile.ZipFile(io.BytesIO(raw)) as z:assert len(z.namelist())==1
 path.write_bytes(raw)
 return dict(symbol=sym,month=month,kind=kind,url=url,sha256=checksum,file=path.name)
if __name__=='__main__':
 jobs=[(s,m,k) for s in p['symbols'] for m in ['2026-07','2026-08'] for k in ['klines','fundingRate']]
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(get,jobs))
 (O/'manifest.json').write_text(json.dumps(rows,indent=2)+'\n');print('verified',len(rows))
