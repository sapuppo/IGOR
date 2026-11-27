"""Build causal hourly and four-hour features from verified raw bytes."""
from pathlib import Path
import json,hashlib,zipfile
import numpy as np,pandas as pd
R=Path(__file__).resolve().parent;P=json.loads((R/'protocol.json').read_text());SYMS=P['symbols'];HOUR=3600000;DAY=24*HOUR

def ms(s):return int(pd.Timestamp(s,tz='UTC').timestamp()*1000)
def read(e):
 p=R/'raw'/e['file'];assert hashlib.sha256(p.read_bytes()).hexdigest()==e['sha256']
 with zipfile.ZipFile(p) as z:return pd.read_csv(z.open(z.namelist()[0]))
def features(f):
 g=f.resample('4h',origin='epoch',closed='left',label='left').agg(dict(open='first',high='max',low='min',close='last',quote_volume='sum'));c=g.close;tr=pd.concat([g.high-g.low,(g.high-c.shift()).abs(),(g.low-c.shift()).abs()],axis=1).max(axis=1);atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean();o=pd.DataFrame(index=g.index)
 o['atr']=atr;o['stop']=(3*atr/c).clip(.01,.12);o['trail_frac']=(4*atr/c).clip(.01,.16);o['mom18']=c.pct_change(18);o['ret6']=c.pct_change(6);o['volume_ratio']=g.quote_volume/g.quote_volume.shift().rolling(42).median();o['liq']=g.quote_volume.rolling(42).median()>=5e6
 for fast,slow in [(32,96),(64,192)]:
  a=c.ewm(span=fast,adjust=False,min_periods=fast).mean();b=c.ewm(span=slow,adjust=False,min_periods=slow).mean();o[f'trend_{fast}']=np.sign(a-b);o[f'gap_{fast}']=(a-b)/atr
 for n in [36,72]:o[f'break_{n}']=np.where(c>g.high.shift().rolling(n).max(),1,np.where(c<g.low.shift().rolling(n).min(),-1,0));o[f'break_valid_{n}']=g.high.shift().rolling(n).max().notna()
 ema=c.ewm(span=50,adjust=False,min_periods=50).mean();change=c.pct_change(6);o['reference']=np.where(o.liq&(change>.04)&(change.shift()<=.04)&(o.volume_ratio>=2)&(c>g.open),1,np.where(o.liq&(change<-.04)&(change.shift()>=-.04)&(o.volume_ratio>=2)&(c<g.open),-1,0));o['ref_stop']=(2*atr/c).clip(.02,.12);o['ref_btc']=np.where(c>c.rolling(180).mean(),1,-1);o['ref_valid']=c.rolling(180).mean().notna()
 # Timestamp is information availability, never raw candle opening time.
 o.index=o.index+pd.Timedelta(hours=4)
 # Forward-fill only after the four-hour candle has closed.
 q=o.reindex(f.index,method='ffill')
 for n in [72,168]:q[f'rel_{n}']=f.close.pct_change(n).shift(1)/f.close.pct_change().rolling(n).std().shift(1)
 q['open']=f.open;q['high']=f.high;q['low']=f.low;q['close']=f.close;q['quote_volume']=f.quote_volume
 return q

def prepare():
 man=json.loads((R/'DATA_MANIFEST.json').read_text());errors=[x for x in man if x['status']!='verified' and x['frequency']=='monthly'];assert not errors,errors
 frames={};funds={};coverage={};hashes={};common_end=ms(P['data']['requested_end_exclusive']);start=ms(P['data']['start']);O=R/'prepared';O.mkdir(exist_ok=True)
 for s in SYMS:
  entries=[x for x in man if x['symbol']==s and x['kind']=='klines' and x['status']=='verified'];f=pd.concat([read(x) for x in entries]);t=f.open_time.to_numpy(dtype=np.int64);t=np.where(t>10**15,t//1000,t);f.index=pd.to_datetime(t,unit='ms',utc=True);f=f[['open','high','low','close','quote_volume']].astype(float).sort_index();assert not f.index.duplicated().any();assert int(f.index[0].timestamp()*1000)==start;common_end=min(common_end,int(f.index[-1].timestamp()*1000)+HOUR);frames[s]=f
  ff=pd.concat([read(x) for x in man if x['symbol']==s and x['kind']=='fundingRate' and x['status']=='verified']);ff=ff.rename(columns={'calc_time':'time','last_funding_rate':'rate'});nov=json.loads((R/(s+'_funding_november.json')).read_text());extra=pd.DataFrame([dict(time=x['fundingTime'],rate=float(x['fundingRate']),funding_interval_hours=8) for x in nov]);ff=pd.concat([ff[['time','rate','funding_interval_hours']],extra]).sort_values('time');assert not ff.time.duplicated().any();assert np.diff(ff.time.to_numpy()).max()<=9*HOUR;funds[s]=ff
 for s in SYMS:
  f=frames[s].loc[(frames[s].index>=pd.to_datetime(start,unit='ms',utc=True))&(frames[s].index<pd.to_datetime(common_end,unit='ms',utc=True))];t=f.index.astype('int64').to_numpy()//10**6;assert np.all(np.diff(t)==HOUR) and t[-1]+HOUR==common_end;assert (f[['open','high','low','close']]>0).all().all();assert (f.high>=f[['open','close','low']].max(axis=1)).all() and (f.low<=f[['open','close','high']].min(axis=1)).all();x=features(f);x.to_pickle(O/(s+'.pkl'));funds[s].to_pickle(O/(s+'_funding.pkl'));coverage[s]=dict(hours=len(f),first=int(t[0]),last=int(t[-1]),funding_events=int(((funds[s].time>=start)&(funds[s].time<common_end)).sum()))
  for p in [O/(s+'.pkl'),O/(s+'_funding.pkl')]:hashes[str(p.relative_to(R))]=hashlib.sha256(p.read_bytes()).hexdigest()
 out=dict(start=start,end_exclusive=common_end,requested_end_exclusive=ms(P['data']['requested_end_exclusive']),coverage=coverage,prepared_sha256=hashes,source_archive_count=sum(x['status']=='verified' for x in man),missing=[x for x in man if x['status']!='verified'],time_rule='4hfeatures available at4hclose, executable after1hour delay; no unfinished candles')
 (R/'DATA_COVERAGE.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
if __name__=='__main__':prepare()
