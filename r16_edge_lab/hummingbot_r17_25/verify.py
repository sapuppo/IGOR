"""Independent CSV accounting, exchange-rule and causal-prefix verification."""
from pathlib import Path
import json,hashlib
import pandas as pd,numpy as np
from data import load,ms,BAR
from strategies import features
R=Path(__file__).resolve().parent;O=R/'results'
def main():
 # Reconstruct raw historical bars independently of replay output.
 p=json.loads((R/'protocol.json').read_text());prefix=[]
 for sym in p['symbols']:
  f=pd.read_csv(R.parent/'usdm_history/klines/15m'/(sym+'.csv.gz'));f=f[(f.open_time>=ms('2022-10-01'))&(f.open_time<ms('2026-07-01'))].set_index('open_time')
  g=f.groupby(f.index//BAR*BAR).agg(dict(open='first',high='max',low='min',close='last',quote_volume='sum'));allf=features(g)
  for cut in [ms('2025-01-01'),ms('2026-01-01')]:
   pd.testing.assert_frame_equal(allf.loc[allf.index<cut],features(g.loc[g.index<cut]));prefix.append(sym+'_'+str(cut))
 checks=[];filters={x['symbol']:{f['filterType']:f for f in x['filters']} for x in json.loads((R/'exchange_filters.json').read_text())['symbols']}
 for file in sorted(O.glob('*_trades.csv')):
  if file.name.startswith('frozen_'):continue
  key=file.name[:-11];t=pd.read_csv(file);d=pd.read_csv(O/(key+'_daily.csv'))
  if len(t):
   assert np.allclose(t.net,t.side*t.qty*(t.exit_fill-t.entry_fill)-t.entry_fee-t.exit_fee+t.funding)
   assert (t.exit>=t.entry).all()
   if not key.startswith(('walk_forward','holdout')):
    for sym,part in t.groupby('symbol'):
     q=filters[sym]['MARKET_LOT_SIZE'];assert part.qty.max()<=float(q['maxQty'])
     q=filters[sym]['PRICE_FILTER'];assert part.entry_fill.min()>=float(q['minPrice']) and part.entry_fill.max()<=float(q['maxPrice'])
  assert np.isclose(10000+t.net.sum(),d.equity.iloc[-1],atol=1e-5),key
  if (O/(key+'.json')).exists():
   result=json.loads((O/(key+'.json')).read_text());assert np.isclose(result['total_return'],d.equity.iloc[-1]/10000-1)
   m=d.assign(month=pd.to_datetime(d.timestamp-1,unit='ms',utc=True).dt.strftime('%Y-%m')).groupby('month').equity.last();rr=m/m.shift(fill_value=10000)-1
   assert all(np.isclose(result['monthly'][k],v) for k,v in rr.items())
  checks.append(key)
 selection=(O/'selection_frozen.json').read_bytes();freeze=json.loads((O/'selection_freeze.json').read_text());assert hashlib.sha256(selection).hexdigest()==freeze['sha256']
 out=dict(status='passed',csv_reconciliations=checks,causal_real_data_prefix_checks=prefix,market_qty_price_filter_checks='all unscaled simulated trades passed',frozen_selection_sha256=freeze['sha256'])
 (O/'verification.json').write_text(json.dumps(out,indent=2)+'\n');print('VERIFIED',len(checks),'replays/combined outputs;',len(prefix),'prefix checks')
if __name__=='__main__':main()
