"""Empirical check of fill.closedPnl versus arithmetic price PnL.
Only segments starting from an observed zero startPosition, without state gaps.
"""
import json,math
from pathlib import Path
R=Path(__file__).resolve().parent;allchecks=[]
for name in ['bobby','wintermute']:
 seen={};ordered=[]
 for p in sorted((R/'raw').glob(f'{name}_recent_fills_[0-9].json')):
  for x in json.loads(p.read_text()):
   k=tuple(x.get(y) for y in ['coin','time','tid','oid','side','sz','px','startPosition'])
   if k not in seen:ordered.append(x);seen[k]=True
 state={}
 for x in ordered:
  if x['coin'].startswith('@'):continue
  c=x['coin'];q=float(x['startPosition']);size=float(x['sz']);px=float(x['px']);sd=1 if x['side']=='B' else -1;delta=sd*size;post=q+delta
  if q==0:state[c]=(q,px)
  if c not in state or not math.isclose(state[c][0],q,abs_tol=1e-8):state.pop(c,None);continue
  avg=state[c][1]
  if q*delta<0:
   close=min(abs(q),size);gross=(1 if q>0 else -1)*(px-avg)*close;reported=float(x['closedPnl']);fee=float(x['fee'])
   if abs(gross)>.0001:allchecks.append(dict(wallet=name,coin=c,time=x['time'],calculated_price_pnl=gross,reported_closedpnl=reported,fee=fee,error_vs_gross=reported-gross,error_vs_gross_minus_fee=reported-(gross-fee)))
   if post==0:state.pop(c,None)
   elif q*post<0:state[c]=(post,px)
   else:state[c]=(post,avg)
  else:
   newavg=(abs(q)*avg+size*px)/abs(post) if post else px;state[c]=(post,newavg)
out=dict(checks=len(allchecks),matches_gross_within_0_00001=sum(abs(x['error_vs_gross'])<.00001 for x in allchecks),matches_after_fee_within_0_00001=sum(abs(x['error_vs_gross_minus_fee'])<.00001 for x in allchecks),examples=allchecks[:20],note='Limited recent segments, not proof of historical CSV transformation or full account PnL. Native API fill field can differ from frontend PnL labels.')
(R/'PNL_FIELD_CHECK.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
