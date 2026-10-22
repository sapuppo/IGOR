from pathlib import Path
from collections import defaultdict
import json,hashlib,warnings,gzip
import numpy as np,pandas as pd
import r17_21_audited_engine as e
import run_r17_10_breakouts as old
from run_r17_19_trailing import prepare
from run_r17_20_new_hypotheses import compute
from run_r17_05_regime_rotation import load_verified
from r17_22_flow import signals
R=Path(__file__).resolve().parent;O=R/'r17_22_results';D=R/'r17_22_data'
def ms(x):return int(pd.Timestamp(x).timestamp()*1000)
def raw(sym,kind):
 p=D/(sym+'_'+kind+'.json');j=json.loads(p.read_text())['response'];assert not j.get('isError');return j['structuredContent']['result']
def main():
 warnings.filterwarnings('ignore');p=json.loads((R/'r17_22_protocol.json').read_text());O.mkdir(exist_ok=True)
 hist,hf=load_verified(R/'usdm_history');hr={}
 for sym,f in hist.items():
  q=pd.read_csv(R/'usdm_history'/'klines/4h'/(sym+'.csv.gz'),compression='gzip').set_index('open_time')
  f['taker_buy_quote_volume']=q.taker_buy_quote_volume
  g=pd.read_csv(R/'usdm_history'/'funding'/(sym+'.csv.gz'),compression='gzip');hr[sym]=[{'timestamp':int(x.fundingTime),'rate':float(x.fundingRate)} for x in g.itertuples()]
 recent={};rf={};rr={};oi={};coverage={}
 for sym in p['recent_symbols']:
  q=pd.DataFrame(raw(sym,'klines'),columns=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume','ignore']).apply(pd.to_numeric)
  assert not q.open_time.duplicated().any();assert q.open_time.is_monotonic_increasing
  assert (q.open_time.diff().dropna()==e.BAR_MS).all();assert q.close_time.max()<ms(p['recent_end_exclusive'])
  recent[sym]=q.set_index('open_time')
  rr[sym]=[{'timestamp':int(x['fundingTime']),'rate':float(x['fundingRate'])} for x in raw(sym,'funding')]
  rf[sym]=defaultdict(list)
  for x in rr[sym]:rf[sym][x['timestamp']//e.BAR_MS*e.BAR_MS].append((x['timestamp'],x['rate']))
  oi[sym]=[{'timestamp':int(x['timestamp']),'oi':float(x['sumOpenInterest'])} for x in raw(sym,'oi')]
  coverage[sym]={'klines':len(q),'funding':len(rr[sym]),'oi':len(oi[sym]),'oi_start':min(x['timestamp'] for x in oi[sym]),'oi_end':max(x['timestamp'] for x in oi[sym])}
 results={};counts={};checks=[]
 for label,data,funding,rates,ois,start,end,modes in [('historical',hist,hf,hr,{},ms('2023-01-01T00:00Z'),ms('2026-07-01T00:00Z'),p['variants'][:3]),('recent',recent,rf,rr,oi,ms(p['recent_start']),ms(p['recent_end_exclusive']),p['variants'])]:
  for sym,f in data.items():
   assert f.taker_buy_quote_volume.notna().all();assert ((f.taker_buy_quote_volume>=0)&(f.taker_buy_quote_volume<=f.quote_volume+1e-5)).all()
  prepare(data);e.START=start;e.END=end;old.START=start;old.END=end
  btc=data['BTCUSDT'].close;bs=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index)
  for mode in modes:
   sig=compute(data) if mode=='r21_volume_control' else signals(data,rates,ois,mode,start,end)
   cut=ms('2025-01-01T00:00Z') if label=='historical' else ms('2026-10-07T00:00Z')
   if mode!='r21_volume_control':
    pre=signals({s:f.loc[f.index<cut].copy() for s,f in data.items()},{s:[v for v in rr0 if v['timestamp']<cut] for s,rr0 in rates.items()},{s:[v for v in oo if v['timestamp']<cut] for s,oo in ois.items()},mode,start,end)
    for k in sig:assert {t:v for t,v in sig[k].items() if t<=cut}=={t:v for t,v in pre[k].items() if t<=cut}
    checks.append(label+'_'+mode)
   counts[label+'_'+mode]=sum(len(v) for m in sig.values() for v in m.values())
   for factor in p['costs']:
    e.STOP=p['stop'];e.TARGET=p['target'];e.FEE=.0006*factor;e.SLIP=.0004*factor
    spec=dict(id=mode,direction='both',lookback_bars=6,btc_gate=True,hold_bars=p['hold_bars'],**p['risk'])
    x=e.replay(spec,data,funding,sig,bs);daily=x.pop('daily_details');trades=x.pop('trade_details');key=label+'_'+mode+'_cost'+str(factor)
    if label=='recent':x['compound_monthly']=None;x['monthly_label']='partial calendar buckets: Sep23-30 and Oct1-21; NOT full months'
    results[key]=x;pd.DataFrame(daily).to_csv(O/(key+'_daily.csv'),index=False);pd.DataFrame(trades).to_csv(O/(key+'_trades.csv'),index=False)
    print(key,json.dumps({k:x[k] for k in ['return','compound_monthly','max_4h_mtm_drawdown','trades']}),flush=True)
 summary=dict(version='R17.22',coverage=coverage,results=results,signal_counts=counts,prefix_checks=checks,source_hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in D.glob('*.json')},protocol_sha256=hashlib.sha256((R/'r17_22_protocol.json').read_bytes()).hexdigest(),live_promotion=False)
 (O/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n');print('COMPLETE',flush=True)
if __name__=='__main__':main()
