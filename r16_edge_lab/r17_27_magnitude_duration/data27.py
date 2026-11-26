"""Reuse frozen R17.26 data; independent long-horizon labels, no source edits."""
from pathlib import Path
import json,hashlib,sys
import numpy as np,pandas as pd
R=Path(__file__).resolve().parent;P=json.loads((R/'protocol.json').read_text());R26=R.parent/'r17_26_probability';STEP=60000;DAY=1440*STEP;SYMS=P['symbols'];HORIZONS=P['horizons_minutes']
sys.path.insert(0,str(R26))
from prepare import BASE_FEATURES,BOOK_FEATURES,labels,feature_frame,ms
FEATURES=BASE_FEATURES+['ret180','vol180','eff60','stop_fraction']

def long_features(x,prices,times):
 out=x.copy();c=pd.Series(prices[:,3],index=times);ret180=c.pct_change(180).to_numpy();vol180=c.pct_change().rolling(180).std().to_numpy();eff60=((c-c.shift(60)).abs()/c.diff().abs().rolling(60).sum().replace(0,np.nan)).to_numpy()
 out['ret180']=ret180;out['vol180']=vol180;out['eff60']=eff60
 return out

def stop_fraction(atrfrac,horizon):return np.clip(2*np.asarray(atrfrac)*np.sqrt(horizon/8),.003,.02)

def prepare():
 O=R/'prepared';O.mkdir(exist_ok=True);hashes={};raw_manifest=json.loads((R26/'manifest.json').read_text())
 # Input ZIPs are public, reproducible and verified before new labels are built.
 for e in raw_manifest:
  if e['status']=='verified':
   p=R26/'raw'/e['file'];assert hashlib.sha256(p.read_bytes()).hexdigest()==e['sha256'],p
 for s in SYMS:
  paths=[R26/'prepared'/(s+suffix) for suffix in ['_prices.npy','_times.npy','_features.pkl','_funding.pkl']]
  for p in paths:hashes[str(p.relative_to(R26))]=hashlib.sha256(p.read_bytes()).hexdigest()
  prices=np.load(paths[0]);times=np.load(paths[1]);x=pd.read_pickle(paths[2]);assert np.array_equal(x.index.to_numpy(),times+STEP)
  x=long_features(x,prices,times)
  # Preserve only explicitly selected causal predictors; old outcome columns
  # never enter training matrices.
  out=x[BASE_FEATURES+BOOK_FEATURES+['book_valid','ret180','vol180','eff60']].copy()
  for h in HORIZONS:
   st=stop_fraction(x.atrfrac.to_numpy(),h);out['stop_'+str(h)]=st
   for side in [1,-1]:
    rr,dd=labels(prices,st,h,side);out[f'r_{h}_{side}']=rr;out[f'd_{h}_{side}']=dd.astype(np.int64)
  out.to_pickle(O/(s+'_features.pkl'));print('LABELS',s,len(out),flush=True)
 (R/'INPUT_HASHES.json').write_text(json.dumps(hashes,indent=2)+'\n')
 print('COMPLETE',flush=True)

if __name__=='__main__':prepare()
