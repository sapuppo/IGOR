from pathlib import Path
import hashlib,json,zipfile,io
import numpy as np,pandas as pd
from strategies import features
R=Path(__file__).resolve().parent;H=R.parent/'usdm_history'
STEP=900000;BAR=16*STEP;DAY=96*STEP
SYMS=json.loads((R/'protocol.json').read_text())['symbols']
def ms(s):return int(pd.Timestamp(s,tz='UTC').timestamp()*1000)
def load(holdout=False):
 manifest=json.loads((H/'manifest.json').read_text());frames={};fund={};hashes={}
 for sym in SYMS:
  for kind in ['kline','funding']:
   entry=next(x for x in manifest['files'] if x['symbol']==sym and x['kind']==kind and (kind=='funding' or x['interval']=='15m'))
   path=H/('funding' if kind=='funding' else 'klines/15m')/(sym+'.csv.gz')
   digest=hashlib.sha256(path.read_bytes()).hexdigest();assert digest==entry['sha256'],path;hashes[str(path.relative_to(H))]=digest
   f=pd.read_csv(path)
   if kind=='kline':frames[sym]=f
   else:fund[sym]=f[['fundingTime','fundingRate']]
 if holdout:
  for entry in json.loads((R/'holdout/manifest.json').read_text()):
   raw=(R/'holdout'/entry['file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==entry['sha256'];hashes[entry['file']]=entry['sha256']
   with zipfile.ZipFile(io.BytesIO(raw)) as z:f=pd.read_csv(z.open(z.namelist()[0]))
   sym=entry['symbol']
   if entry['kind']=='klines':frames[sym]=pd.concat([frames[sym],f],ignore_index=True)
   else:
    f=f.rename(columns={'calc_time':'fundingTime','last_funding_rate':'fundingRate'})
    fund[sym]=pd.concat([fund[sym],f[['fundingTime','fundingRate']]],ignore_index=True)
 end=ms('2026-09-01' if holdout else '2026-07-01');start=ms('2022-10-01');timeline=np.arange(start,end,STEP);packed={};ft={};fundmap={}
 for sym,f in frames.items():
  f=f[(f.open_time>=start)&(f.open_time<end)].set_index('open_time').sort_index()
  assert not f.index.has_duplicates and np.array_equal(f.index,timeline),(sym,'missing/duplicate 15m bars')
  assert np.isfinite(f[['open','high','low','close','quote_volume']]).all().all()
  assert (f.low<=f[['open','close']].min(axis=1)).all() and (f.high>=f[['open','close']].max(axis=1)).all()
  g=f.groupby(f.index//BAR*BAR).agg(dict(open='first',high='max',low='min',close='last',quote_volume='sum'))
  ff=features(g);ff.index=ff.index+BAR;ft[sym]=ff
  packed[sym]=f[['open','high','low','close','quote_volume']].to_numpy()
  events={}
  for x in fund[sym].itertuples():
   when=int(x.fundingTime)
   if start<=when<end:events.setdefault(when//STEP*STEP,[]).append((when,float(x.fundingRate)))
  fundmap[sym]=events
 return dict(start=start,end=end,prices=packed,features=ft,funding=fundmap,hashes=hashes)
