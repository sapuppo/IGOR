"""Run finite training/validation protocol; all outcomes retained, no live orders."""
from pathlib import Path
import json,hashlib,time,gzip,sys
import numpy as np,pandas as pd
from data import load,ms,DAY,SYMS
from engine import replay,metrics
R=Path(__file__).resolve().parent;O=R/'results';O.mkdir(exist_ok=True)
P=json.loads((R/'protocol.json').read_text());CONTROL=dict(id='control',family='control',breakout=20,spread_atr=1)

def save(key,result):
 r,d,t=result
 marks=r.pop('intraday_details',None)
 if key.startswith('validation'):
  if marks is None:marks=[dict(timestamp=v,equity=10000.) for v in range(d[0]['timestamp']-DAY+900000,d[-1]['timestamp']+1,900000)]
  raw=pd.DataFrame(marks).to_csv(index=False).encode();compressed=gzip.compress(raw,mtime=0)
  assert gzip.decompress(compressed)==raw
  tmp=O/(key+'_intraday.tmp');tmp.write_bytes(compressed);tmp.replace(O/(key+'_intraday.csv.gz'))
 pd.DataFrame(d).to_csv(O/(key+'_daily.csv'),index=False)
 pd.DataFrame(t,columns=['symbol','entry','exit','side','qty','entry_fill','exit_fill','entry_fee','exit_fee','funding','net','reason','mode','regime']).to_csv(O/(key+'_trades.csv'),index=False)
 (O/(key+'.json')).write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
 print(key,json.dumps({k:r[k] for k in ['monthly_equivalent','max_15m_dd','sharpe','profit_factor','trades']}),flush=True)
 return r

def eligible(r):return r['trades']>=20 and r['total_return']>0 and (r['profit_factor'] or 0)>1 and r['max_15m_dd']<.20

def score(r):return r['total_return']/max(r['max_15m_dd'],.01)

def main():
 ds=load(False);print('HISTORICAL_HASHES_OK',len(ds['hashes']),flush=True)
 (O/'input_hashes_historical.json').write_text(json.dumps(ds['hashes'],indent=2)+'\n')
 full={};training={};selection={};validation={}
 for spec in P['candidates']+[CONTROL]:
  for cost in [1,2]:
   key='historical_'+spec['id']+'_cost'+str(cost)
   full[key]=save(key,replay(ds,spec,ms(P['training_start']),ms(P['historical_end']),cost,adaptive=spec['id']!='control'))
 # Fixed windows: train twelve months, purge the final seven days, evaluate
 # six months (last holdout two months). Each replay starts flat at 10,000.
 for j,(a,b,c) in enumerate(P['folds']):
  training[str(j)]={};selection[str(j)]={}
  for spec in P['candidates']:
   r=save(f'train{j}_'+spec['id'],replay(ds,spec,ms(a),ms(b)-7*DAY))
   training[str(j)][spec['id']]=r
  for family in ['trend','pmm','hybrid']:
   choices=[s for s in P['candidates'] if s['family']==family and eligible(training[str(j)][s['id']])]
   selected=sorted(choices,key=lambda s:(-score(training[str(j)][s['id']]),s['id']))[0] if choices else None
   selection[str(j)][family]=selected
 # Freeze selections before even parsing holdout prices. A researcher cannot
 # make a new choice from validation or stress performance.
 frozen=json.dumps(selection,indent=2,sort_keys=True)+'\n';(O/'selection_frozen.json').write_text(frozen)
 selhash=hashlib.sha256(frozen.encode()).hexdigest();print('SELECTION_FROZEN',selhash,selection['5'],flush=True)
 (O/'selection_freeze.json').write_text(json.dumps(dict(sha256=selhash,unix_time=time.time(),holdout_not_loaded=True),indent=2)+'\n')
 for j,(a,b,c) in enumerate(P['folds']):
  if j==5:
   ds=load(True);(O/'input_hashes_with_holdout.json').write_text(json.dumps(ds['hashes'],indent=2)+'\n')
  for family in ['trend','pmm','hybrid','control']:
   spec=CONTROL if family=='control' else selection[str(j)][family]
   for cost in [1,2]:
    key=f'validation{j}_{family}_cost{cost}'
    if spec is None:
     d=[dict(timestamp=t,equity=10000.) for t in range(ms(b)+DAY,ms(c)+1,DAY)];r=metrics(d,[]);r.update(max_15m_dd=0.,stats={},halted=False,selected='cash');result=r,d,[]
    else:
     result=replay(ds,spec,ms(b),ms(c),cost,adaptive=family!='control');result[0]['selected']=spec['id']
    validation[key]=save(key,result)
 finalize(full,training,selection,validation,selhash)

