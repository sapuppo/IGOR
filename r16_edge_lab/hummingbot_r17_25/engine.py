"""15m OHLC execution scenario, NOT order-book queue simulation; no live APIs."""
from dataclasses import dataclass
from collections import Counter
import math,json
from pathlib import Path
import numpy as np,pandas as pd
from data import STEP,BAR,DAY,SYMS

@dataclass
class Risk:
 peak:float=10000.;streak:int=0;pause_until:int=0;halted:bool=False
 def observe(self,equity):
  self.peak=max(self.peak,equity)
  if equity<=self.peak*.80:self.halted=True
 def factor(self,equity,t):
  self.observe(equity)
  if self.halted or t<self.pause_until:return 0.
  return .5 if equity<=self.peak*.92 else 1.
 def closed(self,net,t):
  self.streak=self.streak+1 if net<0 else 0
  if self.streak>=3:self.pause_until=max(self.pause_until,t+DAY);self.streak=0

def round_order(price,qty,side,rule):
 # Buy quote rounded down, sell quote up; quantity always down.
 tick=rule['tick'];step=rule['step'];price=(math.floor(price/tick+1e-9) if side==1 else math.ceil(price/tick-1e-9))*tick
 qty=math.floor(qty/step+1e-9)*step
 if qty<rule['minqty'] or qty>rule['maxqty'] or qty*price<rule['minnotional']:return None
 return price,qty

def maker_side(op,hi,lo,bid,ask,penetration):
 # Crossed post-only quotes would have been rejected at activation.
 buy=lo<bid*(1-penetration)
 sell=hi>ask*(1+penetration)
 if buy and sell:return 0  # unidentified first fill, exclude both
 return 1 if buy else -1 if sell else 0

def metrics(daily,trades,capital=10000):
 d=pd.DataFrame(daily);v=np.r_[capital,d.equity.to_numpy()];ret=v[1:]/v[:-1]-1
 dates=pd.to_datetime(d.timestamp-1,unit='ms',utc=True)
 s=pd.Series(d.equity.to_numpy(),index=dates);m=s.resample('ME').last();mr=m/m.shift(fill_value=capital)-1
 nets=np.array([x['net'] for x in trades]);profit=float(nets[nets>0].sum());loss=float(-nets[nets<0].sum());std=ret.std(ddof=1) if len(ret)>1 else 0
 return dict(total_return=float(v[-1]/capital-1),monthly_equivalent=float((v[-1]/capital)**(1/len(m))-1),max_daily_dd=float((1-v/np.maximum.accumulate(v)).max()),sharpe=float(ret.mean()/std*np.sqrt(365)) if std>0 else 0.,profit_factor=profit/loss if loss>0 else None,trades=len(trades),monthly={k.strftime('%Y-%m'):float(x) for k,x in mr.items()},positive_months=int((mr>0).sum()),months=len(m))

