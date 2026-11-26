"""End-to-end registered comparison. No live orders or account credentials."""
from pathlib import Path
import os,json,hashlib,gzip,pickle
os.environ.setdefault('OMP_NUM_THREADS','4');os.environ.setdefault('OPENBLAS_NUM_THREADS','4')
import numpy as np,pandas as pd
from prepare import R,P,STEP,DAY,SYMS,ms
from train import train_fold,sample,PARAMS
from execution import replay,get_data,summary
from reference import make_reference
from probability import train_model,predict,calibration_metrics
O=R/'results';O.mkdir(exist_ok=True)
VARIANTS=P['variants']

def save(key,result):
 r,d,t,m,trace=result
 (O/(key+'.json')).write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
 cols=['symbol','side','entry','exit','entry_fill','exit_fill','qty','entry_fee','exit_fee','funding','net','reason','hold_minutes','predicted_probability','predicted_ev','rank','horizon']
 raw=pd.DataFrame(t,columns=cols).to_csv(index=False).encode();(O/(key+'_trades.csv.gz')).write_bytes(gzip.compress(raw,mtime=0))
 start=r.pop('_start');end=r.pop('_end')
 pd.DataFrame(dict(timestamp=np.arange(start+DAY,end+1,DAY),equity=d)).to_csv(O/(key+'_daily.csv'),index=False)
 np.save(O/(key+'_marks.npy'),m)
 if key.endswith('_cost1'):
  raw=pd.DataFrame(trace).to_json(orient='records',lines=True).encode();(O/(key+'_decision_trace.jsonl.gz')).write_bytes(gzip.compress(raw,mtime=0))
 print(key,json.dumps({k:r[k] for k in ['monthly_equivalent','max_drawdown','sharpe','profit_factor','trades']}),flush=True)
 return r

def evaluate(month,pred,meta):
 start=pd.Period(month).start_time.strftime('%Y-%m-%d');end=min(pd.Period(month).end_time.normalize()+pd.Timedelta(days=1),pd.Timestamp(P['end_exclusive'])).strftime('%Y-%m-%d')
 ds=get_data(start,end);out={}
 for variant in VARIANTS+['reference']:
  ref=variant=='reference';x=make_reference(start,end) if ref else pred
  for cost in [1,2]:
   key=f'{month}_{variant}_cost{cost}';result=replay(ds,x,variant,cost,reference=ref);result[0]['_start']=ms(start);result[0]['_end']=ms(end);out[key]=save(key,result)
 return out

def aggregate(results,months,variant,cost):
 equity=10000.;daily=[];trades=[];marks=[]
 for month in months:
  key=f'{month}_{variant}_cost{cost}';d=pd.read_csv(O/(key+'_daily.csv'));t=pd.read_csv(O/(key+'_trades.csv.gz'));m=np.load(O/(key+'_marks.npy'));scale=equity/10000
  daily.extend((d.equity*scale).tolist());marks.extend((m*scale).tolist())
  for col in ['qty','entry_fee','exit_fee','funding','net']:t[col]*=scale
  trades.extend(t.to_dict('records'));equity=float(d.equity.iloc[-1])*scale
 start=ms(months[0]+'-01');last=months[-1];end=min(ms((pd.Period(last)+1).start_time.strftime('%Y-%m-%d')),ms(P['end_exclusive']))
 out=summary(daily,trades,np.array(marks),start,end)
 out['positive_folds']=sum(results[f'{m}_{variant}_cost{cost}']['total_return']>0 for m in months)
 return out

def shuffle_sanity():
 frames={s:pd.read_pickle(R/'prepared'/(s+'_features.pkl')) for s in SYMS}
 X,rr,dd,ts=sample(frames,ms('2026-04-01'),ms('2026-06-01'),8,True);Xc,rc,dc,tc=sample(frames,ms('2026-06-01'),ms('2026-07-01'),8,True)
 rng=np.random.default_rng(26);y=(rr>0).astype(int);shuffled=rng.permutation(y);model,cal=train_model(X,shuffled,Xc,(rc>0).astype(int),PARAMS)
 Xe,re,de,te=sample(frames,ms('2026-07-01'),ms('2026-08-01'),8,True,stride=8);raw,p=predict(model,cal,Xe)
 return dict(method='one fixed-seed label permutation; calibration unchanged; not a strategy-search permutation p-value',diagnostics=calibration_metrics((re>0).astype(int),p,float((rc>0).mean())))

