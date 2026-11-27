"""Fixed, causal strategy hypotheses. Not original traders' secret rules."""
import numpy as np,pandas as pd
from data29 import P,SYMS,HOUR

def build(frames,name):
 n=len(frames[SYMS[0]]);shape=(n,len(SYMS));side=np.zeros(shape,np.int8);gate=np.zeros(shape,np.int8);score=np.zeros(shape);stop=np.column_stack([frames[s].stop for s in SYMS]);trail=np.column_stack([frames[s].trail_frac for s in SYMS]);btc=frames['BTCUSDT'];reg=np.where((btc.gap_32.abs()>=1)&btc.trend_32.notna(),btc.trend_32,0)
 if name in ['buy_hold','short_hold']:
  side[:,:3]=1 if name=='buy_hold' else -1;gate[:]=9;score[:,:3]=1
 elif name=='cash':gate[:]=9
 elif name=='reference':
  gate[:]=9
  for si,s in enumerate(SYMS[:3]):
   f=frames[s];side[:,si]=np.where((f.reference==btc.ref_btc)&btc.ref_valid,f.reference,0);score[:,si]=f.ret6.abs().fillna(0);stop[:,si]=f.ref_stop
 elif name.startswith('relative_'):
  look=int(name.split('_')[-1]);rr=np.column_stack([frames[s][f'rel_{look}'] for s in SYMS])
  for i,row in enumerate(rr):
   valid=np.isfinite(row)
   if valid.any():
    hi=int(np.argmax(np.where(valid,row,-np.inf)));lo=int(np.argmin(np.where(valid,row,np.inf)))
    if row[hi]>0:side[i,hi]=1;score[i,hi]=abs(row[hi])
    if row[lo]<0:side[i,lo]=-1;score[i,lo]=abs(row[lo])
  gate=side.copy()
 else:
  for si,s in enumerate(SYMS):
   f=frames[s];tr=f.trend_64 if name.startswith('breakout_') or name=='regime_breakout' else f.trend_32
   if name=='trend_64_192':tr=f.trend_64
   valid=np.isfinite(tr)&np.isfinite(f.stop)&np.isfinite(f.mom18);target=np.where(valid&(np.sign(f.mom18)==tr),tr,0);holding=target.copy()
   if name.startswith('breakout_') or name=='regime_breakout':
    look=int(name.split('_')[-1]) if name.startswith('breakout_') else 72;br=f[f'break_{look}'];target=np.where(valid&(br==tr)&(br!=0),br,0);holding=np.where(valid,tr,0)
   if name.startswith('regime_'):
    target=np.where(target==reg,target,0);holding=np.where(holding==reg,holding,0)
   side[:,si]=target;gate[:,si]=holding;score[:,si]=np.where(valid,np.abs(f.gap_64 if name.startswith('breakout_') or name in ['trend_64_192','regime_breakout'] else f.gap_32),0)
 # No negative warm-up artefacts and no use of any bar not already available.
 side[~np.isfinite(stop)]=0;score=np.nan_to_num(score,nan=0,posinf=0,neginf=0)
 return dict(side=side,gate=gate,score=score,stop=stop,trail=trail,name=name)
