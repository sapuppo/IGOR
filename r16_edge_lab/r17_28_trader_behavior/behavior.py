"""Descriptive behavior; no fill replay or invented position baseline."""
from pathlib import Path
from collections import Counter,defaultdict
import json,pandas as pd,numpy as np
def native(x):
 if isinstance(x,np.generic):return x.item()
 raise TypeError(type(x).__name__)
R=Path(__file__).resolve().parent;coins=defaultdict(Counter);dirs=defaultdict(Counter);seconds=Counter();last={};gaps=defaultdict(list);tot=Counter();max_fills_sec=0
for c in pd.read_csv(R/'raw/bobby_2026-10.csv.gz',chunksize=150000,dtype=str,keep_default_na=False):
 t=pd.to_datetime(c.time,utc=True).astype('int64').to_numpy()//10**6;ntl=pd.to_numeric(c.ntl).to_numpy();fee=pd.to_numeric(c.fee,errors='coerce').to_numpy();pnl=pd.to_numeric(c.closedPnl,errors='coerce').to_numpy();sizes=pd.to_numeric(c.sz).to_numpy()
 for d,g in c.assign(ntl_num=ntl,fee_num=fee,pnl_num=pnl).groupby('dir'):
  dirs[d]['fills']+=len(g);dirs[d]['notional']+=g.ntl_num.sum();dirs[d]['fees_observed']+=g.fee_num.sum();dirs[d]['closed_pnl_observed']+=g.pnl_num.sum()
 for s,g in c.assign(t=t,ntl_num=ntl,fee_num=fee,pnl_num=pnl,size_num=sizes).groupby('coin'):
  z=coins[s];z['fills']+=len(g);z['notional']+=g.ntl_num.sum();z['fees_observed']+=g.fee_num.sum();z['closed_pnl_observed']+=g.pnl_num.sum();z['rebate_fills']+=(g.fee_num<0).sum();z['long_related_notional']+=g.loc[g.dir.isin(['Open Long','Close Long']),'ntl_num'].sum();z['short_related_notional']+=g.loc[g.dir.isin(['Open Short','Close Short']),'ntl_num'].sum();z['reversal_notional']+=g.loc[g.dir.str.contains('>'),'ntl_num'].sum();z['executed_buy_qty']+=g.loc[g.dir.isin(['Open Long','Close Short','Short > Long']),'size_num'].sum();z['executed_sell_qty']+=g.loc[g.dir.isin(['Open Short','Close Long','Long > Short']),'size_num'].sum()
  ts=g.t.to_numpy();diff=np.diff(np.r_[last[s],ts]) if s in last else np.diff(ts);gaps[s].extend(diff.tolist());last[s]=int(ts[-1]);seconds.update(zip(g.t.tolist(),[s]*len(g)))
fund=json.loads((R/'raw/bobby_october_userFunding_all.json').read_text());funds=defaultdict(float);sample_counts=Counter()
for x in fund:funds[x['delta']['coin']]+=float(x['delta']['usdc']);sample_counts[str(x['delta'].get('nSamples'))]+=1
ledger=json.loads((R/'raw/bobby_october_userNonFundingLedgerUpdates_all.json').read_text());types=Counter(x['delta'].get('type') for x in ledger)
recent=[]
for name in ['bobby','wintermute']:
 p=R/f'raw/{name}_recent_fills_all.json'
 if not p.exists():continue
 z=json.loads(p.read_text());ff=np.array([float(x['fee']) for x in z]);nn=np.array([float(x['px'])*float(x['sz']) for x in z]);dur=(max(x['time'] for x in z)-min(x['time'] for x in z))/1000
 before={};discontinuity=0;same_ms_reorder=0;clean=0
 for x in z:
  if x['coin'].startswith('@'):continue
  key=x['coin'];q=float(x['startPosition']);sd=1 if x['side']=='B' else -1;post=q+sd*float(x['sz'])
  if key in before:
   oldqt,oldt=before[key]
   if not np.isclose(q,oldqt,atol=1e-6,rtol=1e-9):
    if oldt==x['time']:same_ms_reorder+=1
    else:discontinuity+=1
   else:clean+=1
  before[key]=(post,x['time'])
 recent.append(dict(name=name,fills=len(z),start=min(x['time'] for x in z),end=max(x['time'] for x in z),seconds_covered=dur,makers=sum(not x['crossed'] for x in z),takers=sum(x['crossed'] for x in z),fee_sum=float(ff.sum()),rebate_fills=int((ff<0).sum()),maker_fraction=sum(not x['crossed'] for x in z)/len(z),notional=float(nn.sum()),inventory_transition_matches=clean,inventory_discontinuities=discontinuity,same_ms_order_ambiguities=same_ms_reorder,not_two_year_history=True))
cc={s:{**dict(z),'median_inter_fill_seconds':float(np.median(gaps[s]))/1000 if gaps[s] else None,'p90_inter_fill_seconds':float(np.quantile(gaps[s],.9))/1000 if gaps[s] else None,'short_related_volume_fraction':z['short_related_notional']/z['notional'],'max_fills_one_second':max(v for (t,coin),v in seconds.items() if coin==s)} for s,z in coins.items()}
fundsum=sum(funds.values());a=json.loads((R/'EXPORT_ANALYSIS.json').read_text());out=dict(month='2026-10',observed_export_fills=a['rows'],directions={k:dict(v) for k,v in dirs.items()},by_coin=cc,funding=dict(observed_entries=len(fund),reported_payment_sum=fundsum,by_coin=dict(funds),nSamples_histogram=dict(sample_counts),note='Aggregated funding rows present; szi is not assumed an instantaneous position baseline.'),ledger=dict(observed_entries=len(ledger),types=dict(types),note='Internal dex transfers, deposits and withdrawals must be classified before capital returns.'),recent_native_samples=recent,rebate_credit_share_of_observed_closed_pnl=(-a['observed_fee_sum'])/a['observed_closed_pnl_sum'],portfolio_return_computed=False)
(R/'BEHAVIOR.json').write_text(json.dumps(out,indent=2,default=native)+'\n');print(json.dumps({k:v for k,v in out.items() if k not in ['by_coin','funding']},indent=2,default=native));print('FUNDING_SUM',fundsum)
print('TOP_COINS',[(k,{kk:v[kk] for kk in ['fills','short_related_volume_fraction','median_inter_fill_seconds','max_fills_one_second']}) for k,v in sorted(cc.items(),key=lambda x:-x[1]['notional'])[:8]])
