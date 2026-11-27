import unittest
import numpy as np,pandas as pd
from copy_run29 import flow_arrays
from copy_engine29 import replay,STEP,SYMS

class CopyTests(unittest.TestCase):
 def test_role_and_bucket_availability(self):
  ix=pd.date_range('2026-10-01',periods=65,freq='min',tz='UTC');f=pd.DataFrame([dict(time='2026-10-01T00:59:30Z',coin='BTC',dir='Close Short',ntl=100.)]);o=flow_arrays(f,ix)
  self.assertEqual(o['naive'][0][59,0],0);self.assertEqual(o['naive'][0][60,0],1);self.assertEqual(o['opening'][0][60,0],0)
 def test_future_export_cannot_change_past(self):
  ix=pd.date_range('2026-10-01',periods=130,freq='min',tz='UTC');f=pd.DataFrame([dict(time='2026-10-01T00:01:30Z',coin='BTC',dir='Open Short',ntl=100.),dict(time='2026-10-01T01:45:30Z',coin='BTC',dir='Open Long',ntl=1e12)]);full=flow_arrays(f,ix);pre=flow_arrays(f.iloc[:1],ix)
  for k in full:
   for a,b in zip(full[k],pre[k]):np.testing.assert_array_equal(a[:105],b[:105])
 def test_reversal_excluded_without_inventory(self):
  ix=pd.date_range('2026-10-01',periods=65,freq='min',tz='UTC');f=pd.DataFrame([dict(time='2026-10-01T00:59:30Z',coin='BTC',dir='Short > Long',ntl=100.)]);o=flow_arrays(f,ix);self.assertEqual(o['naive'][0][60,0],1);self.assertEqual(o['opening'][0][60,0],0)
 def test_new_copy_engine_latency_horizon_and_reconcile(self):
  n=1440;prices={s:np.tile([70000.,70001.,69999.,70000.,1e8],(n,1)) for s in SYMS};side=np.zeros((n,3),np.int8);side[0,0]=1;stop=np.full((n,3,3),.01);ds=dict(start=0,end=n*STEP,prices=prices,funding={s:{} for s in SYMS});r,d,tr,m,trace=replay(ds,dict(rule_side=side,stop=stop,strength=np.ones((n,3))),'rule_momentum')
  self.assertEqual(tr[0]['entry'],STEP);self.assertEqual(tr[0]['horizon'],60);self.assertEqual(tr[0]['hold_minutes'],60);self.assertAlmostEqual(d[-1],10000+sum(x['net'] for x in tr),places=7);self.assertLess(r['total_return'],0)

if __name__=='__main__':unittest.main()
