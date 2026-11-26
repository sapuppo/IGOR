import unittest
import numpy as np,pandas as pd
from data27 import STEP,DAY,SYMS,HORIZONS,FEATURES,BOOK_FEATURES,labels,long_features,stop_fraction
from models27 import sample
from engine27 import forecast_table,replay,size_order,Risk

def fixture(n=1440):
 prices={s:np.tile([100.,100.01,99.99,100.,1e8],(n,1)) for s in SYMS};ds=dict(start=0,end=n*STEP,prices=prices,funding={s:{} for s in SYMS},last_rate={s:np.zeros(n) for s in SYMS});shape=(n,3,3,2)
 p={k+'_'+kind:np.full(shape,v) for kind in ['price','book'] for k,v in [('p',.6),('gain',2.),('loss',1.),('duration',30.),('direct',.8)]};p.update(stop=np.full((n,3,3),.01),book=np.ones((n,3),bool),mean_price=np.tile([2.,1.,30.],(3,1)),rms_book=np.ones(3),rule_side=np.zeros((n,3),np.int8));return ds,p

class Tests(unittest.TestCase):
 def test_feature_prefix(self):
  rng=np.random.default_rng(27);c=100*np.exp(np.cumsum(rng.normal(0,.001,500)));v=np.c_[c,c,c,c,np.ones(500)];t=np.arange(500)*STEP;x=pd.DataFrame(index=t+STEP);a=long_features(x,v,t);b=long_features(x.iloc[:300],v[:300],t[:300]);np.testing.assert_allclose(a.iloc[:300],b,equal_nan=True)
 def test_atr_scaling(self):
  self.assertGreater(stop_fraction(.001,180),stop_fraction(.001,30));np.testing.assert_allclose(stop_fraction([0,1],180),[.003,.02])
 def test_horizon_exit(self):
  v=np.tile([100.,100.,100.,100.,1.],(400,1));v[182,0]=101;rr,d=labels(v,np.full(400,.01),180,1);self.assertEqual(d[0],180);self.assertAlmostEqual(rr[0],1.)
 def test_label_stop_first(self):
  v=np.tile([100.,100.,100.,100.,1.],(400,1));v[2,1:3]=[103,98];rr,d=labels(v,np.full(400,.01),180,1);self.assertAlmostEqual(rr[0],-1);self.assertEqual(d[0],1)
 def test_purge_and_book_cohort(self):
  n=1000;t=np.arange(n)*STEP;f=pd.DataFrame(1.,index=t,columns=list(dict.fromkeys(FEATURES+BOOK_FEATURES+['stop_180','r_180_1','r_180_-1','d_180_1','d_180_-1'])));f['book_valid']=True;f.loc[300*STEP,'book_valid']=False;frames={s:f for s in SYMS};a=sample(frames,0,n*STEP,180,False);b=sample(frames,0,n*STEP,180,True);np.testing.assert_array_equal(a[3],b[3]);self.assertLess(a[3].max()+181*STEP,n*STEP);self.assertNotIn(300*STEP,a[3])
 def test_conditional_gain_loss(self):
  ds,p=fixture(2);_,ev,_,_=forecast_table(ds,p,'magnitude_price',1);self.assertAlmostEqual(ev[0,0],.01*(.6*2-.4)-.0024);p['gain_price'][0,0,0,0]=3;self.assertGreater(forecast_table(ds,p,'magnitude_price',1)[1][0,0],ev[0,0]);self.assertAlmostEqual(forecast_table(ds,p,'mean_payoff_price',1)[1][0,0],ev[0,0])
 def test_duration_and_horizon(self):
  ds,p=fixture(2);p['duration_book'][0,0,0,0]=10;_,ev,score,order=forecast_table(ds,p,'duration_book',1);self.assertEqual(order[0,0],0);self.assertAlmostEqual(score[0,0],ev[0,0]/10);score=forecast_table(ds,p,'duration_book_h180',1)[2];self.assertTrue(np.isneginf(score[:,[0,1,2,3,6,7]]).all())
 def test_cost_and_book(self):
  ds,p=fixture(2);a=forecast_table(ds,p,'duration_book',1)[1];b=forecast_table(ds,p,'duration_book',2)[1];np.testing.assert_allclose(a-b,.0024);p['book'][:]=False
  for v in ['magnitude_price','duration_price','duration_book']:self.assertTrue(np.isneginf(forecast_table(ds,p,v,1)[2]).all())
 def test_direct_conservative(self):
  ds,p=fixture(2);a=forecast_table(ds,p,'direct_book',1)[1];b=forecast_table(ds,p,'conservative_book',1)[1];np.testing.assert_allclose(a-b,.005)
 def test_negative_ev_skip(self):
  ds,p=fixture();p['gain_book'][:]=.01;result=replay(ds,p,'duration_book');self.assertEqual(result[0]['trades'],0);self.assertEqual(result[0]['total_return'],0)
 def test_latency_funding_reconciliation(self):
  ds,p=fixture();ds['funding']['ETHUSDT'][2*STEP]=[(2*STEP,.0001)];r,d,t,m,trace=replay(ds,p,'duration_book');self.assertGreater(len(t),0);self.assertEqual(min(x['entry'] for x in t),STEP);self.assertTrue(all(x['horizon']==30 for x in t));self.assertAlmostEqual(m[-1],10000+sum(x['net'] for x in t));self.assertLess(sum(x['funding'] for x in t),0);self.assertEqual(len(d),1)
 def test_future_intrabar_cannot_change_entry(self):
  ds,p=fixture();a=replay(ds,p,'duration_book')[4][0];ds['prices']['ETHUSDT'][1,1]=200;ds['prices']['ETHUSDT'][1,2]=1;b=replay(ds,p,'duration_book')[4][0];self.assertEqual(a,b)
 def test_stop_first_execution(self):
  ds,p=fixture();ds['prices']['ETHUSDT'][1,1:3]=[103,98];t=replay(ds,p,'duration_book')[2];self.assertEqual(t[0]['reason'],'STOP');self.assertLess(t[0]['net'],0)
 def test_risk_pause_drawdown(self):
  r=Risk();r.closed(-1,0);r.closed(-1,STEP);r.closed(-1,2*STEP);self.assertEqual(r.factor(10000,3*STEP),0);self.assertEqual(r.factor(9100,100*STEP),.5);self.assertEqual(r.factor(7900,100*STEP),0);self.assertTrue(r.halt)
 def test_risk_ablation_only_pauses(self):
  ds,p=fixture();a=replay(ds,p,'duration_book');b=replay(ds,p,'duration_book_no_adaptive');self.assertEqual(a[4][0],b[4][0]);self.assertGreater(b[0]['trades'],a[0]['trades'])
 def test_rule_180_minutes(self):
  ds,p=fixture();p['rule_side'][:,1]=1;t=replay(ds,p,'rule_momentum')[2];self.assertTrue(len(t)>0);self.assertTrue(all(x['horizon']==180 for x in t));self.assertEqual(t[0]['hold_minutes'],180)
 def test_qty_floor_minimum(self):
  rule=dict(tick=.1,step=.01,minqty=.01,maxqty=100,minnotional=5,minprice=.1,maxprice=1e6);fill,qty=size_order(100,1,100,rule,.0006);self.assertLessEqual(qty*fill,100);self.assertGreaterEqual(fill,100.06);self.assertIsNone(size_order(100,1,1,rule,.0006))
if __name__=='__main__':unittest.main(verbosity=2)
