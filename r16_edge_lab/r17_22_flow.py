"""Frozen causal flow/OI/funding rules. Missing inputs never become neutral values."""
from collections import defaultdict
import numpy as np,pandas as pd
BAR=14400000

def asof_values(times,source,value,max_age):
 if not source:return np.full(len(times),np.nan)
 q=pd.DataFrame(source).sort_values('timestamp');assert not q.timestamp.duplicated().any()
 ts=q.timestamp.to_numpy(dtype='int64');vals=q[value].to_numpy(dtype=float)
 loc=np.searchsorted(ts,np.asarray(times,dtype='int64'),side='left')-1
 safe=np.maximum(loc,0);out=vals[safe].copy();out[(loc<0)|(np.asarray(times)-ts[safe]>max_age)]=np.nan
 return out

def signals(data,rates,oi,mode,start,end):
 maps={(6,side):defaultdict(list) for side in [1,-1]}
 for sym,f in data.items():
  t=f.index.to_numpy()+BAR;c=f.close
  flow=f.taker_buy_quote_volume.rolling(6,min_periods=6).sum()/f.quote_volume.rolling(6,min_periods=6).sum()
  ret=c/c.shift(6)-1;liquid=f.quote_volume.rolling(42,min_periods=42).median()>=5e6
  funding=asof_values(t,rates[sym],'rate',16*3600000)
  if mode=='flow_oi_funding':
   cur=asof_values(t,oi.get(sym,[]),'oi',8*3600000);past=asof_values(t-24*3600000,oi.get(sym,[]),'oi',8*3600000);growth=cur/past-1
  for side in [1,-1]:
   raw=(side*ret>=.02)&(side*(flow-.5)>=.05)&liquid
   mask=raw&~raw.shift(fill_value=False)
   if mode in ['flow_funding','flow_oi_funding']:mask&=np.isfinite(funding)&(side*funding<=.0003)
   if mode=='flow_oi_funding':mask&=np.isfinite(growth)&(growth>=.01)
   for ts,strength in abs(ret[mask]).items():
    entry=int(ts)+BAR
    if start<=entry<end:maps[6,side][entry].append((sym,side,float(strength)))
 for m in maps.values():
  for t in m:m[t].sort(key=lambda x:(-x[2],x[0]))
 return maps
