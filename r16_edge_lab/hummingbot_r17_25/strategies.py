"""Independent causal adaptations; provenance and deviations in protocol.json."""
import numpy as np
import pandas as pd

def smooth(x,n,alpha):
 out=pd.Series(np.nan,index=x.index);v=x.dropna().copy()
 if len(v)<n:return out
 v.iloc[:n-1]=np.nan;v.iloc[n-1]=x.dropna().iloc[:n].mean()
 out.loc[v.index]=v.ewm(alpha=alpha,adjust=False).mean()
 return out

def features(f):
 c=f.close;prev=c.shift();tr=pd.concat([f.high-f.low,(f.high-prev).abs(),(f.low-prev).abs()],axis=1).max(axis=1)
 atr=smooth(tr,14,1/14);a20=smooth(tr,20,1/20)
 upper=((f.high+f.low)/2+4*a20).to_numpy();lower=((f.high+f.low)/2-4*a20).to_numpy()
 direction=np.zeros(len(f));cl=c.to_numpy()
 for i in range(20,len(f)):
  if cl[i]>upper[i-1]:direction[i]=1
  elif cl[i]<lower[i-1]:direction[i]=-1
  else:
   direction[i]=direction[i-1] or 1
   if direction[i]>0:lower[i]=max(lower[i],lower[i-1])
   else:upper[i]=min(upper[i],upper[i-1])
 macd=smooth(c,21,2/22)-smooth(c,42,2/43);hist=macd-smooth(macd,9,2/10)
 # Whole-series mean/std would leak future information. Every row has its own
 # trailing normalization window; a zero variance yields no quote skew.
 z=(-(macd-macd.rolling(142).mean())/macd.rolling(142).std()).clip(-3,3).fillna(0)
 natr=atr/c;ref=c*(1+(.5*z+.5*np.where(hist>0,1,-1))*natr/2)
 momentum=c/c.shift(42)-1;eff=(c-c.shift(42)).abs()/c.diff().abs().rolling(42).sum().replace(0,np.nan)
 out=pd.DataFrame(dict(close=c,atr=atr,natr=natr,st=direction,mom=momentum,eff=eff,reference=ref,liq=f.quote_volume.rolling(42).median()>=5e6),index=f.index)
 for n in (20,55):
  out['long'+str(n)]=(c>f.high.shift().rolling(n).max())&(momentum>0)&(direction==1)
  out['short'+str(n)]=(c<f.low.shift().rolling(n).min())&(momentum<0)&(direction==-1)
 out['long0']=(momentum>0)&(momentum.shift()<=0)&(direction==1)
 out['short0']=(momentum<0)&(momentum.shift()>=0)&(direction==-1)
 change=c/c.shift(6)-1;vr=f.quote_volume/f.quote_volume.shift().rolling(42).median()
 out['control_long']=(change>.04)&(change.shift()<=.04)&(vr>=2)&(c>f.open)
 out['control_short']=(change<-.04)&(change.shift()>=-.04)&(vr>=2)&(c<f.open)
 out['btc_side']=np.where(c>c.rolling(180).mean(),1,-1)
 return out

def intent(row,spec,btc_side):
 if not row['liq'] or not np.isfinite(row['atr']) or row['atr']<=0:return ('cash',0)
 fam=spec['family']
 if fam=='control':
  for side,col in [(1,'control_long'),(-1,'control_short')]:
   if row[col] and side==btc_side:return ('trend',side)
  return ('cash',0)
 if fam=='hybrid':
  if row['eff']<=.20:return ('pmm',0) if spec['spread_atr'] else ('cash',0)
  if row['eff']<.35 or not np.isfinite(row['eff']):return ('cash',0)
 if fam=='pmm':return ('pmm',0)
 n=str(spec['breakout'])
 if row['long'+n]:return ('trend',1)
 if row['short'+n]:return ('trend',-1)
 return ('cash',0)
