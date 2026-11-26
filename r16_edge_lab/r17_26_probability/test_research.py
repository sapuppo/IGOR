import unittest
from decimal import Decimal
import numpy as np,pandas as pd
from prepare import feature_frame,attach_book,labels,STEP,book_frame
from probability import kalman_probability,expected_value
from execution import size_order,Risk
from live_book import snapshot_features
from third_party.hypergrok_stop import price_stop
from third_party.vibe_risk import max_drawdown_analysis
class ResearchTests(unittest.TestCase):
 def frame(self,n=500):
  c=100+np.arange(n)*.005+np.sin(np.arange(n)/9)
  return pd.DataFrame(dict(open=c-.01,high=c+.1,low=c-.1,close=c,quote_volume=1e6,taker_buy_quote_volume=6e5),index=np.arange(n)*STEP)
 def test_features_prefix_and_future_perturbation(self):
  f=self.frame();x=feature_frame(f);pd.testing.assert_frame_equal(x.iloc[:350],feature_frame(f.iloc[:350]))
  f.iloc[350:,f.columns.get_loc('close')]*=2;pd.testing.assert_frame_equal(x.iloc[:350],feature_frame(f).iloc[:350])
 def test_book_strict_past_and_stale(self):
  b=pd.DataFrame([[.1,.2,10],[.2,.3,11]],index=[60001,180001]);dec=np.array([60001,60002,180001,400000]);v,age,valid=attach_book(dec,b)
  self.assertEqual(list(valid),[False,True,True,False]);self.assertEqual(v[2,0],.1)
 def test_conflicting_book_duplicates_rejected(self):
  f=pd.DataFrame(dict(timestamp=['2026-01-01']*2,percentage=[.2,.2],notional=[1,2]))
  with self.assertRaises(AssertionError):book_frame(f)
 def test_book_imbalance_not_volume_proxy(self):
  snap=dict(timestamp_ms=0,bid_notional_02=30,ask_notional_02=10,bid_notional_1=90,ask_notional_1=10)
  x=snapshot_features(snap,60000);self.assertEqual(x['imbalance02'],.5);self.assertEqual(x['imbalance1'],.8)
  with self.assertRaises(ValueError):snapshot_features(snap,1000)
 def test_label_entry_after_latency(self):
  f=self.frame(50);p=f[['open','high','low','close','quote_volume']].to_numpy();p[:,0:4]=100;p[0]=[10,10,10,10,1];p[1]=[20,20,20,20,1]
  r,d=labels(p,np.full(len(p),.005),8,1);self.assertEqual(r[0],0);self.assertEqual(d[0],8)
 def test_ambiguous_labels_stop_first(self):
  p=np.tile([100,100,100,100,1],(40,1)).astype(float);p[2]=[100,110,90,100,1]
  for side in [1,-1]:
   r,d=labels(p,np.full(40,.005),8,side);self.assertAlmostEqual(r[0],-1);self.assertEqual(d[0],1)
 def test_kalman_prefix_invariance(self):
  p=np.linspace(.1,.9,100);t=np.arange(100)*STEP
  np.testing.assert_allclose(kalman_probability(p,t)[:50],kalman_probability(p[:50],t[:50]))
 def test_rank_cost_and_duration(self):
  a,ar,ta=expected_value(.6,.005,2,-1,5,5,.0024);b,br,tb=expected_value(.6,.005,2,-1,15,15,.0024)
  self.assertAlmostEqual(a,b);self.assertAlmostEqual(ar,br*3)
  ev,_,_=expected_value(.3,.002,2,-1,5,5,.0024);self.assertLess(ev,0)
 def test_rounding_final_fill_preserves_budget(self):
  rule=dict(tick=.1,step=.001,minqty=.001,maxqty=100,minnotional=5,minprice=.01,maxprice=1e6)
  for side in [1,-1]:
   price,qty=size_order(100.09,side,100,rule,.0006);self.assertLessEqual(price*qty,100+1e-8)
 def test_imported_stressed_stop_stays_within_budget(self):
  for stop in ['99','101']:
   x=price_stop(Decimal(100),Decimal(stop),Decimal(10000),Decimal('.25'),Decimal('.06'),Decimal(6),3)
   self.assertLessEqual(x['stressed_stop']['loss_if_triggered'],Decimal(25));self.assertGreater(x['drawn_stop']['loss_if_triggered'],Decimal(25))
 def test_loss_pause_and_drawdown_halt(self):
  r=Risk();r.closed(-1,0);r.closed(-1,0);r.closed(-1,0)
  self.assertEqual(r.factor(10000,1),0);self.assertEqual(r.factor(10000,60*STEP),1)
  self.assertEqual(r.factor(9100,61*STEP),.5);self.assertEqual(r.factor(7900,62*STEP),0);self.assertEqual(r.factor(11000,63*STEP),0)
 def test_imported_drawdown_includes_initial_capital(self):
  x=max_drawdown_analysis(pd.Series([10000.,9000.,9500.]));self.assertAlmostEqual(x['max_drawdown'],.1)
if __name__=='__main__':unittest.main()
