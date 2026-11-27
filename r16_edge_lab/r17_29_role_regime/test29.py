import unittest
import numpy as np,pandas as pd
from data29 import HOUR,DAY,SYMS,features
from engine29 import Risk,entry_order,replay
from roles29 import classify

def fixture(n=72):
 base=[70000.,2000.,100.,600.,1.,.1];prices={s:np.tile([x,x*1.00001,x*.99999,x,1e8],(n,1)) for s,x in zip(SYMS,base)};ds=dict(start=0,end=n*HOUR,prices=prices,funding={s:{} for s in SYMS});shape=(n,6);side=np.zeros(shape,np.int8);side[:,0]=1;pol=dict(side=side,gate=np.full(shape,9),score=np.ones(shape),stop=np.full(shape,.02),trail=np.full(shape,.04),name='test',base_name='test',risk_fraction=.0025);return ds,pol
class Tests(unittest.TestCase):
 def test_cover_not_new_long(self):
  r=classify(-10,'B',3);self.assertEqual(r['opening_side'],0);self.assertEqual(r['closing_side'],-1);self.assertFalse(r['observed_buy_is_new_long']);self.assertEqual(r['after'],'-7')
 def test_buy_reversal_split(self):
  r=classify(-3,'B',5);self.assertEqual(r['opening_quantity'],'2');self.assertEqual(r['closing_quantity'],'3');self.assertTrue(r['reversal'])
 def test_increase_short(self):
  r=classify(-2,'A',1);self.assertEqual(r['opening_side'],-1);self.assertEqual(r['closing_side'],0)
 def test_unknown_position_rejected(self):
  with self.assertRaises(ValueError):classify(None,'B',1)
 def test_long_reduction(self):
  r=classify(2,'A',1);self.assertEqual(r['closing_side'],1);self.assertEqual(r['opening_side'],0)
 def test_exact_decimal(self):self.assertEqual(classify('0.1','B','0.2')['after'],'0.3')
 def test_causal_feature_prefix(self):
  rng=np.random.default_rng(29);n=24*50;v=100*np.exp(np.cumsum(rng.normal(0,.001,n)));idx=pd.date_range('2024-01-01',periods=n,freq='h',tz='UTC');f=pd.DataFrame(dict(open=v,high=v*1.002,low=v*.998,close=v,quote_volume=1e8),index=idx);a=features(f);b=features(f.iloc[:1001]);cols=[x for x in a if x not in ['open','high','low','close','quote_volume']];pd.testing.assert_frame_equal(a.iloc[:1001][cols],b[cols])
 def test_current_hour_close_not_available(self):
  rng=np.random.default_rng(1);n=1000;v=100*np.exp(np.cumsum(rng.normal(0,.001,n)));idx=pd.date_range('2024-01-01',periods=n,freq='h',tz='UTC');f=pd.DataFrame(dict(open=v,high=v*1.002,low=v*.998,close=v,quote_volume=1e8),index=idx);a=features(f);f.loc[idx[800],'close']*=2;b=features(f);self.assertEqual(a.loc[idx[800],'rel_72'],b.loc[idx[800],'rel_72'])
 def test_qty_rounding(self):
  r=dict(tick=.1,step=.01,minqty=.01,maxqty=100,minnotional=5,minprice=.1,maxprice=1e6);o=entry_order(100,1,100,r,.0006);self.assertLessEqual(o[0]*o[1],100);self.assertIsNone(entry_order(100,1,1,r,.0006))
 def test_cash_reconciles(self):
  ds,p=fixture();p['side'][:]=0;r,d,t,m,trace=replay(ds,{'cash':p},[(0,'cash')]);self.assertEqual(r['total_return'],0);self.assertEqual(len(t),0)
 def test_one_hour_latency_and_end_fees(self):
  ds,p=fixture();r,d,t,m,trace=replay(ds,{'test':p},[(0,'test')]);self.assertGreater(len(t),0);self.assertEqual(trace[0]['time'],HOUR);self.assertEqual(trace[0]['decision_time'],0);self.assertAlmostEqual(m[-1],10000+sum(x['net'] for x in t));self.assertLess(r['total_return'],0)
 def test_intrabar_cannot_change_open_allocation(self):
  ds,p=fixture();p['side'][:,:3]=1;a=replay(ds,{'test':p},[(0,'test')])[4][:3];ds['prices']['BTCUSDT'][1,1:3]=[140000,1];b=replay(ds,{'test':p},[(0,'test')])[4][:3];self.assertEqual(a,b)
 def test_stop_first(self):
  ds,p=fixture();p['base_name']='reference';ds['prices']['BTCUSDT'][1,1:3]=[85000,60000];r,d,t,m,trace=replay(ds,{'reference':p},[(0,'reference')]);self.assertEqual(t[0]['reason'],'STOP');self.assertLess(t[0]['net'],0);self.assertGreater(r['stats']['stop_target_ambiguous'],0)
 def test_funding_debit_and_reconciliation(self):
  ds,p=fixture();ds['funding']['BTCUSDT'][8*HOUR]=[(8*HOUR,.0001)];r,d,t,m,tr=replay(ds,{'test':p},[(0,'test')]);self.assertLess(r['funding'],0);self.assertAlmostEqual(m[-1],10000+sum(x['net'] for x in t))
 def test_ambiguous_positive_funding_skipped(self):
  ds,p=fixture();ds['funding']['BTCUSDT'][8*HOUR]=[(8*HOUR+100,-.001)];ds['prices']['BTCUSDT'][8,2]=65000;r,d,t,m,tr=replay(ds,{'test':p},[(0,'test')]);self.assertEqual(r['funding'],0)
 def test_risk_sticky(self):
  r=Risk();self.assertEqual(r.factor(7900,0),0);self.assertEqual(r.factor(10000,100*HOUR),0);self.assertTrue(r.halt)
 def test_policy_switch_does_not_reset_halt(self):
  ds,p=fixture();p['side'][:,:3]=1;p['stop'][:]=.9;p['trail'][:]=.99;p['risk_fraction']=.5
  for s in SYMS:ds['prices'][s][36:,:4]*=.5
  policies={'testA':p,'testB':dict(p)};r,d,t,m,trace=replay(ds,policies,[(0,'testA'),(37*HOUR,'testB')]);self.assertTrue(r['halted']);self.assertTrue(all(x['time']<37*HOUR for x in trace));self.assertGreater(r['max_drawdown'],.2)
if __name__=='__main__':unittest.main(verbosity=2)
