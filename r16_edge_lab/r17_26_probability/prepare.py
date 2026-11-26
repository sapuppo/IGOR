"""Causal features from public minute candles and actual depth snapshots."""
from pathlib import Path
import io,json,zipfile,hashlib,concurrent.futures
import numpy as np,pandas as pd
R=Path(__file__).resolve().parent;P=json.loads((R/'protocol.json').read_text());STEP=60000;DAY=1440*STEP
SYMS=P['symbols'];BASE_FEATURES=['ret1','ret3','ret8','ret20','ret60','distance20','distance60','vol20','vol60','atrfrac','high_distance','low_distance','flow1','flow5','flow20','volume_ratio','hour_sin','hour_cos']
BOOK_FEATURES=['imbalance02','imbalance1','log_depth02','book_age']
def ms(s):return int(pd.Timestamp(s,tz='UTC').timestamp()*1000)
def read(entry):
 raw=(R/'raw'/entry['file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==entry['sha256'],entry['file']
 with zipfile.ZipFile(io.BytesIO(raw)) as z:return pd.read_csv(z.open(z.namelist()[0]))
def book_frame(f):
 f=f[np.isclose(abs(f.percentage),.2)|np.isclose(abs(f.percentage),1)].copy()
 f['timestamp']=pd.to_datetime(f.timestamp,utc=True).astype('int64')//1000000+1000
 if f.duplicated(['timestamp','percentage']).any():
  assert f.groupby(['timestamp','percentage']).notional.nunique().max()==1,'conflicting depth duplicates'
  f=f.drop_duplicates(['timestamp','percentage'])
 q=f.pivot(index='timestamp',columns='percentage',values='notional').sort_index()
 for v in [-1.,-.2,.2,1.]:
  if v not in q:q[v]=np.nan
 q=q[[-1.,-.2,.2,1.]].dropna();q=q[(q>0).all(axis=1)]
 out=pd.DataFrame(index=q.index)
 out['imbalance02']=(q[-.2]-q[.2])/(q[-.2]+q[.2]);out['imbalance1']=(q[-1.]-q[1.])/(q[-1.]+q[1.]);out['log_depth02']=np.log1p(q[-.2]+q[.2])
 return out

def attach_book(decisions,book):
 ix=np.searchsorted(book.index.to_numpy(),decisions,side='left')-1
 safe=np.maximum(ix,0);age=decisions-book.index.to_numpy()[safe]
 valid=(ix>=0)&(age>0)&(age<=120000)
 vals=book.to_numpy()[safe].copy();vals[~valid]=np.nan
 return vals,age/1000,valid

def feature_frame(f,book=None):
 c=f.close;tr=pd.concat([f.high-f.low,(f.high-c.shift()).abs(),(f.low-c.shift()).abs()],axis=1).max(axis=1);atr=tr.ewm(alpha=1/14,adjust=False,min_periods=60).mean();ratio=atr/c
 x=pd.DataFrame(index=f.index+STEP);vals={}
 for n in [1,3,8,20,60]:vals['ret'+str(n)]=c.pct_change(n)
 vals.update(distance20=(c-c.ewm(span=20,adjust=False).mean())/atr,distance60=(c-c.ewm(span=60,adjust=False).mean())/atr,vol20=c.pct_change().rolling(20).std(),vol60=c.pct_change().rolling(60).std(),atrfrac=ratio,high_distance=(c-f.high.shift().rolling(20).max())/atr,low_distance=(c-f.low.shift().rolling(20).min())/atr,flow1=f.taker_buy_quote_volume/f.quote_volume.replace(0,np.nan),flow5=f.taker_buy_quote_volume.rolling(5).sum()/f.quote_volume.rolling(5).sum().replace(0,np.nan),flow20=f.taker_buy_quote_volume.rolling(20).sum()/f.quote_volume.rolling(20).sum().replace(0,np.nan),volume_ratio=f.quote_volume/f.quote_volume.shift().rolling(60).median().replace(0,np.nan))
 for k,v in vals.items():x[k]=v.to_numpy()
 hour=(x.index//STEP%1440)/1440*2*np.pi;x['hour_sin']=np.sin(hour);x['hour_cos']=np.cos(hour)
 x['stop_fraction']=np.clip(2*ratio.to_numpy(),.002,.008)
 if book is not None:
  values,age,valid=attach_book(x.index.to_numpy(),book)
  for j,k in enumerate(BOOK_FEATURES[:-1]):x[k]=values[:,j]
  x['book_age']=np.where(valid,age,np.nan);x['book_valid']=valid
 else:
  for k in BOOK_FEATURES:x[k]=np.nan
  x['book_valid']=False
 return x

def labels(prices,stop,horizon,side):
 """Entry at signal decision+1min. Raw row i closes at (i+1), entry i+2."""
 n=len(prices);entry=np.full(n,np.nan);entry[:-2]=prices[2:,0]
 result=np.full(n,np.nan);duration=np.full(n,horizon,dtype=np.int16);active=np.isfinite(entry)
 sl=entry*(1-side*stop);tp=entry*(1+side*2*stop)
 for k in range(horizon):
  shift=2+k;op=np.full(n,np.nan);hi=op.copy();lo=op.copy()
  op[:-shift]=prices[shift:,0];hi[:-shift]=prices[shift:,1];lo[:-shift]=prices[shift:,2]
  gs=active&(side*(op-sl)<=0);gt=active&(~gs)&(side*(op-tp)>=0)
  result[gs|gt]=side*(op[gs|gt]/entry[gs|gt]-1);duration[gs|gt]=max(1,k);active[gs|gt]=False
  sh=active&((lo<=sl) if side==1 else (hi>=sl));th=active&(~sh)&((hi>=tp) if side==1 else (lo<=tp))
  result[sh]=side*(sl[sh]/entry[sh]-1);result[th]=side*(tp[th]/entry[th]-1);duration[sh|th]=k+1;active[sh|th]=False
 shift=2+horizon;exitref=np.full(n,np.nan);exitref[:-shift]=prices[shift:,0]
 result[active]=side*(exitref[active]/entry[active]-1)
 return result/stop,duration

def main():
 manifest=json.loads((R/'manifest.json').read_text());out=R/'prepared';out.mkdir(exist_ok=True);coverage={}
 for sym in SYMS:
  entries=[x for x in manifest if x['symbol']==sym and x['status']=='verified']
  pieces=[read(e) for e in entries if e['kind']=='klines'];f=pd.concat(pieces,ignore_index=True).sort_values('open_time').set_index('open_time')
  f=f.loc[(f.index>=ms(P['ohlcv_start']))&(f.index<ms(P['end_exclusive']))]
  assert not f.index.has_duplicates and np.all(np.diff(f.index)==STEP),(sym,'candle gap/duplicate')
  assert np.isfinite(f[['open','high','low','close','quote_volume','taker_buy_quote_volume']]).all().all()
  assert (f.high>=f[['open','close','low']].max(axis=1)).all() and (f.low<=f[['open','close','high']].min(axis=1)).all()
  # Parse daily snapshots independently; retain their original information time.
  books=[]
  for e in entries:
   if e['kind']=='bookDepth':books.append(book_frame(read(e)))
  b=pd.concat(books).sort_index();assert not b.index.has_duplicates
  b.to_pickle(out/(sym+'_book.pkl'))
  x=feature_frame(f,b);sel=x.index>=ms(P['book_start']);coverage[sym]=dict(decisions=int(sel.sum()),book_valid=int(x.loc[sel,'book_valid'].sum()),book_fraction=float(x.loc[sel,'book_valid'].mean()),price_rows=len(f),snapshot_rows=len(b))
  prices=f[['open','high','low','close','quote_volume']].to_numpy();np.save(out/(sym+'_prices.npy'),prices);np.save(out/(sym+'_times.npy'),f.index.to_numpy())
  for h in P['horizons_minutes']:
   for side in [1,-1]:
    rr,dd=labels(prices,x.stop_fraction.to_numpy(),h,side);x[f'r_{h}_{side}']=rr;x[f'd_{h}_{side}']=dd
  x.to_pickle(out/(sym+'_features.pkl'))
  funds=[read(e).rename(columns={'calc_time':'fundingTime','last_funding_rate':'fundingRate'})[['fundingTime','fundingRate']] for e in entries if e['kind']=='fundingRate']
  raw=json.loads((R/f'funding_{sym}_2026_11.json').read_text());ff=pd.DataFrame(raw.get('result',raw) if isinstance(raw,dict) else raw)[['fundingTime','fundingRate']];funds.append(ff)
  fu=pd.concat(funds,ignore_index=True).sort_values('fundingTime');fu.fundingTime=fu.fundingTime.astype('int64');fu.fundingRate=fu.fundingRate.astype(float)
  assert not fu.fundingTime.duplicated().any()
  # Require funding coverage until last24h, no silent zero funding window.
  assert fu.fundingTime.min()<=ms(P['book_start'])+8*3600000 and fu.fundingTime.max()>=ms(P['end_exclusive'])-8*3600000
  fu.to_pickle(out/(sym+'_funding.pkl'));print('PREPARED',sym,coverage[sym],flush=True)
 (out/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
 print('COMPLETE',flush=True)
if __name__=='__main__':main()
