"""Hourly taker simulator with continuous drawdown state; no account access."""
import math,json
from dataclasses import dataclass
from collections import Counter
import numpy as np,pandas as pd
from data29 import R,P,SYMS,HOUR,DAY

@dataclass
class Risk:
 peak:float=10000.;streak:int=0;pause_until:int=0;halt:bool=False
 def factor(self,eq,t):
  self.peak=max(self.peak,eq)
  if eq<=self.peak*.8:self.halt=True
  if self.halt or t<self.pause_until:return 0.
  return .5 if eq<=self.peak*.92 else 1.
 def closed(self,net,t):
  self.streak=self.streak+1 if net<0 else 0
  if self.streak>=3:self.pause_until=max(self.pause_until,t+6*HOUR);self.streak=0

def venue_rules():
 out={}
 for s in json.loads((R/'exchange_filters.json').read_text())['symbols']:
  f={x['filterType']:x for x in s['filters']};l=f['LOT_SIZE'];m=f['MARKET_LOT_SIZE'];px=f['PRICE_FILTER'];out[s['symbol']]=dict(tick=float(px['tickSize']),step=float(l['stepSize']),minqty=max(float(l['minQty']),float(m['minQty'])),maxqty=min(float(l['maxQty']),float(m['maxQty'])),minnotional=float(f.get('MIN_NOTIONAL',{}).get('notional',5)),minprice=float(px['minPrice']),maxprice=float(px['maxPrice']))
 return out

def entry_order(op,sd,budget,r,friction):
 raw=op*(1+sd*friction);tick=r['tick'];fill=(math.ceil(raw/tick-1e-9) if sd==1 else math.floor(raw/tick+1e-9))*tick;qty=math.floor(min(budget/fill,r['maxqty'])/r['step']+1e-9)*r['step']
 if qty<r['minqty'] or qty*fill<r['minnotional'] or not r['minprice']<=fill<=r['maxprice']:return None
 assert qty*fill<=budget+1e-6
 return fill,qty

def summary(daily,trades,marks,start,end):
 v=np.r_[10000.,daily];dr=v[1:]/v[:-1]-1;mv=np.r_[10000.,marks];idx=pd.to_datetime(np.arange(start+DAY,end+1,DAY)-1,unit='ms',utc=True);ss=pd.Series(daily,index=idx);month=ss.resample('ME').last();mr=month/month.shift(fill_value=10000)-1;net=np.array([x['net'] for x in trades]);gp=float(net[net>0].sum());gl=float(-net[net<0].sum());std=dr.std(ddof=1) if len(dr)>1 else 0.;days=(end-start)/DAY;years=ss.resample('YE').last();yr=years/years.shift(fill_value=10000)-1
 return dict(total_return=float(v[-1]/10000-1),monthly_equivalent=float((v[-1]/10000)**(30.4375/days)-1),monthly={t.strftime('%Y-%m'):float(x) for t,x in mr.items()},yearly={str(t.year):float(x) for t,x in yr.items()},max_drawdown=float((1-mv/np.maximum.accumulate(mv)).max()),sharpe=float(dr.mean()/std*np.sqrt(365)) if std>0 else 0.,profit_factor=gp/gl if gl>0 else None,profit_factor_infinite=bool(gl==0 and gp>0),trades=len(trades),win_rate=float((net>0).mean()) if len(net) else 0.,mean_hold_hours=float(np.mean([x['hold_hours'] for x in trades])) if len(trades) else 0.,days=days,fees=float(sum(x['entry_fee']+x['exit_fee'] for x in trades)),funding=float(sum(x['funding'] for x in trades)))

