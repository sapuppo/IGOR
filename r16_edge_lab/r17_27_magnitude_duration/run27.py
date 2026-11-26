"""Registered rolling comparison; never sends orders. python run27.py"""
import os,json,hashlib,gzip
os.environ.setdefault('OMP_NUM_THREADS','4');os.environ.setdefault('OPENBLAS_NUM_THREADS','4')
import numpy as np,pandas as pd
from data27 import R,P,STEP,DAY,SYMS,ms
from models27 import train_fold
from engine27 import replay,get_data,summary
from reference import make_reference
O=R/'results';O.mkdir(exist_ok=True)
VARIANTS=P['variants']+P['diagnostic_horizon_ablations'];CANDIDATES=P['variants'][:7]

def save(key,result,start,end):
 r,d,t,m,trace=result
 r['gross_price_pnl']=float(sum(x['side']*x['qty']*(x['exit_fill']-x['entry_fill']) for x in t));r['turnover_notional']=float(sum(x['qty']*(x['entry_fill']+x['exit_fill']) for x in t))
 (O/(key+'.json')).write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
 cols=['symbol','side','entry','exit','entry_fill','exit_fill','qty','entry_fee','exit_fee','funding','net','reason','hold_minutes','predicted_probability','predicted_ev','rank','horizon']
 (O/(key+'_trades.csv.gz')).write_bytes(gzip.compress(pd.DataFrame(t,columns=cols).to_csv(index=False).encode(),mtime=0))
 pd.DataFrame(dict(timestamp=np.arange(start+DAY,end+1,DAY),equity=d)).to_csv(O/(key+'_daily.csv'),index=False);np.save(O/(key+'_marks.npy'),m)
 if key.endswith('_cost1'):(O/(key+'_decision_trace.jsonl.gz')).write_bytes(gzip.compress(pd.DataFrame(trace).to_json(orient='records',lines=True).encode(),mtime=0))
 print(key,json.dumps({k:r[k] for k in ['total_return','max_drawdown','profit_factor','trades']}),flush=True);return r

def evaluate(month,pred,meta):
 start=month+'-01';end=pd.Timestamp(meta['end'],unit='ms',tz='UTC').strftime('%Y-%m-%d');ds=get_data(start,end);out={};refpred=make_reference(start,end)
 for variant in VARIANTS:
  for cost in [1,2]:
   key=f'{month}_{variant}_cost{cost}';result=replay(ds,refpred if variant=='reference' else pred,variant,cost,reference=variant=='reference');out[key]=save(key,result,ms(start),ms(end))
 return out

def aggregate(results,months,variant,cost):
 equity=10000.;daily=[];trades=[];marks=[]
 for month in months:
  key=f'{month}_{variant}_cost{cost}';d=pd.read_csv(O/(key+'_daily.csv'));t=pd.read_csv(O/(key+'_trades.csv.gz'));m=np.load(O/(key+'_marks.npy'));scale=equity/10000
  daily.extend((d.equity*scale).tolist());marks.extend((m*scale).tolist())
  for col in ['qty','entry_fee','exit_fee','funding','net']:t[col]*=scale
  trades.extend(t.to_dict('records'));equity=float(d.equity.iloc[-1])*scale
 start=ms(months[0]+'-01');end=min(ms(str((pd.Period(months[-1])+1).start_time.date())),ms(P['final_period'][1]));out=summary(daily,trades,np.array(marks),start,end)
 out['positive_folds']=sum(results[f'{m}_{variant}_cost{cost}']['total_return']>0 for m in months);out['fees']=float(sum(t['entry_fee']+t['exit_fee'] for t in trades));out['funding']=float(sum(t['funding'] for t in trades));out['price_pnl_after_spread_slippage']=float(sum(t['side']*t['qty']*(t['exit_fill']-t['entry_fill']) for t in trades));out['trades_by_horizon']={str(h):sum(t['horizon']==h for t in trades) for h in [30,60,180,10080]};return out

def paired_bootstrap(months,left,right):
 def daily(v):
  rr=[]
  for m in months:
   a=np.r_[10000,pd.read_csv(O/f'{m}_{v}_cost1_daily.csv').equity];rr.extend(a[1:]/a[:-1]-1)
  return np.asarray(rr)
 l=daily(left);r=daily(right);rng=np.random.default_rng(27);values=[]
 for _ in range(500):
  ix=np.concatenate([(np.arange(7)+j)%len(l) for j in rng.integers(0,len(l),size=(len(l)+6)//7)])[:len(l)];values.append(float(np.prod(1+l[ix])-np.prod(1+r[ix])))
 return dict(left=left,right=right,days=len(l),block_days=7,paths=500,total_return_difference_95_interval=np.percentile(values,[2.5,97.5]).tolist(),note='Descriptive paired interval; not adjusted for research selection or repeated use of these dates.')

def main():
 results={};models={}
 for month in P['walk_forward_months']:
  pred,meta=train_fold(month);models[month]=meta;results.update(evaluate(month,pred,meta))
 combined={f'walk_forward_{v}_cost{c}':aggregate(results,P['walk_forward_months'],v,c) for v in VARIANTS for c in [1,2]};choices=[]
 for v in CANDIDATES:
  x=combined[f'walk_forward_{v}_cost1'];s=combined[f'walk_forward_{v}_cost2'];control=combined['walk_forward_reference_cost1']
  if (x['profit_factor'] or 0)>1.2 and x['trades']>=100 and x['positive_folds']>=3 and x['max_drawdown']<=.2 and s['total_return']>0 and x['total_return']>control['total_return']:choices.append(v)
 selected=sorted(choices,key=lambda v:(-combined[f'walk_forward_{v}_cost1']['total_return'],v))[0] if choices else 'cash';frozen=dict(selected=selected,choices=choices,walk_forward_results=combined,november_models_not_generated=True,independent_research_holdout=False)
 raw=json.dumps(frozen,sort_keys=True,indent=2)+'\n';(O/'selection_before_final.json').write_text(raw);selectionsha=hashlib.sha256(raw.encode()).hexdigest();print('SELECTION_FROZEN',selected,selectionsha,flush=True)
 pred,meta=train_fold('2026-11');models['2026-11']=meta;results.update(evaluate('2026-11',pred,meta))
 for v in VARIANTS:
  for c in [1,2]:combined[f'final_{v}_cost{c}']=aggregate(results,['2026-11'],v,c)
 pairs=[('magnitude_price','mean_payoff_price'),('duration_price','magnitude_price'),('duration_book','duration_price'),('direct_book','duration_book'),('conservative_book','direct_book'),('duration_book','duration_book_no_adaptive')]
 report=dict(version='R17.27',results=results,combined=combined,models=models,selected=selected,selection_sha256=selectionsha,paired_bootstrap=[paired_bootstrap(P['walk_forward_months'],a,b) for a,b in pairs],historical_goal_passed=False,promoted=False,independent_research_holdout=False,protocol_sha256=hashlib.sha256((R/'protocol.json').read_bytes()).hexdigest())
 if selected!='cash':
  passed=True
  for c in [1,2]:
   w=combined[f'walk_forward_{selected}_cost{c}'];control=combined[f'walk_forward_reference_cost{c}'];f=combined[f'final_{selected}_cost{c}'];passed &= w['monthly_equivalent']>=.05 and w['total_return']>control['total_return'] and w['sharpe']>=1 and (w['profit_factor'] or 0)>=1.2 and f['total_return']>0
  report['historical_goal_passed']=bool(passed)
 (O/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('COMPLETE',selected,report['historical_goal_passed'],flush=True)
if __name__=='__main__':main()
