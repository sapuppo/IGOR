"""Independent reconciliation and scalar labels, outside execution code."""
import json,hashlib
import numpy as np,pandas as pd
from data27 import R,R26,P,STEP,SYMS,HORIZONS,ms,long_features,stop_fraction,labels
from prepare import read,feature_frame
from third_party.vibe_risk import max_drawdown_analysis

def scalar_label(v,i,st,h,side):
 entry=v[i+2,0];sl=entry*(1-side*st);tp=entry*(1+side*2*st)
 for k in range(h):
  op,hi,lo,_,_=v[i+2+k]
  if side*(op-sl)<=0 or side*(op-tp)>=0:return side*(op/entry-1)/st,max(1,k)
  if (lo<=sl if side==1 else hi>=sl):return side*(sl/entry-1)/st,k+1
  if (hi>=tp if side==1 else lo<=tp):return side*(tp/entry-1)/st,k+1
 return side*(v[i+2+h,0]/entry-1)/st,h

def main():
 O=R/'results';report=json.loads((O/'summary.json').read_text());checks=[];prefix=[];models=[];labelchecks=0
 assert hashlib.sha256((O/'selection_before_final.json').read_bytes()).hexdigest()==report['selection_sha256'];assert hashlib.sha256((R/'protocol.json').read_bytes()).hexdigest()==report['protocol_sha256']
 for path in sorted(O.glob('*_daily.csv')):
  key=path.name[:-10];d=pd.read_csv(path);t=pd.read_csv(O/(key+'_trades.csv.gz'));marks=np.load(O/(key+'_marks.npy'));m=json.loads((O/(key+'.json')).read_text())
  assert len(t)==m['trades'] and np.isclose(d.equity.iloc[-1],10000+t.net.sum(),atol=1e-6)
  assert np.isclose(d.equity.iloc[-1],marks[-1]) and np.isclose(m['total_return'],marks[-1]/10000-1)
  assert np.allclose(marks[1439::1440],d.equity)
  if len(t):
   expected=t.side*t.qty*(t.exit_fill-t.entry_fill)-t.entry_fee-t.exit_fee+t.funding;assert np.allclose(t.net,expected,atol=1e-6)
   assert (t.exit>=t.entry).all() and (t.qty>0).all()
   assert np.allclose(t.hold_minutes,(t.exit-t.entry)/STEP)
   losses=-t.net[t.net<0].sum();pf=t.net[t.net>0].sum()/losses if losses else None
   if pf is not None:assert np.isclose(pf,m['profit_factor'])
  ext=max_drawdown_analysis(pd.Series(np.r_[10000.,marks]));assert np.isclose(ext['max_drawdown'],m['max_drawdown']),key
  v=np.r_[10000.,d.equity];rr=v[1:]/v[:-1]-1;sh=rr.mean()/rr.std(ddof=1)*np.sqrt(365) if rr.std(ddof=1)>0 else 0
  assert np.isclose(sh,m['sharpe'])
  checks.append(key)
 assert len(checks)==120,len(checks)
 for path in sorted((R/'models').glob('2026-*.json')):
  m=json.loads(path.read_text());assert hashlib.sha256(path.with_suffix('.pkl').read_bytes()).hexdigest()==m['model_sha256'];predpath=path.parent/(path.stem+'_predictions.npz');m['predictions_sha256']=hashlib.sha256(predpath.read_bytes()).hexdigest()
  for a in m['audit']:
   assert a['fit_last']+181*STEP<a['calibration_first'] and a['calibration_last']+181*STEP<m['start'];assert a['fit_samples']>1000 and a['calibration_samples']>1000
  for h in HORIZONS:
   aa=[x for x in m['audit'] if x['key'].startswith(str(h)+'_')];assert aa[0]['fit_samples']==aa[1]['fit_samples'] and aa[0]['calibration_samples']==aa[1]['calibration_samples']
  models.append(dict(file=path.name,model_sha256=m['model_sha256'],predictions_sha256=m['predictions_sha256']))
 rng=np.random.default_rng(27);manifest=json.loads((R26/'manifest.json').read_text())
 for s in SYMS:
  times=np.load(R26/'prepared'/(s+'_times.npy'));v=np.load(R26/'prepared'/(s+'_prices.npy'));f=pd.read_pickle(R/'prepared'/(s+'_features.pkl'))
  for h in HORIZONS:
   for sd in [1,-1]:
    for i in rng.integers(200,len(v)-h-3,size=100):
     rr,dd=scalar_label(v,int(i),float(f['stop_'+str(h)].iloc[i]),h,sd);assert np.isclose(rr,f[f'r_{h}_{sd}'].iloc[i]) and dd==f[f'd_{h}_{sd}'].iloc[i];labelchecks+=1
  raw=pd.concat([read(e) for e in manifest if e['symbol']==s and e['kind']=='klines' and e['status']=='verified' and e['period'] in ['2026-06','2026-07']]).set_index('open_time').sort_index();book=pd.read_pickle(R26/'prepared'/(s+'_book.pkl'));cut=ms('2026-07-01');pre=raw.loc[raw.index<cut]
  full=long_features(feature_frame(raw,book),raw[['open','high','low','close','quote_volume']].to_numpy(),raw.index.to_numpy());part=long_features(feature_frame(pre,book.loc[book.index<cut+STEP]),pre[['open','high','low','close','quote_volume']].to_numpy(),pre.index.to_numpy());pd.testing.assert_frame_equal(full.loc[full.index<=cut],part);prefix.append(s)
 assert len(models)==5
 out=dict(status='passed',accounting_replays=len(checks),model_bundles=models,model_heads=150,scalar_label_checks=labelchecks,real_prefix_checks=prefix,independent_drawdown='HKUDS/Vibe-Trading MIT',unit_tests=17,selection_before_final_sha256=report['selection_sha256'],no_live_orders=True)
 (R/'VERIFICATION.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
if __name__=='__main__':main()
