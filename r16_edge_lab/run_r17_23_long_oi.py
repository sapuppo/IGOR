"""Long OI evaluation. Frozen R17.22 signal rules; five prespecified symbols."""
from pathlib import Path
from collections import defaultdict
import json,hashlib,warnings
import numpy as np,pandas as pd
import r17_21_audited_engine as e
from run_r17_19_trailing import prepare
from run_r17_20_new_hypotheses import compute
from run_r17_05_regime_rotation import load_verified
from run_r17_16_band_reversion import section
from r17_22_flow import signals,asof_values
R=Path(__file__).resolve().parent;D=R/'r17_23_data';O=R/'r17_23_results'
def ms(s):return int(pd.Timestamp(s).timestamp()*1000)
def main():
 warnings.filterwarnings('ignore');p=json.loads((R/'r17_23_protocol.json').read_text());prev=json.loads((R/'r17_22_protocol.json').read_text());m=json.loads((D/'manifest.json').read_text());all_data,allfund=load_verified(R/'usdm_history');data={s:all_data[s].copy() for s in p['symbols']};fund={s:allfund[s] for s in p['symbols']};rates={};oi={};input_hashes={};support={}
 for sym,f in data.items():
  x=pd.read_csv(R/'usdm_history/klines/4h'/(sym+'.csv.gz'),compression='gzip').set_index('open_time');f['taker_buy_quote_volume']=x.taker_buy_quote_volume
  rr=pd.read_csv(R/'usdm_history/funding'/(sym+'.csv.gz'),compression='gzip');rates[sym]=[{'timestamp':int(x.fundingTime),'rate':float(x.fundingRate)} for x in rr.itertuples()]
  op=D/(sym+'_oi_4h.csv.gz');input_hashes[op.name]=hashlib.sha256(op.read_bytes()).hexdigest();q=pd.read_csv(op,compression='gzip');assert q.timestamp.is_monotonic_increasing and not q.timestamp.duplicated().any();assert (q.oi>0).all();oi[sym]=q.to_dict('records')
  t=f.index.to_numpy()+e.BAR_MS;sel=(t>=ms(p['test_start']))&(t<ms(p['test_end_exclusive']));cur=asof_values(t[sel],oi[sym],'oi',8*3600000);past=asof_values(t[sel]-24*3600000,oi[sym],'oi',8*3600000)
  support[sym]={'decision_bars':int(sel.sum()),'causal_oi_pair_available':int((np.isfinite(cur)&np.isfinite(past)).sum()),'fraction':float((np.isfinite(cur)&np.isfinite(past)).mean())}
 prepare(data);e.START=ms(p['test_start']);e.END=ms(p['test_end_exclusive']);btc=data['BTCUSDT'].close;bs=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index);out={};prefix=[];counts={}
 for mode in p['variants']:
  sig=compute(data) if mode=='r21_volume_control' else signals(data,rates,oi,mode,e.START,e.END)
  if mode!='r21_volume_control':
   for cut in [ms('2025-01-01T00:00Z'),ms('2026-01-01T00:00Z')]:
    pre=signals({s:f.loc[f.index<cut].copy() for s,f in data.items()},{s:[v for v in rows if v['timestamp']<cut] for s,rows in rates.items()},{s:[v for v in rows if v['timestamp']<cut] for s,rows in oi.items()},mode,e.START,e.END)
    for k in sig:assert {t:v for t,v in sig[k].items() if t<=cut}=={t:v for t,v in pre[k].items() if t<=cut}
    prefix.append(mode+'_'+str(cut))
  counts[mode]=sum(len(v) for maps in sig.values() for v in maps.values())
  for factor in p['costs']:
   e.STOP=prev['stop'];e.TARGET=prev['target'];e.FEE=.0006*factor;e.SLIP=.0004*factor
   spec=dict(id=mode,direction='both',lookback_bars=6,btc_gate=True,hold_bars=prev['hold_bars'],**prev['risk']);x=e.replay(spec,data,fund,sig,bs);daily=x.pop('daily_details');trades=x.pop('trade_details');key=mode+'_cost'+str(factor)
   x['segments']={name:section(daily,ms(a),ms(b)) for name,a,b in [('2023','2023-01-01T00:00Z','2024-01-01T00:00Z'),('2024','2024-01-01T00:00Z','2025-01-01T00:00Z'),('2025','2025-01-01T00:00Z','2026-01-01T00:00Z'),('h1_2026','2026-01-01T00:00Z','2026-07-01T00:00Z')]}
   x['months_ge_15']=sum(v>=.15 for v in x['monthly'].values());out[key]=x;pd.DataFrame(daily).to_csv(O/(key+'_daily.csv'),index=False);pd.DataFrame(trades).to_csv(O/(key+'_trades.csv'),index=False)
   print(key,json.dumps({k:x[k] for k in ['return','compound_monthly','max_4h_mtm_drawdown','trades']}),flush=True)
 report=dict(version='R17.23',results=out,support=support,prefix_checks=prefix,signal_counts=counts,input_hashes=input_hashes,source_manifest_sha256=hashlib.sha256((D/'manifest.json').read_bytes()).hexdigest(),protocol_sha256=hashlib.sha256((R/'r17_23_protocol.json').read_bytes()).hexdigest(),live_promotion=False)
 (O/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('COMPLETE',flush=True)
if __name__=='__main__':main()
