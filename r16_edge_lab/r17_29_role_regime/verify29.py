"""Independent accounting, selection and causal availability audit."""
import json,hashlib,math,gzip
from pathlib import Path
import numpy as np,pandas as pd
from data29 import R,P,SYMS,HOUR,DAY,features
from engine29 import venue_rules

def near(a,b):assert math.isclose(float(a),float(b),abs_tol=1e-7,rel_tol=1e-9),(a,b)
def main():
 cov=json.loads((R/'DATA_COVERAGE.json').read_text());man=json.loads((R/'DATA_MANIFEST.json').read_text());checked=0
 for x in man:
  if x['status']=='verified':assert hashlib.sha256((R/'raw'/x['file']).read_bytes()).hexdigest()==x['sha256'];checked+=1
 for file,sha in cov['prepared_sha256'].items():assert hashlib.sha256((R/file).read_bytes()).hexdigest()==sha
 assert checked==510 and cov['end_exclusive']==int(pd.Timestamp('2026-11-26',tz='UTC').timestamp()*1000)
 featcount=0
 for s in SYMS:
  f=pd.read_pickle(R/'prepared'/(s+'.pkl'));raw=f[['open','high','low','close','quote_volume']]
  for n in [1001,len(f)-11]:
   a=features(raw.iloc[:n]);cols=[c for c in a if c not in raw.columns];pd.testing.assert_frame_equal(a[cols],f.iloc[:n][cols],check_exact=True);featcount+=1
 report=json.loads((R/'results/COMPARISON.json').read_text());frozenraw=(R/'results/SELECTION_FROZEN.json').read_bytes();assert hashlib.sha256(frozenraw).hexdigest()==report['selection_sha256'];frozen=json.loads(frozenraw);assert frozen['protocol_sha256']==hashlib.sha256((R/'protocol.json').read_bytes()).hexdigest()
 for fold in frozen['folds']:
  assert fold['train_start']<fold['train_end_exclusive']==fold['test_start'];ok=[]
  for name,x in fold['training'].items():
   a=x['normal'];pf=a['profit_factor'] if a['profit_factor'] is not None else (float('inf') if a['profit_factor_infinite'] else 0)
   eligible=a['trades']>=20 and pf>1.1 and a['max_drawdown']<=.2 and all(v>0 for v in x['half_returns']) and x['stress']['total_return']>0 and a['total_return']>fold['reference_return'];assert bool(eligible)==x['eligible']
   if eligible:ok.append(name)
  winner=sorted(ok,key=lambda n:(-fold['training'][n]['normal']['total_return'],n))[0] if ok else 'cash';assert winner==fold['selected']
 audited=[];tradecount=0;rules=venue_rules()
 groups=[(R/'results',report['results'],report['start'],report['end_exclusive'],HOUR,24,'hold_hours'),(R/'copy_results',json.loads((R/'copy_results/COPY_COMPARISON.json').read_text())['results'],int(pd.Timestamp('2026-10-01',tz='UTC').timestamp()*1000),int(pd.Timestamp('2026-11-01',tz='UTC').timestamp()*1000),60000,1440,'hold_minutes')]
 for root,results,start,end,step,perday,holdcol in groups:
  for key,r in results.items():
   t=pd.read_csv(root/(key+'_trades.csv.gz'));d=pd.read_csv(root/(key+'_daily.csv'));m=np.load(root/(key+'_marks.npy'));assert len(m)==(end-start)//step;assert len(d)==len(m)//perday
   assert np.array_equal(d.timestamp.to_numpy(),np.arange(start+DAY,end+1,DAY));np.testing.assert_allclose(d.equity.to_numpy(),m[perday-1::perday],rtol=1e-12,atol=1e-7)
   if len(t):
    pnl=t.side*t.qty*(t.exit_fill-t.entry_fill)-t.entry_fee-t.exit_fee+t.funding;np.testing.assert_allclose(pnl,t.net,rtol=1e-9,atol=1e-7);assert (t.entry>=start).all() and (t.exit<=end).all() and (t.exit>=t.entry).all();np.testing.assert_allclose((t.exit-t.entry)/step,t[holdcol],rtol=1e-10)
    near(r['fees'],(t.entry_fee+t.exit_fee).sum());near(r['funding'],t.funding.sum());near(m[-1],10000+t.net.sum());tradecount+=len(t)
    for s,x in t.groupby('symbol'):np.testing.assert_allclose(x.qty/rules[s]['step'],np.rint(x.qty/rules[s]['step']),rtol=0,atol=1e-5)
    gains=t.net[t.net>0].sum();loss=-t.net[t.net<0].sum()
    if loss>0:near(r['profit_factor'],gains/loss)
   else:near(m[-1],10000)
   near(r['total_return'],m[-1]/10000-1);v=np.r_[10000,m];near(r['max_drawdown'],np.max(1-v/np.maximum.accumulate(v)))
   ss=pd.Series(d.equity.to_numpy(),index=pd.to_datetime(d.timestamp-1,unit='ms',utc=True));mm=ss.resample('ME').last();rr=mm/mm.shift(fill_value=10000)-1
   for date,ret in rr.items():near(r['monthly'][date.strftime('%Y-%m')],ret)
   if root.name=='results' and key.endswith('cost1'):
    with gzip.open(root/(key+'_trace.jsonl.gz'),'rt') as z:
     for row in z:
      if not row.strip():continue
      x=json.loads(row);assert x['time']-x['decision_time']==HOUR and (x['decision_time']//HOUR)%4==0
      if key.startswith('selected_wfo'):
       valid=[f for f in frozen['folds'] if f['test_start']<=x['time']];assert valid[-1]['selected']==x['policy']
   audited.append(key)
 out=dict(status='passed',unit_tests=26,verified_market_archives=checked,real_feature_prefix_checks=featcount,selection_folds_checked=len(frozen['folds']),accounting_replays=len(audited),trade_rows_reconciled=tradecount,training_replays=report['training_replays'],total_strategy_replays=report['training_replays']+len(audited),protocol_sha256=hashlib.sha256((R/'protocol.json').read_bytes()).hexdigest(),selection_sha256=report['selection_sha256'],limitations=['No independent untouched future sample','Current venue filters, not historical point-in-time','Hourly maximum drawdown excludes intrahour unrealized extreme','No live execution, queue simulation or complete2year wallet reconstruction'])
 (R/'VERIFICATION.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))

if __name__=='__main__':main()
