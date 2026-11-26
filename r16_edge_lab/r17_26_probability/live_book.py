"""Read-only feature contract for a future paper feed; no order capability."""
import numpy as np

def snapshot_features(snapshot,decision_ms):
 ts=int(snapshot['timestamp_ms']);age=(decision_ms-(ts+1000))/1000
 if age<=0 or age>120:raise ValueError('future or stale depth snapshot')
 b02=float(snapshot['bid_notional_02']);a02=float(snapshot['ask_notional_02']);b1=float(snapshot['bid_notional_1']);a1=float(snapshot['ask_notional_1'])
 if min(b02,a02,b1,a1)<=0:raise ValueError('nonpositive depth')
 return dict(imbalance02=(b02-a02)/(b02+a02),imbalance1=(b1-a1)/(b1+a1),log_depth02=float(np.log1p(b02+a02)),book_age=age)
