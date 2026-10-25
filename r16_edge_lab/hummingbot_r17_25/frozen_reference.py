"""Re-run frozen R17.24 comparator without touching any original source."""
from pathlib import Path
import sys,json,warnings,hashlib
import pandas as pd,numpy as np
R=Path(__file__).resolve().parent;sys.path.insert(0,str(R.parent))
import r17_21_audited_engine as e
from run_r17_05_regime_rotation import load_verified
from run_r17_19_trailing import prepare
from run_r17_20_new_hypotheses import compute
warnings.filterwarnings('ignore');p=json.loads((R/'protocol.json').read_text());data,fund=load_verified(R.parent/'usdm_history');data={s:data[s] for s in p['symbols']};fund={s:fund[s] for s in data};prepare(data);sig=compute(data);btc=data['BTCUSDT'].close;bs=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index);results={}
for cost in [1,2]:
 e.FEE=.0006*cost;e.SLIP=.0004*cost;e.TARGET=.15;e.STOP=.05
 spec=dict(id='frozen_r17_24_volume',direction='both',lookback_bars=6,btc_gate=True,hold_bars=42,risk_fraction=.0025,max_weight=.15,max_exposure=.6,atr_stop=2)
 x=e.replay(spec,data,fund,sig,bs);daily=x.pop('daily_details');tr=x.pop('trade_details');results[str(cost)]=x
 pd.DataFrame(daily).to_csv(R/'results'/f'frozen_reference_cost{cost}_daily.csv',index=False);pd.DataFrame(tr).to_csv(R/'results'/f'frozen_reference_cost{cost}_trades.csv',index=False)
 print(cost,x['compound_monthly'],x['max_4h_mtm_drawdown'],x['trades'],flush=True)
(R/'results/frozen_reference.json').write_text(json.dumps(results,indent=2)+'\n')
