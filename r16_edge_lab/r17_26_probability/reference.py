"""Frozen volume impulse rules, same public prices and same execution costs."""
import numpy as np,pandas as pd
from prepare import R,P,STEP,SYMS,ms

def make_reference(start,end):
 a=ms(start);b=ms(end);timeline=np.arange(a,b,STEP);features={};raw={}
 for sym in SYMS:
  v=np.load(R/'prepared'/(sym+'_prices.npy'));t=np.load(R/'prepared'/(sym+'_times.npy'));f=pd.DataFrame(v,index=t,columns=['open','high','low','close','quote_volume'])
  g=f.groupby(f.index//14400000*14400000).agg(dict(open='first',high='max',low='min',close='last',quote_volume='sum'))
  c=g.close;change=c/c.shift(6)-1;vol=g.quote_volume/g.quote_volume.shift().rolling(42).median();ema=c.ewm(span=50,adjust=False,min_periods=50).mean();liq=g.quote_volume.rolling(42).median()>=5e6
  tr=pd.concat([g.high-g.low,(g.high-c.shift()).abs(),(g.low-c.shift()).abs()],axis=1).max(axis=1)
  atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
  x=pd.DataFrame(dict(long=liq&(change>.04)&(change.shift()<=.04)&(vol>=2)&(c>g.open),short=liq&(change<-.04)&(change.shift()>=-.04)&(vol>=2)&(c<g.open),strength=change.abs(),stop=(2*atr/c).clip(.02,.12),btcside=np.where(c>c.rolling(180).mean(),1,-1)),index=g.index)
  x.index+=14400000;features[sym]=x
 btc=features['BTCUSDT'].btcside;signal=np.zeros((len(timeline),len(SYMS)),dtype=np.int8);stop=np.full(signal.shape,np.nan);strength=np.zeros(signal.shape)
 for si,sym in enumerate(SYMS):
  x=features[sym];sel=x.index.intersection(timeline);ix=((sel-a)//STEP).to_numpy(dtype=int)
  side=np.where(x.loc[sel,'long'],1,np.where(x.loc[sel,'short'],-1,0));side=np.where(side==btc.reindex(sel),side,0)
  signal[ix,si]=side;strength[ix,si]=x.loc[sel,'strength'];stop[ix,si]=x.loc[sel,'stop']
 return dict(signal=signal,stop=stop,strength=strength)
