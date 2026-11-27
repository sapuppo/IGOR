"""Account inventory reconstruction, not a strategy or order sender.

The export lacks startPosition. Infer only an initial inventory uniquely
identified by direction constraints over the entire observed window. This
uses later records for accounting; it must never be used as a predictive
feature at the start of a backtest.
"""
from dataclasses import dataclass,field
from decimal import Decimal
D=Decimal;ZERO=D(0)
DIRECTIONS={'Open Long':1,'Close Short':1,'Short > Long':1,'Open Short':-1,'Close Long':-1,'Long > Short':-1}

@dataclass
class Interval:
 cumulative:Decimal=ZERO
 lower:Decimal|None=None
 upper:Decimal|None=None
 lower_strict:bool=False
 upper_strict:bool=False
 rows:int=0
 def low(self,b,strict=False):
  if self.lower is None or b>self.lower:self.lower=b;self.lower_strict=strict
  elif b==self.lower:self.lower_strict |= strict
 def high(self,b,strict=False):
  if self.upper is None or b<self.upper:self.upper=b;self.upper_strict=strict
  elif b==self.upper:self.upper_strict |= strict
 def add(self,direction,size):
  size=D(size)
  if size<=0 or direction not in DIRECTIONS:raise ValueError('Invalid fill')
  pre=self.cumulative;post=pre+DIRECTIONS[direction]*size
  if direction=='Open Long':self.low(-pre)
  elif direction=='Open Short':self.high(-pre)
  elif direction=='Close Long':self.low(-pre,True);self.low(-post)
  elif direction=='Close Short':self.high(-pre,True);self.high(-post)
  elif direction=='Long > Short':self.low(-pre,True);self.high(-post,True)
  elif direction=='Short > Long':self.high(-pre,True);self.low(-post,True)
  self.cumulative=post;self.rows+=1
 @property
 def valid(self):
  return self.lower is None or self.upper is None or self.lower<self.upper or (self.lower==self.upper and not self.lower_strict and not self.upper_strict)
 @property
 def identified(self):return self.valid and self.lower is not None and self.lower==self.upper
 def asdict(self):
  return dict(rows=self.rows,lower=str(self.lower) if self.lower is not None else None,upper=str(self.upper) if self.upper is not None else None,lower_strict=self.lower_strict,upper_strict=self.upper_strict,valid=self.valid,identified=self.identified,initial=str(self.lower) if self.identified else None,ending=str(self.lower+self.cumulative) if self.identified else None)

def legs(q,direction,size):
 """Validate against inferred state and split a reversal without double counting."""
 q=D(q);size=D(size);delta=DIRECTIONS[direction]*size;new=q+delta
 valid={'Open Long':q>=0,'Open Short':q<=0,'Close Long':q>0 and new>=0,'Close Short':q<0 and new<=0,'Long > Short':q>0 and new<0,'Short > Long':q<0 and new>0}[direction]
 if not valid:raise ValueError(f'Inventory contradiction: {q} {direction} {size}')
 if q!=0 and q*delta<0:
  closing=min(abs(q),size);opening=size-closing
 else:closing=ZERO;opening=size
 return new,opening,closing

@dataclass
class Campaign:
 side:int
 started:int|None
 initial_inherited:bool
 entry_notional:float=0.
 exit_notional:float=0.
 max_abs_quantity:float=0.
 fills:int=0
 gross_closed_reported:float=0.
 gross_missing_close:bool=False
 fees_reported:float=0.
 fee_missing:bool=False
 non_usdc_fee:bool=False

@dataclass
class CampaignTracker:
 q:Decimal
 current:Campaign|None=field(init=False,default=None)
 completed:list=field(default_factory=list)
 observed_flats:int=0
 def __post_init__(self):
  self.q=D(self.q)
  if self.q:self.current=Campaign(1 if self.q>0 else -1,None,True,max_abs_quantity=float(abs(self.q)))
 def add(self,direction,size,price,time,fee,pnl,fee_token='USDC'):
  old=self.q;new,opening,closing=legs(old,direction,size);total=float(D(size));price=float(price)
  allocations=[]
  if closing:
   if self.current is None:raise ValueError('Closing without campaign')
   c=self.current;c.fills+=1;c.exit_notional+=float(closing)*price;c.gross_closed_reported+=float(pnl) if pnl is not None else 0;c.gross_missing_close |= pnl is None
   frac=float(closing)/total;c.fees_reported+=(fee*frac if fee is not None else 0);c.fee_missing |= fee is None;c.non_usdc_fee |= fee_token!='USDC';allocations.append(c)
   if closing==abs(old):
    self.completed.append(dict(side=c.side,started=c.started,ended=time,inherited=c.initial_inherited,hold_minutes=(time-c.started)/60000 if c.started is not None else None,entry_notional=c.entry_notional,exit_notional=c.exit_notional,max_abs_quantity=c.max_abs_quantity,fills=c.fills,gross_closed_reported=c.gross_closed_reported,fees_reported=c.fees_reported,fee_missing=c.fee_missing,gross_missing_close=c.gross_missing_close,non_usdc_fee=c.non_usdc_fee,net_before_funding=(c.gross_closed_reported-c.fees_reported) if not (c.initial_inherited or c.fee_missing or c.gross_missing_close or c.non_usdc_fee) else None));self.current=None;self.observed_flats+=1
  if opening:
   if self.current is None:self.current=Campaign(1 if new>0 else -1,time,False)
   c=self.current;c.fills+=1;c.entry_notional+=float(opening)*price;c.max_abs_quantity=max(c.max_abs_quantity,float(abs(new)));frac=float(opening)/total;c.fees_reported+=(fee*frac if fee is not None else 0);c.fee_missing |= fee is None;c.non_usdc_fee |= fee_token!='USDC';allocations.append(c)
  self.q=new
  return new
