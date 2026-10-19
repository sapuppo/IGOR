from pathlib import Path
import json,hashlib,warnings
import pandas as pd,numpy as np
import r17_21_audited_engine as e
import r17_19_trailing_engine as oldtrail
import run_r17_10_breakouts as oldfixed
from run_r17_19_trailing import prepare
from run_r17_20_new_hypotheses import compute
from run_r17_05_regime_rotation import load_verified
from run_r17_16_band_reversion import section,CUT
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'r17_21_results'

def main():
 warnings.filterwarnings('ignore');OUT.mkdir(exist_ok=True)
 p=json.loads((ROOT/'r17_21_protocol.json').read_text());data,funding=load_verified(ROOT/'usdm_history');print('152 hashes verified',flush=True)
 trailing=prepare(data);volume=compute(data);prefix={s:f.loc[f.index<CUT].copy() for s,f in data.items()};pt=prepare(prefix);pv=compute(prefix)
 for maps,pre in [(trailing,pt),(volume,pv)]:
  for k in maps:assert {t:v for t,v in maps[k].items() if t<=CUT}=={t:v for t,v in pre[k].items() if t<=CUT}
 for s in data:assert np.allclose(data[s].loc[prefix[s].index,'atr'],prefix[s].atr,equal_nan=True)
 btc=data['BTCUSDT'].close;btcside=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index)
 results={};attributions={};parity={}
 def record(key,r):
  daily=r.pop('daily_details');trades=r.pop('trade_details');f=pd.DataFrame(trades)
  r['segments']={name:section(daily,int(pd.Timestamp(a).timestamp()*1000),int(pd.Timestamp(b).timestamp()*1000)) for name,a,b in [('train','2023-01-01T00:00Z','2025-01-01T00:00Z'),('2025','2025-01-01T00:00Z','2026-01-01T00:00Z'),('h1_2026','2026-01-01T00:00Z','2026-07-01T00:00Z')]}
  r['profit_factor']=float(f.net.clip(lower=0).sum()/-f.net.clip(upper=0).sum()) if (f.net<0).any() else None
  r['win_rate']=float((f.net>0).mean());r['months_ge_15']=sum(v>=.15 for v in r['monthly'].values())
  if 'price_pnl' in f:
   assert np.allclose(f.net,f.price_pnl-f.entry_fee-f.exit_fee+f.funding)
  attributions[key]={field:{str(k):{'trades':len(g),'net':float(g.net.sum())} for k,g in f.groupby(field)} for field in ['symbol','side','reason']}
  pd.DataFrame(daily).to_csv(OUT/(key+'_daily.csv'),index=False);f.to_csv(OUT/(key+'_trades.csv'),index=False);results[key]=r
  print(key,json.dumps({k:r[k] for k in ['compound_monthly','max_4h_mtm_drawdown','profit_factor']}),flush=True)
 for family in ['trail55','volume_impulse']:
  signals=trailing if family=='trail55' else volume
  base=dict(id=family,direction='both',lookback_bars=55 if family=='trail55' else 6,btc_gate=True,hold_bars=180 if family=='trail55' else 42)
  if family=='trail55':base['trail_atr']=4
  for mode in p['variants']:
   spec=base.copy();spec['id']=family+'_'+mode
   if mode in ['risk','risk_cooldown']:
    spec.update({k:v for k,v in p['risk'].items() if k!='cooldown_bars'})
   if mode=='risk_cooldown':spec['cooldown_bars']=p['risk']['cooldown_bars']
   for factor in p['costs']:
    engine=(oldtrail if family=='trail55' else oldfixed) if mode=='legacy' else e
    engine.STOP=.05;engine.TARGET=.15;engine.FEE=.0006*factor;engine.SLIP=.0004*factor
    r=engine.replay(spec,data,funding,signals,btcside);key=spec['id']+'_cost'+str(factor)
    if mode=='legacy':
     previous=ROOT/('r17_19_results' if family=='trail55' else 'r17_20_results')/'summary.json';ps=json.loads(previous.read_text())['results'];pk=('trail4_hold180' if family=='trail55' else 'volume_impulse_gate1_hold42')+'_cost'+str(factor)
     assert r['trade_sha256']==ps[pk]['trade_sha256'];parity[key]='EXACT_TRADE_HASH_MATCH'
    record(key,r)
 for symbol in ['BTCUSDT','ETHUSDT']:
  for factor in [1,2]:
   e.STOP=.999;e.TARGET=float('inf');e.FEE=.0006*factor;e.SLIP=.0004*factor
   spec=dict(id=symbol+'_passive_perpetual',direction='long',lookback_bars=1,btc_gate=False,hold_bars=(e.END-e.START)//e.BAR_MS+1,max_weight=1,max_exposure=1)
   sig={(1,1):{e.START:[(symbol,1,1.)]}};record(spec['id']+'_cost'+str(factor),e.replay(spec,data,funding,sig,btcside))
 qualified=[k for k,v in results.items() if k.endswith('cost1') and 'legacy' not in k and 'passive' not in k and all(x['compound_monthly']>=p['goal_monthly'] and x['max_4h_mtm_drawdown']<=p['max_dd'] and all(y['return']>0 for y in x['segments'].values()) for x in [v,results[k[:-1]+'2']])]
 summary=dict(version='R17.21',protocol_sha256=hashlib.sha256((ROOT/'r17_21_protocol.json').read_bytes()).hexdigest(),verified_files=152,prefix_invariance='PASS_SIGNALS_AND_ATR',legacy_parity=parity,results=results,qualified=qualified,live_promotion=False,data_status=p['dataset'])
 (OUT/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n');(OUT/'attribution.json').write_text(json.dumps(attributions,indent=2)+'\n');print('COMPLETE qualified',qualified,flush=True)
if __name__=='__main__':main()
