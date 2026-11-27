"""Retrospective role-flow replay; not reconstruction of a trader's wallet."""
import json,gzip,hashlib,sys
from pathlib import Path
from collections import Counter
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parent
from copy_engine29 import get_data,replay
from data27 import R26,STEP,DAY,SYMS,ms,stop_fraction
from roles29 import classify
O=ROOT/'copy_results';O.mkdir(exist_ok=True)

def flow_arrays(f,index):
 # Row time is execution timestamp, rounded DOWN only for binning; the
 # resulting minute bucket is available at its CLOSE, never at its open.
 bucket=pd.to_datetime(f.time,utc=True).dt.floor('min')+pd.Timedelta(minutes=1)
 known=f.dir.isin(['Open Long','Open Short','Close Long','Close Short','Long > Short','Short > Long'])
 assert known.all(),'Unknown direction cannot be guessed'
 sign=f.dir.map({'Open Long':1,'Open Short':-1,'Close Long':-1,'Close Short':1,'Long > Short':-1,'Short > Long':1})
 opening=f.dir.map({'Open Long':1,'Open Short':-1}).fillna(0)
 vals=pd.DataFrame(dict(t=bucket,coin=f.coin,naive=sign*f.ntl,opening=opening*f.ntl,volume=f.ntl))
 out={}
 for kind in ['naive','opening']:
  sides=[];strength=[]
  for coin in ['BTC','ETH','SOL']:
   x=vals[vals.coin==coin].groupby('t')[[kind,'volume']].sum().reindex(index,fill_value=0)
   flow=x[kind].rolling(60,min_periods=60).sum();vol=x.volume.rolling(60,min_periods=60).sum();sides.append(np.sign(flow).fillna(0).to_numpy());strength.append((flow.abs()/vol.replace(0,np.nan)).fillna(0).to_numpy())
  out[kind]=(np.column_stack(sides).astype(np.int8),np.column_stack(strength))
 return out

def native_roles():
 out={}
 for wallet in ['bobby','winter']:
  p=ROOT.parent/'r17_28_trader_behavior/raw'/(wallet+'_recent_fills_all.json')
  if not p.exists():continue
  ff=json.loads(p.read_text());c=Counter();rows=[]
  for x in ff:
   if x.get('startPosition') is None:c['unknown_inventory']+=1;continue
   role=classify(x['startPosition'],x['side'],x['sz']);c['fills']+=1;c['buy_fills']+=x['side']=='B';c['buy_only_closing_short']+=x['side']=='B' and float(role['opening_quantity'])==0;c['buy_opens_long']+=role['observed_buy_is_new_long'];c['reversals']+=role['reversal'];c['maker_fills']+=not x['crossed']
   if len(rows)<20:rows.append(dict(coin=x['coin'],time=x['time'],side=x['side'],dir=x.get('dir'),**role))
  out[wallet]=dict(counts=dict(c),source_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),examples=rows,note='Capped recent native sample; not2years or independent profit evidence')
 (O/'NATIVE_ROLE_AUDIT.json').write_text(json.dumps(out,indent=2)+'\n')

def main():
 raw=ROOT.parent/'r17_28_trader_behavior/raw/bobby_2026-10.csv.gz';assert hashlib.sha256(raw.read_bytes()).hexdigest()=='ae9ddb381c62570c7fa0ed297feab7caff0c43eedadd9e332f84d4ba0eff6148'
 f=pd.read_csv(raw,usecols=['time','coin','dir','ntl']);f=f[f.coin.isin(['BTC','ETH','SOL'])].copy();a=ms('2026-10-01');b=ms('2026-11-01');index=pd.date_range('2026-10-01','2026-11-01',freq='min',tz='UTC',inclusive='left');flow=flow_arrays(f,index);ds=get_data('2026-10-01','2026-11-01');st=[]
 for s in SYMS:
  x=pd.read_pickle(R26/'prepared'/(s+'_features.pkl'));times=x.index.to_numpy();sel=(times>=a)&(times<b);assert np.array_equal(times[sel],index.astype('int64').to_numpy()//10**6);st.append(stop_fraction(x.atrfrac.to_numpy()[sel],60))
 stop=np.repeat(np.column_stack(st)[:,:,None],3,axis=2)
 btc=pd.read_pickle(ROOT/'prepared/BTCUSDT.pkl');reg=np.where((btc.gap_32.abs()>=1)&btc.trend_32.notna(),btc.trend_32,0);regime=pd.Series(reg,index=btc.index).reindex(index,method='ffill').to_numpy()
 results={}
 for name in ['naive_buy_sell','opening_risk_only','opening_with_regime']:
  side,strength=flow['naive' if name=='naive_buy_sell' else 'opening'];side=side.copy()
  if name=='opening_with_regime':side=np.where(side==regime[:,None],side,0).astype(np.int8)
  pred=dict(rule_side=side,stop=stop,strength=strength)
  for cost in [1,2]:
   key=name+'_cost'+str(cost);r,d,t,m,trace=replay(ds,pred,'rule_momentum',cost);r['fees']=sum(z['entry_fee']+z['exit_fee'] for z in t);r['funding']=sum(z['funding'] for z in t);results[key]=r
   (O/(key+'.json')).write_text(json.dumps(r,indent=2,allow_nan=False)+'\n');(O/(key+'_trades.csv.gz')).write_bytes(gzip.compress(pd.DataFrame(t).to_csv(index=False).encode(),mtime=0));np.save(O/(key+'_marks.npy'),m);pd.DataFrame(dict(timestamp=np.arange(a+DAY,b+1,DAY),equity=d)).to_csv(O/(key+'_daily.csv'),index=False)
   if cost==1:(O/(key+'_trace.jsonl.gz')).write_bytes(gzip.compress(pd.DataFrame(trace).to_json(orient='records',lines=True).encode(),mtime=0))
   print('COPY',key,'return',r['total_return'],'dd',r['max_drawdown'],'trades',r['trades'],flush=True)
 metadata=dict(period=['2026-10-01','2026-11-01'],selected_fill_rows=len(f),dir_counts=f.dir.value_counts().to_dict(),source_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),results=results,independent_holdout=False,promoted=False,opening_definition='Only OpenLong and OpenShort; reversals excluded due missingstartPosition',not_full_wallet=True,source_venue='Hyperliquid',execution_venue='Binance USDT-M',source_visibility_assumption='Every historical export fill assumed observable atminuteclose; no livefeedlatency/dropout guarantee')
 (O/'COPY_COMPARISON.json').write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n');native_roles();print('COPY COMPLETE',flush=True)

if __name__=='__main__':main()
