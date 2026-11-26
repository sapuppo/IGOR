"""Minute taker replay. Never reads future outcomes when selecting orders."""
from pathlib import Path
from collections import Counter
from dataclasses import dataclass
import json,math
from decimal import Decimal
from data27 import R,P,R26,STEP,DAY,SYMS,HORIZONS,ms
from third_party.hypergrok_stop import price_stop
import numpy as np,pandas as pd

@dataclass
class Risk:
 peak:float=10000.;streak:int=0;pause_until:int=0;halt:bool=False
 def factor(self,equity,t):
  self.peak=max(self.peak,equity)
  if equity<=self.peak*.8:self.halt=True
  if self.halt or t<self.pause_until:return 0.
  return .5 if equity<=self.peak*.92 else 1.
 def closed(self,net,t):
  self.streak=self.streak+1 if net<0 else 0
  if self.streak>=3:self.pause_until=max(self.pause_until,t+60*STEP);self.streak=0

def rules():
 out={}
 for s in json.loads((R26/'exchange_filters.json').read_text())['symbols']:
  f={x['filterType']:x for x in s['filters']};lot=f['LOT_SIZE'];market=f['MARKET_LOT_SIZE'];pf=f['PRICE_FILTER']
  out[s['symbol']]=dict(tick=float(pf['tickSize']),step=float(lot['stepSize']),minqty=max(float(lot['minQty']),float(market['minQty'])),maxqty=min(float(lot['maxQty']),float(market['maxQty'])),minnotional=float(f.get('MIN_NOTIONAL',{}).get('notional',5)),minprice=float(pf['minPrice']),maxprice=float(pf['maxPrice']))
 return out

def size_order(ref,side,budget,rule,friction):
 raw=ref*(1+side*friction);tick=rule['tick']
 fill=(math.ceil(raw/tick-1e-9) if side==1 else math.floor(raw/tick+1e-9))*tick
 qty=math.floor(min(budget/fill,rule['maxqty'])/rule['step']+1e-9)*rule['step']
 if qty<rule['minqty'] or qty*fill<rule['minnotional'] or fill<rule['minprice'] or fill>rule['maxprice']:return None
 assert qty*fill<=budget+1e-6
 return fill,qty