def finalize(full,training,selection,validation,selhash):
 combined={}
 for family in ['trend','pmm','hybrid','control']:
  for cost in [1,2]:
   for label,folds in [('walk_forward',range(5)),('holdout',[5])]:
    equity=10000.;daily=[];trades=[];marks=[]
    for j in folds:
     key=f'validation{j}_{family}_cost{cost}';d=pd.read_csv(O/(key+'_daily.csv'));t=pd.read_csv(O/(key+'_trades.csv'));scale=equity/10000
     intr=pd.read_csv(O/(key+'_intraday.csv.gz'));marks.extend((intr.equity*scale).tolist())
     d.equity*=scale
     for col in ['qty','entry_fee','exit_fee','funding','net']:t[col]*=scale
     daily+=d.to_dict('records');trades+=t.to_dict('records');equity=float(d.equity.iloc[-1])
    # Daily chained drawdown is computed globally, including cross-fold peaks.
    m=metrics(daily,trades);m['max_fold_15m_dd']=max(validation[f'validation{j}_{family}_cost{cost}']['max_15m_dd'] for j in folds)
    v=np.r_[10000.,marks];m['max_15m_dd']=float((1-v/np.maximum.accumulate(v)).max())
    key=f'{label}_{family}_cost{cost}';combined[key]=m
    pd.DataFrame(daily).to_csv(O/(key+'_daily.csv'),index=False);pd.DataFrame(trades,columns=['symbol','entry','exit','side','qty','entry_fill','exit_fill','entry_fee','exit_fee','funding','net','reason','mode','regime']).to_csv(O/(key+'_trades.csv'),index=False)
 passes=[]
 for family in ['trend','pmm','hybrid']:
  ok=True
  for cost in [1,2]:
   w=combined[f'walk_forward_{family}_cost{cost}'];h=combined[f'holdout_{family}_cost{cost}'];ctrl=combined[f'walk_forward_control_cost{cost}']
   ok &= w['monthly_equivalent']>=.05 and w['total_return']>ctrl['total_return'] and w['max_15m_dd']<=.20 and w['sharpe']>=1 and (w['profit_factor'] or 0)>=1.2 and w['trades']>=100 and h['total_return']>0
   ok &= sum(validation[f'validation{j}_{family}_cost{cost}']['total_return']>0 for j in range(5))>=4
  if ok:passes.append(family)
 report=dict(version='R17.25-HB',full=full,training=training,selection=selection,selection_sha256=selhash,validation=validation,combined=combined,passes_promotion_gates=passes,live_promotion=False,walk_forward_note='Historical periods previously consulted in earlier research; only Jul-Aug2026 withheld from this study until selection frozen; not prospective live OOS',protocol_sha256=hashlib.sha256((R/'protocol.json').read_bytes()).hexdigest())
 (O/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('COMPLETE',passes,flush=True)
if __name__=='__main__':
 if '--finalize' in sys.argv:
  get=lambda f:json.loads(f.read_text())
  full={f.stem:get(f) for f in O.glob('historical_*.json')}
  training={str(j):{s['id']:get(O/(f'train{j}_'+s['id']+'.json')) for s in P['candidates']} for j in range(6)}
  selection=get(O/'selection_frozen.json');validation={f.stem:get(f) for f in O.glob('validation*.json')}
  finalize(full,training,selection,validation,get(O/'selection_freeze.json')['sha256'])
 else:main()
