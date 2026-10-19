from pathlib import Path
import json,warnings
import pandas as pd,numpy as np
import r17_21_audited_engine as e
from run_r17_19_trailing import prepare
from run_r17_20_new_hypotheses import compute
from run_r17_05_regime_rotation import load_verified
from run_r17_16_band_reversion import section,CUT
R=Path(__file__).resolve().parent;O=R/'r17_21_results'
warnings.filterwarnings('ignore')
p={'decision':'For each family choose side with greatest sum normalized trade net among exits strictly before 2025; positive score required, min30 closed trades; tie long. Derived after first audit batch. 2025-26 not untouched.','selection_period':'2023-2024','test_start':'2025-01-01','costs':[1,2],'risk':{'risk_fraction':.0025,'max_weight':.15,'max_exposure':.6,'atr_stop':2},'live_promotion':False}
(R/'r17_21_direction_protocol.json').write_text(json.dumps(p,indent=2)+'\n')
selection={}
for family in ['trail55','volume_impulse']:
 f=pd.read_csv(O/(family+'_corrected_cost1_trades.csv'));f=f[f.exit<CUT].copy();f['normalized']=f.net/(f.qty*f.entry_fill)
 scores={str(side):dict(trades=len(g),score=float(g.normalized.sum())) for side,g in f.groupby('side')};valid=[(int(k),x['score']) for k,x in scores.items() if x['trades']>=30 and x['score']>0]
 selection[family]={'scores':scores,'side':max(valid,key=lambda x:(x[1],x[0]))[0] if valid else None}
print('SELECTION',selection,flush=True)
data,funding=load_verified(R/'usdm_history');trailing=prepare(data);volume=compute(data);btc=data['BTCUSDT'].close;btcside=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index);results={}
# Fresh portfolio at 2025 boundary: no training positions or wealth carried into evaluation.
e.START=CUT
for family,sel in selection.items():
 if sel['side'] is None:continue
 for factor in [1,2]:
  spec=dict(id=family+'_train_direction',direction='long' if sel['side']==1 else 'short',lookback_bars=55 if family=='trail55' else 6,btc_gate=True,hold_bars=180 if family=='trail55' else 42,**p['risk'])
  if family=='trail55':spec['trail_atr']=4
  e.STOP=.05;e.TARGET=.15;e.FEE=.0006*factor;e.SLIP=.0004*factor
  rr=e.replay(spec,data,funding,trailing if family=='trail55' else volume,btcside);daily=rr.pop('daily_details');trades=rr.pop('trade_details')
  rr['segments']={name:section(daily,int(pd.Timestamp(a).timestamp()*1000),int(pd.Timestamp(b).timestamp()*1000)) for name,a,b in [('2025','2025-01-01T00:00Z','2026-01-01T00:00Z'),('h1_2026','2026-01-01T00:00Z','2026-07-01T00:00Z')]}
  key=spec['id']+'_cost'+str(factor);results[key]=rr;pd.DataFrame(daily).to_csv(O/(key+'_daily.csv'),index=False);pd.DataFrame(trades).to_csv(O/(key+'_trades.csv'),index=False)
  print(key,rr['compound_monthly'],rr['max_4h_mtm_drawdown'],rr['segments'],flush=True)
(O/'direction_summary.json').write_text(json.dumps(dict(protocol=p,selection=selection,results=results),indent=2)+'\n')