def replay(ds,policies,schedule,cost=1,risk_fraction=.0025):
 start,end=ds['start'],ds['end'];N=(end-start)//HOUR;prices=ds['prices'];rules=venue_rules();fee=.0006*cost;friction=.0006*cost;positions={};cash=10000.;risk=Risk();trades=[];marks=[];daily=[];stats=Counter();trace=[];last_exit={};current=None;day_start=10000.;day_block=False;schedule=sorted(schedule);polname=schedule[0][1];sched_i=0
 def eq(i,col=0):return cash+sum(p['side']*p['qty']*(prices[s][i,col]-p['fill']) for s,p in positions.items())
 def close(s,ref,t,reason):
  nonlocal cash
  p=positions.pop(s);tick=rules[s]['tick'];raw=ref*(1-p['side']*friction);fill=(math.floor(raw/tick+1e-9) if p['side']==1 else math.ceil(raw/tick-1e-9))*tick;ef=p['qty']*fill*fee;pnl=p['side']*p['qty']*(fill-p['fill']);cash+=pnl-ef;net=pnl-p['fee']-ef+p['funding'];trades.append(dict(symbol=s,side=p['side'],entry=p['entered'],exit=t,entry_fill=p['fill'],exit_fill=fill,qty=p['qty'],entry_fee=p['fee'],exit_fee=ef,funding=p['funding'],net=net,reason=reason,hold_hours=(t-p['entered'])/HOUR,policy=p['policy'],risk_fraction=p['risk_fraction']));stats['fees']+=ef;risk.closed(net,t);last_exit[s]=t
 for i in range(N):
  t=start+i*HOUR
  while sched_i+1<len(schedule) and schedule[sched_i+1][0]<=t:sched_i+=1
  newname=schedule[sched_i][1]
  # Funding exactly at the open applies to positions already held.
  for s,p in positions.items():
   for when,rate in ds['funding'][s].get(t,[]):
    if when==t:
     pay=-p['side']*p['qty']*prices[s][i,0]*rate;p['funding']+=pay;cash+=pay;stats['funding']+=pay
  if newname!=polname:
   for s in list(positions):close(s,prices[s][i,0],t,'POLICY_SWITCH')
   polname=newname
  pol=policies[polname];control=polname in ['reference','buy_hold','short_hold','cash'];adaptive=not control
  rf=float(pol.get('risk_fraction',risk_fraction));base=pol.get('base_name',polname);hold=base in ['buy_hold','short_hold'];reference=base=='reference';p=pol
  if i%24==0:day_start=eq(i);day_block=False
  if adaptive:
   factor=risk.factor(eq(i),t)
   if eq(i)<=day_start*.96:day_block=True
   if risk.halt or day_block:
    for s in list(positions):close(s,prices[s][i,0],t,'RISK_HALT')
  for s,pos in list(positions.items()):
   if hold:continue
   op=prices[s][i,0];sd=pos['side'];d=i-1;si=SYMS.index(s)
   if t-pos['entered']>=pos['horizon']*HOUR:close(s,op,t,'TIME');continue
   if sd*(op-pos['stop'])<=0:close(s,op,t,'GAP_STOP');continue
   if reference and sd*(op-pos['target'])>=0:close(s,op,t,'GAP_TARGET');continue
   if i>0 and (t//HOUR)%4==1 and not reference and p['gate'][d,si]!=9 and p['gate'][d,si]!=sd:close(s,op,t,'SIGNAL_EXIT')
  candidates=[]
  if i>0 and (t//HOUR)%4==1 and not day_block and (not adaptive or risk.factor(eq(i),t)>0):
   d=i-1
   for si,s in enumerate(SYMS):
    sd=int(p['side'][d,si]);st=float(p['stop'][d,si])
    if sd and np.isfinite(st) and st>0:candidates.append((float(p['score'][d,si]),s,sd,st))
  candidates.sort(key=lambda x:(-x[0],x[1],-x[2]));entry_eq=eq(i);gross=sum(pos['qty']*prices[s][i,0] for s,pos in positions.items())
  for score,s,sd,st in candidates:
   if s in positions or last_exit.get(s,-1)>=t or len(positions)>=3:continue
   factor=1. if not adaptive else risk.factor(entry_eq,t)
   if factor==0:continue
   weight=.15 if reference else .2;budget=min(weight*entry_eq,max(0,.6*entry_eq-gross)/(1+fee),prices[s][max(i-1,0),4]*.001)
   if not hold:budget=min(budget,rf*factor*entry_eq/(st+2*(fee+friction)))
   order=entry_order(prices[s][i,0],sd,budget,rules[s],friction)
   if order is None:stats['execution_rejections']+=1;continue
   fill,qty=order;ef=qty*fill*fee;cash-=ef;entry_eq-=ef;gross+=qty*fill;stats['fees']+=ef;stats['entries']+=1;positions[s]=dict(side=sd,qty=qty,fill=fill,fee=ef,entered=t,stop=fill*(1-sd*st),target=fill*(1+sd*.15),horizon=168 if reference else 336,funding=0.,policy=polname,risk_fraction=rf)
   trace.append(dict(time=t,decision_time=t-HOUR,symbol=s,side=sd,stop_fraction=st,qty=qty,notional=qty*fill,policy=polname))
  # Funding inside the hour cannot affect beginning-of-hour sizing. If a
  # stop could predate payment, debit adverse amounts and skip positive ones.
  for s,pos in list(positions.items()):
   op,hi,lo,cl,_=prices[s][i];sd=pos['side'];sh=(lo<=pos['stop']) if sd==1 else (hi>=pos['stop']);th=((hi>=pos['target']) if sd==1 else (lo<=pos['target'])) if reference else False
   for when,rate in ds['funding'][s].get(t,[]):
    if when>t:
     pay=-sd*pos['qty']*op*rate
     if pos['entered']==t or (not hold and (sh or th)):pay=min(0.,pay)
     pos['funding']+=pay;cash+=pay;stats['funding']+=pay
   if not hold:
    if sh:
     if th:stats['stop_target_ambiguous']+=1
     close(s,pos['stop'],t+HOUR,'STOP');continue
    if th:close(s,pos['target'],t+HOUR,'TARGET');continue
    if not reference:
     si=SYMS.index(s);tf=float(p['trail'][i,si])
     if np.isfinite(tf):pos['stop']=max(pos['stop'],cl*(1-tf)) if sd==1 else min(pos['stop'],cl*(1+tf))
  value=eq(i,3);marks.append(value)
  if adaptive:risk.factor(value,t+HOUR)
  if (i+1)%24==0:daily.append(value)
 for s in list(positions):close(s,prices[s][N-1,3],end,'END')
 marks[-1]=cash;daily[-1]=cash;assert math.isclose(cash,10000+sum(x['net'] for x in trades),abs_tol=1e-5)
 out=summary(daily,trades,marks,start,end);out.update(stats=dict(stats),halted=risk.halt,continuous_risk_state=True);return out,daily,trades,np.asarray(marks),trace