def get_data(start,end):
 a=ms(start);b=ms(end);out={};fund={};latest={};available={};reference={}
 for sym in SYMS:
  prices=np.load(R26/'prepared'/(sym+'_prices.npy'));times=np.load(R26/'prepared'/(sym+'_times.npy'));sel=(times>=a)&(times<b)
  out[sym]=prices[sel];available[sym]=times[sel];assert np.all(np.diff(available[sym])==STEP) and available[sym][0]==a and available[sym][-1]==b-STEP
  f=pd.read_pickle(R26/'prepared'/(sym+'_funding.pkl'));ts=f.fundingTime.to_numpy();rr=f.fundingRate.to_numpy();mapping={}
  for t,rate in zip(ts,rr):
   if a<=t<b:mapping.setdefault(int(t//STEP*STEP),[]).append((int(t),float(rate)))
  fund[sym]=mapping
  # Estimated future funding based only on last published event, not final rate.
  ix=np.searchsorted(ts,available[sym],side='left')-1;last=np.where(ix>=0,rr[np.maximum(ix,0)],.0001);age=available[sym]-ts[np.maximum(ix,0)];last=np.where((ix>=0)&(age<16*3600000),last,.0001);latest[sym]=last
 return dict(start=a,end=b,prices=out,funding=fund,last_rate=latest)

def summary(daily,trades,minute_equity,start,end):
 eq=np.array(daily);v=np.r_[10000.,eq];dr=v[1:]/v[:-1]-1;std=dr.std(ddof=1) if len(dr)>1 else 0
 times=pd.to_datetime(np.arange(start+DAY,end+1,DAY)-1,unit='ms',utc=True);s=pd.Series(eq,index=times);m=s.resample('ME').last();mr=m/m.shift(fill_value=10000)-1
 net=np.array([t['net'] for t in trades]);loss=-net[net<0].sum();mv=np.r_[10000.,minute_equity]
 days=(end-start)/DAY
 return dict(total_return=float(v[-1]/10000-1),monthly_equivalent=float((v[-1]/10000)**(30.4375/days)-1),monthly={t.strftime('%Y-%m'):float(x) for t,x in mr.items()},max_drawdown=float((1-mv/np.maximum.accumulate(mv)).max()),sharpe=float(dr.mean()/std*np.sqrt(365)) if std>0 else 0.,profit_factor=float(net[net>0].sum()/loss) if loss>0 else None,trades=len(trades),win_rate=float((net>0).mean()) if len(net) else 0.,mean_hold_minutes=float(np.mean([t['hold_minutes'] for t in trades])) if len(trades) else 0.,days=days)

def forecast_table(ds,pred,variant,cost):
 book=variant not in ['mean_payoff_price','magnitude_price','duration_price']
 kind='book' if book else 'price'
 arr=pred['p_'+kind];gain=pred['gain_'+kind];loss=pred['loss_'+kind]
 if variant=='mean_payoff_price':
  gain=pred['mean_price'][None,None,:,0,None];loss=pred['mean_price'][None,None,:,1,None]
 expected=arr*gain-(1-arr)*loss
 if variant in ['direct_book','conservative_book']:
  expected=pred['direct_book']
  if variant=='conservative_book':expected=expected-.5*pred['rms_book'][None,None,:,None]
 rate=np.stack([ds['last_rate'][s] for s in SYMS],axis=1)[:,:,None,None]
 # ds row t represents decision at t, with entry at t+one minute.
 entrytimes=ds['start']+np.arange(len(arr))*STEP+STEP
 nextsettle=(entrytimes//28800000+1)*28800000
 cross=(entrytimes[:,None,None,None]+np.array(HORIZONS)[None,None,:,None]*STEP>=nextsettle[:,None,None,None])
 funding=np.maximum(0,rate*np.array([1,-1])[None,None,None,:])*cross
 ev=pred['stop'][:,:,:,None]*expected-.0024*cost-funding
 valid=np.isfinite(ev)&pred['book'][:,:,None,None]&(ev>0)
 if variant.startswith('duration_book_h'):
  h=int(variant.removeprefix('duration_book_h'));valid &= (np.array(HORIZONS)==h)[None,None,:,None]
 tau=pred['duration_'+kind]
 score=ev if variant in ['mean_payoff_price','magnitude_price'] else ev/np.maximum(1,tau)
 score=np.where(valid,score,-np.inf).reshape(len(arr),-1)
 return arr.reshape(len(arr),-1),ev.reshape(len(arr),-1),score,np.argsort(-score,axis=1,kind='stable')

def replay(ds,pred,variant,cost=1,reference=False):
 start=ds['start'];end=ds['end'];fee=.0006*cost;friction=.0006*cost;rule=rules();risk=Risk();positions={};cash=10000.;trades=[];daily=[];marks=[];stats=Counter();day_start=10000.;day_block=False;trace=[];last_exit={}
 prices=ds['prices'];N=(end-start)//STEP;adaptive=not reference and variant!='duration_book_no_adaptive'
 if not reference and variant!='rule_momentum':probtable,evtable,scoretable,orders=forecast_table(ds,pred,variant,cost)
 # pred arrays: [decision minute, sym, horizon, side] and calibration statistics.
 def equity(i,col=0):return cash+sum(p['side']*p['qty']*(prices[s][i,col]-p['entry_fill']) for s,p in positions.items())
 def close(s,ref,t,why):
  nonlocal cash
  p=positions.pop(s);tick=rule[s]['tick'];raw=ref*(1-p['side']*friction);fill=(math.floor(raw/tick+1e-9) if p['side']==1 else math.ceil(raw/tick-1e-9))*tick
  exitfee=p['qty']*fill*fee;pnl=p['side']*p['qty']*(fill-p['entry_fill']);cash+=pnl-exitfee;net=pnl-p['entry_fee']-exitfee+p['funding'];stats['fees']+=exitfee;stats['spread_slippage']+=p['qty']*abs(ref-fill)
  trades.append(dict(symbol=s,side=p['side'],entry=p['entered'],exit=t,entry_fill=p['entry_fill'],exit_fill=fill,qty=p['qty'],entry_fee=p['entry_fee'],exit_fee=exitfee,funding=p['funding'],net=net,reason=why,hold_minutes=(t-p['entered'])/STEP,predicted_probability=p['p'],predicted_ev=p['ev'],rank=p['rank'],horizon=p['horizon']))
  if adaptive:risk.closed(net,t)
  last_exit[s]=t
 for i in range(N):
  t=start+i*STEP
  if i%1440==0:day_start=equity(i);day_block=False
  for sym,p in list(positions.items()):
   for when,rate in ds['funding'][sym].get(t,[]):
    # Existing position definitely present at open; price proxy for mark.
    pay=-p['side']*p['qty']*prices[sym][i,0]*rate;p['funding']+=pay;cash+=pay;stats['funding']+=pay
  eq=equity(i)
  if adaptive:
   factor=risk.factor(eq,t)
   if eq<=day_start*.96:day_block=True
   if risk.halt or day_block:
    for sym in list(positions):close(sym,prices[sym][i,0],t,'RISK_HALT')
  # Definite open exits before ranking; intrabar outcomes processed AFTER entries.
  for sym,p in list(positions.items()):
   op=prices[sym][i,0];side=p['side']
   if t-p['entered']>=p['horizon']*STEP:close(sym,op,t,'TIME');continue
   if side*(op-p['stop'])<=0:close(sym,op,t,'GAP_STOP');continue
   if side*(op-p['target'])>=0:close(sym,op,t,'GAP_TARGET')
  candidates=[]
  if i>0 and not day_block and (not adaptive or risk.factor(equity(i),t)>0):
   # Prediction made at prior minute close, filled after one full minute delay.
   d=i-1
   if reference:
    for si,sym in enumerate(SYMS):
     side=int(pred['signal'][d,si])
     if side:candidates.append(dict(sym=sym,side=side,stop=float(pred['stop'][d,si]),horizon=10080,p=.5,ev=0.,rank=float(pred['strength'][d,si])))
   elif variant=='rule_momentum':
    for si,sym in enumerate(SYMS):
     side=int(pred['rule_side'][d,si]);st=float(pred['stop'][d,si,2])
     if side and np.isfinite(st):candidates.append(dict(sym=sym,side=side,stop=st,horizon=180,p=.5,ev=0.,rank=1.))
   else:
    for k in orders[d]:
     rank=float(scoretable[d,k])
     if not np.isfinite(rank):break
     si=int(k)//6;hi=int(k)%6//2;di=int(k)%2;sym=SYMS[si]
     if sym in positions:continue
     candidates.append(dict(sym=sym,side=1 if di==0 else -1,stop=float(pred['stop'][d,si,hi]),horizon=HORIZONS[hi],p=float(probtable[d,k]),ev=float(evtable[d,k]),rank=rank))
  candidates.sort(key=lambda x:(-x['rank'],x['sym'],-x['side'],x['horizon']))
  # Same-open equity snapshot; only fees/exposure reservations change per entry.
  entry_eq=equity(i);gross=sum(p['qty']*prices[s][i,0] for s,p in positions.items())
  for c in candidates:
   s=c['sym'];side=c['side']
   if s in positions or last_exit.get(s,-1)>=t or len(positions)>=3:continue
   factor=1. if not adaptive else risk.factor(entry_eq,t)
   if factor==0:continue
   maxweight=.15 if reference else .2
   notional=min(maxweight*entry_eq,.0025*factor*entry_eq/(c['stop']+2*(fee+friction)),max(0.,.6*entry_eq-gross)/(1+fee),prices[s][max(0,i-1),4]*.001)
   order=size_order(prices[s][i,0],side,notional,rule[s],friction)
   if order is None:stats['execution_rejections']+=1;continue
   fill,qty=order
   # Reuse HyperGrok's reviewed pure stressed-stop sizing, unchanged MIT code.
   decimals=max(0,-Decimal(str(rule[s]['step'])).as_tuple().exponent)
   cap=price_stop(Decimal(str(fill)),Decimal(str(fill*(1-side*c['stop']))),Decimal(str(entry_eq)),Decimal(str(.25*factor)),Decimal(str(fee*100)),Decimal(str(friction*10000)),decimals)['stressed_stop']['size']
   qty=min(qty,float(cap))
   if qty<rule[s]['minqty'] or qty*fill<rule[s]['minnotional']:continue
   entryfee=qty*fill*fee;cash-=entryfee;entry_eq-=entryfee;gross+=qty*fill;stats['fees']+=entryfee;stats['spread_slippage']+=qty*abs(fill-prices[s][i,0]);stats['entries']+=1
   positions[s]=dict(side=side,qty=qty,entry_fill=fill,entry_fee=entryfee,entered=t,stop=fill*(1-side*c['stop']),target=fill*(1+side*(.15 if reference else 2*c['stop'])),funding=0.,horizon=c['horizon'],p=c['p'],ev=c['ev'],rank=c['rank'])
   if len(trace)<10000:trace.append(dict(timestamp=t,**c,notional=qty*fill))
  # Full candle range cannot affect any beginning-of-candle order decision.
  for s,p in list(positions.items()):
   op,hi,lo,cl,_=prices[s][i];side=p['side'];sh=lo<=p['stop'] if side==1 else hi>=p['stop'];th=hi>=p['target'] if side==1 else lo<=p['target']
   if p['entered']==t:
    # Unknown entry order vs intrabar funding; debit adverse cash flows only.
    for when,rate in ds['funding'][s].get(t,[]):
     if when>t:
      pay=min(0.,-side*p['qty']*op*rate);p['funding']+=pay;cash+=pay;stats['funding']+=pay
   if sh:
    if th:stats['stop_target_ambiguous']+=1
    close(s,p['stop'],t+STEP,'STOP')
   elif th:close(s,p['target'],t+STEP,'TARGET')
  eq=equity(i,3);marks.append(eq)
  if adaptive:risk.factor(eq,t+STEP)
  if (i+1)%1440==0:daily.append(eq)
 for s in list(positions):close(s,prices[s][N-1,3],end,'END')
 marks[-1]=cash;daily[-1]=cash
 assert math.isclose(cash,10000+sum(x['net'] for x in trades),abs_tol=1e-5)
 r=summary(daily,trades,marks,start,end);r.update(stats=dict(stats),halted=risk.halt)
 return r,daily,trades,np.array(marks,dtype=np.float64),trace
