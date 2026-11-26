"""Independent accounting, causal feature/label time and external risk checks."""
from pathlib import Path
import json,hashlib,ast
import numpy as np,pandas as pd
from prepare import R,P,SYMS,STEP,DAY,feature_frame,ms
from third_party.vibe_risk import max_drawdown_analysis

def main():
 checks=[];prefix=[];modelchecks=[];external=[]
 for sym in SYMS:
  times=np.load(R/'prepared'/(sym+'_times.npy'));prices=np.load(R/'prepared'/(sym+'_prices.npy'));book=pd.read_pickle(R/'prepared'/(sym+'_book.pkl'))
  cols=['open','high','low','close','quote_volume'];f=pd.DataFrame(prices,index=times,columns=cols)
  # Taker volumes are retained in the generated features; reconstruct the raw
  # prefix directly from original archives for an independent feature check.
  from prepare import read
  man=json.loads((R/'manifest.json').read_text());entries=[e for e in man if e['symbol']==sym and e['kind']=='klines' and e['status']=='verified' and e['period'] in ['2026-06','2026-07']]
  f=pd.concat([read(e) for e in entries]).set_index('open_time').sort_index();cut=ms('2026-07-01');a=feature_frame(f,book);b=feature_frame(f.loc[f.index<cut],book.loc[book.index<cut+STEP])
  pd.testing.assert_frame_equal(a.loc[a.index<=cut],b);prefix.append(sym)
 for modeldir in ['models','models_lightgbm']:
  for p in (R/modeldir).glob('2026-*.json'):
   m=json.loads(p.read_text());assert hashlib.sha256(p.with_suffix('.pkl').read_bytes()).hexdigest()==m['model_sha256']
   for x in m['audit']:
    assert x['fit_last']+21*STEP<x['calibration_first'];assert x['calibration_last']+21*STEP<m['start']
   modelchecks.append(str(p.relative_to(R)))
 for dirname in ['results','results_lightgbm']:
  O=R/dirname
  report=json.loads((O/'summary.json').read_text());assert hashlib.sha256((O/'selection_before_final.json').read_bytes()).hexdigest()==report['selection_sha256']
  for path in sorted(O.glob('*_daily.csv')):
   key=path.name[:-10];d=pd.read_csv(path);t=pd.read_csv(O/(key+'_trades.csv.gz'));marks=np.load(O/(key+'_marks.npy'));m=json.loads((O/(key+'.json')).read_text())
   assert len(t)==m['trades'] and np.isclose(d.equity.iloc[-1],10000+t.net.sum(),atol=1e-6)
   assert np.isclose(d.equity.iloc[-1],marks[-1]);assert np.isclose(m['total_return'],d.equity.iloc[-1]/10000-1)
   if len(t):
    expected=t.side*t.qty*(t.exit_fill-t.entry_fill)-t.entry_fee-t.exit_fee+t.funding
    assert np.allclose(t.net,expected,atol=1e-6)
    assert (t.exit>=t.entry).all() and (t.qty>0).all()
   ext=max_drawdown_analysis(pd.Series(np.r_[10000.,marks]))
   assert np.isclose(ext['max_drawdown'],m['max_drawdown']),key
   checks.append(dirname+'/'+key)
  # No selection is allowed to pretend a flat policy has calibrated alpha.
  if report['selected']=='cash':assert report['goal_achieved'] is False
 # Check exact AST of reused HyperGrok functions (not just credit in a report).
 raw=(R/'sources/hypergrok_stop_cost_original.txt').read_text();local=(R/'third_party/hypergrok_stop.py').read_text()
 defs=lambda s:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(s).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
 a,b=defs(raw),defs(local)
 for name in ['UnpriceableStop','lot','round_down','price_stop']:assert a[name]==b[name];external.append(name)
 out=dict(status='passed',replay_accounting_checks=checks,model_cutoff_checks=modelchecks,real_data_prefix_checks=prefix,unchanged_reused_functions=external,independent_drawdown_module='HKUDS/Vibe-Trading',missing_book_files=[e['file'] for e in json.loads((R/'manifest.json').read_text()) if e['status']!='verified'])
 (R/'VERIFICATION.json').write_text(json.dumps(out,indent=2)+'\n');print('VERIFIED',len(checks),'replays;',len(modelchecks),'model bundles;',len(prefix),'real prefixes')
if __name__=='__main__':main()
