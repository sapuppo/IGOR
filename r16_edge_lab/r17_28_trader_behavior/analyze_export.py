"""Profile a public export and reconstruct only identified inventory paths."""
from pathlib import Path
from collections import Counter,defaultdict
from decimal import Decimal as D
from datetime import datetime,timezone
import csv,gzip,json,hashlib,numpy as np,pandas as pd
from inventory import Interval,CampaignTracker,DIRECTIONS
R=Path(__file__).resolve().parent;FILE=R/'raw/bobby_2026-10.csv.gz';START=1790812800000;END=1793491200000

def iterator():
 with gzip.open(FILE,'rt',newline='') as f:
  for i,r in enumerate(csv.DictReader(f)):
   if not r.get('time'):continue
   t=int(datetime.strptime(r['time'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()*1000)
   yield i,t,r

def number(s):return float(s) if s!='' else None

def main():
 limits=defaultdict(Interval);stats=defaultdict(Counter);daily=defaultdict(Counter);rows=0;dirs=Counter();previous=-1;fee_missing_rows=[];bad_notional=0;allhashzero=0
 for i,t,r in iterator():
  rows+=1;assert START<=t<END;assert t>=previous;previous=t;coin=r['coin'];dr=r['dir'];dirs[dr]+=1;price=float(r['px']);size=float(r['sz']);ntl=float(r['ntl']);assert price>0 and size>0
  if not np.isclose(price*size,ntl,rtol=1e-9,atol=1e-8):bad_notional+=1
  s=stats[coin];s['fills']+=1;s['notional']+=ntl;s['time_first']=min(t,s.get('time_first',t));s['time_last']=t
  fee=number(r['fee']);pnl=number(r['closedPnl']);d=daily[t//86400000*86400000];d['fills']+=1;d['notional']+=ntl
  for agg in [s,d]:
   if fee is None:agg['missing_fee']+=1;agg['notional_missing_fee']+=ntl
   else:agg['fees_reported']+=fee;agg['rebate_fills' if fee<0 else 'positive_fee_fills' if fee>0 else 'zero_fee_fills']+=1
   if pnl is not None:agg['closed_pnl_reported']+=pnl
   if pnl is None and ('Close' in dr or '>' in dr):agg['missing_close_pnl']+=1
  if fee is None and len(fee_missing_rows)<15:fee_missing_rows.append(r)
  if dr in DIRECTIONS:limits[coin].add(dr,r['sz']);s['buy_fills' if DIRECTIONS[dr]>0 else 'sell_fills']+=1
  else:s['excluded_nonperp_directions']+=1
 print('PASS1',rows,'identified',sum(x.identified for x in limits.values()),'invalid',sum(not x.valid for x in limits.values()),flush=True)
 inventory={c:x.asdict() for c,x in limits.items()};(R/'INVENTORY_INFERENCE.json').write_text(json.dumps(inventory,indent=2)+'\n')
 trackers={c:CampaignTracker(x.lower) for c,x in limits.items() if x.identified};minute={};fee_sum_reconstructed=0.
 for i,t,r in iterator():
  coin=r['coin'];dr=r['dir']
  if coin not in trackers or dr not in DIRECTIONS:continue
  q=trackers[coin].add(dr,r['sz'],r['px'],t,number(r['fee']),number(r['closedPnl']),r['feeToken'])
  if coin in ['BTC','ETH','SOL']:minute[t//60000*60000,coin]=(float(q),float(r['px']))
 campaigns=[];censored=[]
 for c,tr in trackers.items():
  for row in tr.completed:campaigns.append(dict(coin=c,**row))
  if tr.current:
   cc=tr.current;censored.append(dict(coin=c,side=cc.side,started=cc.started,inherited=cc.initial_inherited,ending_quantity=str(tr.q),gross_closed_reported=cc.gross_closed_reported,fees_reported=cc.fees_reported,fee_missing=cc.fee_missing,gross_missing_close=cc.gross_missing_close))
  fs=sum(x['fees_reported'] for x in tr.completed)+(tr.current.fees_reported if tr.current else 0)
  assert np.isclose(fs,stats[c]['fees_reported'],atol=1e-6),('fees allocation',c,fs,stats[c]['fees_reported'])
  gross=sum(x['gross_closed_reported'] for x in tr.completed)+(tr.current.gross_closed_reported if tr.current else 0)
  assert np.isclose(gross,stats[c]['closed_pnl_reported'],atol=1e-5),('PnL allocation',c,gross,stats[c]['closed_pnl_reported'])
 pd.DataFrame(campaigns,columns=['coin','side','started','ended','inherited','hold_minutes','entry_notional','exit_notional','max_abs_quantity','fills','gross_closed_reported','fees_reported','fee_missing','gross_missing_close','non_usdc_fee','net_before_funding']).to_csv(R/'CAMPAIGNS.csv.gz',index=False,compression=dict(method='gzip',mtime=0));(R/'CENSORED_CAMPAIGNS.json').write_text(json.dumps(censored,indent=2)+'\n')
 pd.DataFrame([dict(minute=t,coin=c,quantity=v[0],last_fill_price=v[1]) for (t,c),v in sorted(minute.items())],columns=['minute','coin','quantity','last_fill_price']).to_csv(R/'MAJOR_INVENTORY.csv.gz',index=False,compression=dict(method='gzip',mtime=0))
 pd.DataFrame([dict(timestamp=k,**v) for k,v in sorted(daily.items())]).to_csv(R/'DAILY_OBSERVED.csv',index=False)
 a=pd.DataFrame(campaigns);complete=a[~a.inherited] if len(a) else a;holds=complete.hold_minutes.dropna() if len(complete) else pd.Series(dtype=float);g=sum(s['closed_pnl_reported'] for s in stats.values());f=sum(s['fees_reported'] for s in stats.values());n=sum(s['notional'] for s in stats.values());totalreb=sum(s['rebate_fills'] for s in stats.values())
 out=dict(status='analysis_complete_for_one_export_only',address='0x7fdafde5cfb5465924316eced2d3715494c517d1',start_utc='2026-10-01',end_exclusive_utc='2026-11-01',rows=rows,symbols=len(stats),directions=dict(dirs),observed_closed_pnl_sum=g,observed_fee_sum=f,observed_closed_pnl_minus_observed_fees=g-f,missing_fee_rows=sum(s['missing_fee'] for s in stats.values()),missing_close_pnl_rows=sum(s['missing_close_pnl'] for s in stats.values()),missing_fee_notional=sum(s['notional_missing_fee'] for s in stats.values()),net_monthly_return=None,equity_drawdown=None,reason_return_not_computed='Opening/ending marked equity, cash flows, funding reconciliation and missing-field semantics not fully verified; realized PnL is not return.',rebate_fills=totalreb,rebate_fraction_of_all_fills=totalreb/rows,notional=n,identified_inventory_coins=len(trackers),unidentified_inventory_coins=[c for c,x in limits.items() if not x.identified],contradiction_coins=[c for c,x in limits.items() if not x.valid],closed_campaigns_including_inherited=len(a),closed_campaigns_with_observed_start=len(complete),inherited_closed_campaigns=int(a.inherited.sum()) if len(a) else 0,right_censored_campaigns=len(censored),hold_minutes_quantiles={str(q):float(holds.quantile(q)) for q in [.25,.5,.75,.9,.99]} if len(holds) else {},bad_price_times_size_notional=bad_notional,raw_sha256=hashlib.sha256(FILE.read_bytes()).hexdigest(),stats_by_coin={c:dict(s) for c,s in stats.items()},missing_fee_sample=fee_missing_rows,notes=['Position inference is ex-post accounting and cannot be used as a causal signal.','Campaign identification assumes every direction-labelled fill in the export is present and correctly ordered.','CSV precision is seconds, not milliseconds.','Blank fees and blank closing PnL are unknown pending format validation; never assumed zero.','Fee signs show credits or charges, not a guaranteed maker/taker label.','Missing oid, tid, side and startPosition restrict verification and deduplication.','Only October2026; no two-year completeness claim.'])
 (R/'EXPORT_ANALYSIS.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print('COMPLETE',json.dumps({k:v for k,v in out.items() if k not in ['stats_by_coin','missing_fee_sample','notes']}),flush=True)
if __name__=='__main__':main()
