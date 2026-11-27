"""Economic role from signed inventory, not a buy/sell or display-label guess."""
from decimal import Decimal as D

def classify(start_position,side,size):
 if start_position is None:raise ValueError('startPosition required; unknown inventory cannot be assumed zero')
 q=D(str(start_position));z=D(str(size))
 if z<=0 or side not in ['B','A']:raise ValueError('Invalid side/size')
 delta=z if side=='B' else -z;new=q+delta
 closing=min(abs(q),z) if q*delta<0 else D(0);opening=z-closing
 return dict(before=str(q),after=str(new),closing_quantity=str(closing),opening_quantity=str(opening),opening_side=(1 if delta>0 else -1) if opening else 0,closing_side=(1 if q>0 else -1) if closing else 0,observed_buy_is_new_long=bool(side=='B' and opening>0),reversal=bool(q*new<0))
