"""Preregistered continuous walk-forward; no broker/account access."""
import json,gzip,hashlib,time
from pathlib import Path
import numpy as np,pandas as pd
from data29 import R,P,SYMS,HOUR,DAY,ms
from policy29 import build
from engine29 import replay
O=R/'results';O.mkdir(exist_ok=True)

def save(key,out,start,end):
 r,d,tr,m,trace=out
 r['price_pnl_after_spread_slippage']=float(sum(x['side']*x['qty']*(x['exit_fill']-x['entry_fill']) for x in tr))
 r['turnover_notional']=float(sum(x['qty']*(x['entry_fill']+x['exit_fill']) for x in tr))
 (O/(key+'.json')).write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
 cols=['symbol','side','entry','exit','entry_fill','exit_fill','qty','entry_fee','exit_fee','funding','net','reason','hold_hours','policy','risk_fraction']
 (O/(key+'_trades.csv.gz')).write_bytes(gzip.compress(pd.DataFrame(tr,columns=cols).to_csv(index=False).encode(),mtime=0))
 pd.DataFrame(dict(timestamp=np.arange(start+DAY,end+1,DAY),equity=d)).to_csv(O/(key+'_daily.csv'),index=False)
 np.save(O/(key+'_marks.npy'),m)
 if key.endswith('cost1'):(O/(key+'_trace.jsonl.gz')).write_bytes(gzip.compress(pd.DataFrame(trace).to_json(orient='records',lines=True).encode(),mtime=0))
 return r

def setup():
 cov=json.loads((R/'DATA_COVERAGE.json').read_text());frames={s:pd.read_pickle(R/'prepared'/(s+'.pkl')) for s in SYMS};prices={s:frames[s][['open','high','low','close','quote_volume']].to_numpy() for s in SYMS};fund={}
 for s in SYMS:
  f=pd.read_pickle(R/'prepared'/(s+'_funding.pkl'));fund[s]={}
  for t,rate in zip(f.time,f.rate):fund[s].setdefault(int(t//HOUR*HOUR),[]).append((int(t),float(rate)))
 policies={name:build(frames,name) for name in P['candidates']+P['controls']};configs=[]
 for name in P['candidates']:
  for rf in P['risk']['research_risk_fractions']:
   key=name+'_r'+str(int(rf*10000));policies[key]={**policies[name],'base_name':name,'risk_fraction':rf};configs.append(key)
 return cov,frames,prices,fund,policies,configs

def subset(cov,prices,fund,policies,start,end):
 a=(start-cov['start'])//HOUR;b=(end-cov['start'])//HOUR
 ds=dict(start=start,end=end,prices={s:x[a:b] for s,x in prices.items()},funding=fund)
 ps={k:{z:(v[a:b] if isinstance(v,np.ndarray) else v) for z,v in x.items()} for k,x in policies.items()}
 return ds,ps

def halves(daily,start,mid):
 n=(mid-start)//DAY;return [float(daily[n-1]/10000-1),float(daily[-1]/daily[n-1]-1)]

def select_training(cov,prices,fund,policies,configs):
 folds=[];total=0;t0=time.time()
 for q in P['walk_forward']['test_quarters']:
  end=ms(q);start=ms(str((pd.Timestamp(q)-pd.DateOffset(months=6)).date()));mid=ms(str((pd.Timestamp(q)-pd.DateOffset(months=3)).date()));ds,ps=subset(cov,prices,fund,policies,start,end)
  ref=replay(ds,ps,[(start,'reference')],1)[0];rows={};eligible=[]
  for name in configs:
   normal=replay(ds,ps,[(start,name)],1);stress=replay(ds,ps,[(start,name)],2);total+=2
   h=halves(normal[1],start,mid);r=normal[0];pf=(r['profit_factor'] if r['profit_factor'] is not None else (float('inf') if r['profit_factor_infinite'] else 0))
   passed=bool(r['trades']>=20 and pf>1.1 and r['max_drawdown']<=.2 and min(h)>0 and stress[0]['total_return']>0 and r['total_return']>ref['total_return'])
   rows[name]=dict(normal=r,stress=stress[0],half_returns=h,eligible=passed)
   if passed:eligible.append(name)
  chosen=sorted(eligible,key=lambda x:(-rows[x]['normal']['total_return'],x))[0] if eligible else 'cash'
  folds.append(dict(test_start=end,train_start=start,train_end_exclusive=end,reference_return=ref['total_return'],selected=chosen,eligible=eligible,training=rows))
  print('TRAIN',q,'selected',chosen,'replays',total+len(folds),'seconds',round(time.time()-t0),flush=True)
 frozen=dict(folds=folds,protocol_sha256=hashlib.sha256((R/'protocol.json').read_bytes()).hexdigest(),continuous_replay_not_started=True)
 raw=json.dumps(frozen,indent=2,allow_nan=False)+'\n';(O/'SELECTION_FROZEN.json').write_text(raw)
 return folds,hashlib.sha256(raw.encode()).hexdigest()

def main():
 cov,frames,prices,fund,policies,configs=setup();folds,selection_hash=select_training(cov,prices,fund,policies,configs)
 start=ms('2025-01-01');end=cov['end_exclusive'];ds,ps=subset(cov,prices,fund,policies,start,end);results={}
 for name in configs+P['controls']+['selected_wfo']:
  schedule=[(x['test_start'],x['selected']) for x in folds] if name=='selected_wfo' else [(start,name)]
  for cost in [1,2]:
   key=name+'_cost'+str(cost);out=replay(ds,ps,schedule,cost);results[key]=save(key,out,start,end)
   print('TEST',key,'return',round(out[0]['total_return']*100,4),'dd',round(out[0]['max_drawdown']*100,4),'trades',out[0]['trades'],flush=True)
 selected=results['selected_wfo_cost1'];stress=results['selected_wfo_cost2']
 historical=bool(all(selected['yearly'].get(y,0)>0 for y in ['2025','2026']) and np.mean(list(selected['monthly'].values()))>=.05 and np.mean(list(stress['monthly'].values()))>=.05 and (selected['profit_factor'] or 0)>=1.2 and selected['sharpe']>=1 and selected['max_drawdown']<=.2 and selected['trades']>=100)
 out=dict(version='R17.29',start=start,end_exclusive=end,training_replays=8*33,test_replays=len(results),results=results,quarter_selections=[{k:v for k,v in f.items() if k!='training'} for f in folds],selection_sha256=selection_hash,historical_goal_passed=historical,prospective_confirmation=False,promoted=False,retrospective_research=True,source_archive_count=cov['source_archive_count'])
 (O/'COMPARISON.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print('COMPLETE',historical,flush=True)

if __name__=='__main__':main()