def replay(ds,spec,start,end,cost=1,adaptive=True):
 from strategies import intent
 assert start%DAY==0 and end%DAY==0 and start<end<=ds['end']
 raw=json.loads((Path(__file__).parent/'exchange_filters.json').read_text());rules={}
 for s in raw['symbols']:
  q={x['filterType']:x for x in s['filters']};lot=q['LOT_SIZE']
  rules[s['symbol']]=dict(tick=float(q['PRICE_FILTER']['tickSize']),step=float(lot['stepSize']),minqty=float(lot['minQty']),maxqty=float(lot['maxQty']),minnotional=float(q.get('MIN_NOTIONAL',{}).get('notional',5)))
 cash=10000.;positions={};pending={};trades=[];daily=[];marks=[];stats=Counter();risk=Risk();peak=10000.;maxdd=0.;last_features={};decision=0;day_open=10000.;day_block=False
 fee=.0006*cost;makerfee=.0002*cost;friction=(.0002+.0004)*cost;penetration=.0002 if cost==1 else .001
 fmaps={s:ds['features'][s].to_dict('index') for s in SYMS};prices=ds['prices'];fund=ds['funding'];first=(start-ds['start'])//STEP;last=(end-ds['start'])//STEP
 def equity(i,pricecol=0):return cash+sum(p['side']*p['qty']*(prices[s][i,pricecol]-p['entry_fill']) for s,p in positions.items())
 def close(s,ref,t,why):
  nonlocal cash
  p=positions.pop(s);fill=ref*(1-p['side']*friction);exitfee=p['qty']*fill*fee;pnl=p['side']*p['qty']*(fill-p['entry_fill'])
  net=pnl-p['entry_fee']-exitfee+p['funding'];cash+=pnl-exitfee;stats['fees']+=exitfee;stats['friction_cost']+=p['qty']*ref*friction
  tr=dict(symbol=s,entry=p['entered'],exit=t,side=p['side'],qty=p['qty'],entry_fill=p['entry_fill'],exit_fill=fill,entry_fee=p['entry_fee'],exit_fee=exitfee,funding=p['funding'],net=net,reason=why,mode=p['mode'],regime=p['regime'])
  trades.append(tr)
  if adaptive:risk.closed(net,t)
 def enter(s,side,ref,t,mode,i,atr,regime,maxqty=None):
  nonlocal cash,entry_equity,entry_gross
  eq=entry_equity;factor=risk.factor(eq,t) if adaptive else 1.
  if factor==0 or day_block or len(positions)>=4:return False
  stopfraction=max(.02,min(.12,2*atr/ref));entryfee=makerfee if mode=='pmm' else fee
  fill=ref if mode=='pmm' else ref*(1+side*friction)
  gross=entry_gross
  budget=min(.15*eq,.0025*factor*eq/(stopfraction+entryfee+fee+2*friction),max(0,.6*eq-gross)/(1+entryfee),float(prices[s][i-1,4])*.001)
  rounded=round_order(fill,min(budget/fill,maxqty) if maxqty is not None else budget/fill,side,rules[s])
  if rounded is None:stats['min_order_rejections']+=1;return False
  price,qty=rounded
  # Quotes must preserve exact tick level; taker adverse fill rounded adversely.
  if mode!='pmm':price=(math.ceil(fill/rules[s]['tick']) if side==1 else math.floor(fill/rules[s]['tick']))*rules[s]['tick']
  # Adverse tick rounding can raise notional above its risk budget. Re-floor
  # quantity using the FINAL fill price, including the market-lot maximum.
  qty=math.floor(min(qty,budget/price)/rules[s]['step']+1e-9)*rules[s]['step']
  if qty<rules[s]['minqty'] or qty*price<rules[s]['minnotional']:
   stats['min_order_rejections']+=1;return False
  charge=qty*price*entryfee;cash-=charge;entry_equity-=charge;entry_gross+=qty*price;stats['fees']+=charge
  if mode!='pmm':stats['friction_cost']+=qty*ref*friction
  target=price*(1+side*.15) if spec['family']=='control' else price+side*atr if mode=='pmm' else side*float('inf')
  positions[s]=dict(side=side,qty=qty,entry_fill=price,entry_fee=charge,entered=t,funding=0.,stop=price*(1-side*stopfraction),target=target,mode=mode,regime=regime)
  stats['entries']+=1;return True
 for i in range(first,last):
  t=ds['start']+i*STEP
  if t%DAY==0:day_open=equity(i);day_block=False
  # Existing positions settle before new orders. Intrabar timestamps use open proxy.
  for s,p in list(positions.items()):
   for when,rate in fund[s].get(t,[]):
    pay=-p['side']*p['qty']*prices[s][i,0]*rate;p['funding']+=pay;cash+=pay;stats['funding']+=pay
  eq=equity(i)
  if adaptive:
   risk.observe(eq)
   if eq<=day_open*.96:day_block=True
   if risk.halted or day_block:
    for s in list(positions):close(s,prices[s][i,0],t,'RISK_HALT')
    pending.clear()
  # Features indexed by availability (closed 4h candles). Submit after close;
  # orders are first eligible one full 15m bar later.
  if t%BAR==0:
   decision=t;pending.clear()
   last_features={s:fmaps[s].get(t) for s in SYMS}
   bs=last_features['BTCUSDT']['btc_side'] if last_features['BTCUSDT'] else 0
   for s in SYMS:
    row=last_features[s]
    if row is None:continue
    if s in positions and positions[s]['mode']=='trend' and spec['family']!='control':
     p=positions[s];new=row['close']-p['side']*3*row['atr'];p['stop']=max(p['stop'],new) if p['side']==1 else min(p['stop'],new)
    mode,side=intent(row,spec,bs)
    if mode=='cash':continue
    regime='trend' if row['eff']>=.35 else 'range' if row['eff']<=.20 else 'transition'
    pending[s]=dict(mode=mode,side=side,atr=row['atr'],regime=regime,reference=row['reference'],natr=row['natr'],ready=t+STEP,expires=t+BAR,activated=False)
  # Existing stops/gaps precede new entries; closing on same bar prevents reentry.
  closed=set()
  for s,p in list(positions.items()):
   op,hi,lo,cl,_=prices[s][i];side=p['side'];maxhold=BAR*(6 if p['mode']=='pmm' else 42)
   if t-p['entered']>=maxhold:close(s,op,t,'TIME');closed.add(s);continue
   gapstop=side*(op-p['stop'])<=0;gaptarget=side*(op-p['target'])>=0
   if gapstop or gaptarget:close(s,op,t,'GAP_STOP' if gapstop else 'GAP_TARGET');closed.add(s);continue
  # Only prices known at submission determine order levels and sizing; volume
  # participation uses previous 15m volume, never current bar volume.
  entry_equity=equity(i);entry_gross=sum(p['qty']*prices[s][i,0] for s,p in positions.items())
  for s,q in list(pending.items()):
   if s in positions or s in closed or t<q['ready'] or t>=q['expires']:continue
   if adaptive and (risk.factor(equity(i),t)==0 or day_block):continue
   op,hi,lo,cl,_=prices[s][i];mode=q['mode'];side=q['side'];ref=op
   if mode=='pmm':
    if not q['activated']:
     spread=spec['spread_atr']*q['natr'];tick=rules[s]['tick']
     q['bid']=math.floor(q['reference']*(1-spread)/tick)*tick;q['ask']=math.ceil(q['reference']*(1+spread)/tick)*tick
     if q['bid']>=op*(1-.0002*cost) or q['ask']<=op*(1+.0002*cost):stats['post_only_rejections']+=1;pending.pop(s);continue
     # Size the resting quote now; never increase it using later fill-bar data.
     eq=entry_equity;fac=risk.factor(eq,t) if adaptive else 1.
     q['quantities']={}
     for sd,px in [(1,q['bid']),(-1,q['ask'])]:
      sf=max(.02,min(.12,2*q['atr']/px))
      budget=min(.15*eq,.0025*fac*eq/(sf+makerfee+fee+2*friction),max(0,.6*eq-entry_gross)/(1+makerfee),prices[s][i-1,4]*.001)
      q['quantities'][sd]=max(0,budget/px)
     q['activated']=True
    side=maker_side(op,hi,lo,q['bid'],q['ask'],penetration)
    if side==0:continue
    ref=q['bid'] if side==1 else q['ask']
   if enter(s,side,ref,t,mode,i,q['atr'],q['regime'],q['quantities'][side] if mode=='pmm' else None):
    pending.pop(s);p=positions[s]
  # Resolve intrabar events only AFTER all order decisions. Their cash/PnL
  # cannot fund or veto another order at the beginning of this same candle.
  for s,p in list(positions.items()):
   op,hi,lo,cl,_=prices[s][i];side=p['side'];new=p['entered']==t
   if new and p['mode']=='pmm':
    for when,rate in fund[s].get(t,[]):
     pay=min(0.,-side*p['qty']*op*rate);p['funding']+=pay;cash+=pay;stats['funding']+=pay
   sh=lo<=p['stop'] if side==1 else hi>=p['stop']
   th=hi>=p['target'] if side==1 else lo<=p['target']
   if sh:
    if th:stats['ambiguous_stop_first']+=1
    ref=min(op,p['stop']) if side==1 else max(op,p['stop'])
    close(s,ref,t+STEP,'STOP')
   elif th and not (new and p['mode']=='pmm'):close(s,p['target'],t+STEP,'TARGET')
  eq=equity(i,3);peak=max(peak,eq);maxdd=max(maxdd,1-eq/peak)
  marks.append(dict(timestamp=t+STEP,equity=eq))
  if adaptive:risk.observe(eq)
  if (t+STEP)%DAY==0:daily.append(dict(timestamp=t+STEP,equity=eq))
 for s in list(positions):close(s,prices[s][last-1,3],end,'END')
 daily[-1]['equity']=cash;marks[-1]['equity']=cash;maxdd=max(maxdd,1-cash/peak)
 assert math.isclose(cash,10000+sum(x['net'] for x in trades),abs_tol=1e-6)
 result=metrics(daily,trades);result.update(max_15m_dd=maxdd,stats=dict(stats),halted=risk.halted,intraday_details=marks)
 return result,daily,trades