def main():
 results={};models={}
 for month in P['walk_forward_months']:
  pred,meta=train_fold(month);models[month]=meta;results.update(evaluate(month,pred,meta))
 combined={}
 for variant in VARIANTS+['reference']:
  for cost in [1,2]:combined[f'walk_forward_{variant}_cost{cost}']=aggregate(results,P['walk_forward_months'],variant,cost)
 choices=[]
 for v in VARIANTS:
  x=combined[f'walk_forward_{v}_cost1'];stress=combined[f'walk_forward_{v}_cost2']
  if x['profit_factor'] is not None and x['profit_factor']>1 and x['trades']>=100 and x['max_drawdown']<=.20 and x['positive_folds']>=3 and stress['total_return']>0:choices.append(v)
 selected=sorted(choices,key=lambda v:(-combined[f'walk_forward_{v}_cost1']['total_return'],v))[0] if choices else 'cash'
 freeze=dict(selected=selected,choices=choices,walk_forward_results=combined,holdout_predictions_not_generated=True)
 raw=json.dumps(freeze,sort_keys=True,indent=2)+'\n';(O/'selection_before_final.json').write_text(raw);sha=hashlib.sha256(raw.encode()).hexdigest();print('SELECTION_FROZEN',selected,sha,flush=True)
 # Final November outcomes cannot alter family selection or any hyperparameter.
 pred,meta=train_fold('2026-11');models['2026-11']=meta;results.update(evaluate('2026-11',pred,meta))
 for variant in VARIANTS+['reference']:
  for cost in [1,2]:combined[f'final_{variant}_cost{cost}']=aggregate(results,['2026-11'],variant,cost)
 sanity=shuffle_sanity()
 bootstrap={};rng=np.random.default_rng(26)
 for variant in ([selected] if selected!='cash' else [])+['reference']:
  d=np.concatenate([pd.read_csv(O/f'{m}_{variant}_cost1_daily.csv').equity.to_numpy()/10000 for m in []]) if False else []
  returns=[]
  for m in P['walk_forward_months']:
   v=np.r_[10000,pd.read_csv(O/f'{m}_{variant}_cost1_daily.csv').equity.to_numpy()];returns.extend(v[1:]/v[:-1]-1)
  r=np.array(returns);paths=[]
  for _ in range(500):
   idx=np.concatenate([(np.arange(7)+j)%len(r) for j in rng.integers(0,len(r),size=(len(r)+6)//7)])[:len(r)];paths.append(float(np.prod(1+r[idx])-1))
  bootstrap[variant]=dict(block_days=7,paths=500,total_return_95_interval=list(np.percentile(paths,[2.5,97.5])),note='descriptive selected-policy interval; not adjusted for multi-variant selection')
 report=dict(version='R17.26',results=results,combined=combined,models=models,selected=selected,selection_sha256=sha,shuffle_sanity=sanity,block_bootstrap=bootstrap,goal_achieved=False,promoted=False,protocol_sha256=hashlib.sha256((R/'protocol.json').read_bytes()).hexdigest())
 if selected!='cash':
  passed=True
  for cost in [1,2]:
   w=combined[f'walk_forward_{selected}_cost{cost}'];c=combined[f'walk_forward_reference_cost{cost}'];f=combined[f'final_{selected}_cost{cost}']
   passed &= w['monthly_equivalent']>=.05 and w['total_return']>c['total_return'] and w['sharpe']>=1 and (w['profit_factor'] or 0)>=1.2 and f['total_return']>0
  # Brier gate tested on the calibrated binary model used, not only PnL.
  typ='price' if selected=='price_only_turnover_kalman' else 'book'
  passed &= all(d['diagnostics'][f'{h}_{typ}']['calibrated']['brier']<=d['diagnostics'][f'{h}_{typ}']['calibrated']['constant_prior_brier'] for d in models.values() for h in [8,20])
  report['goal_achieved']=bool(passed)
 (O/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('COMPLETE',selected,report['goal_achieved'],flush=True)
if __name__=='__main__':main()
