import unittest
import numpy as np,pandas as pd
from r17_22_flow import asof_values,signals,BAR
class Causality(unittest.TestCase):
 def test_no_same_timestamp_or_future(self):
  a=asof_values([100,101,199],[{'timestamp':100,'x':3},{'timestamp':200,'x':99}],'x',100)
  self.assertTrue(np.isnan(a[0]));self.assertEqual(list(a[1:]),[3,3])
 def test_stale_and_missing_fail_closed(self):
  self.assertTrue(np.isnan(asof_values([201],[{'timestamp':100,'x':3}],'x',100)[0]))
  self.assertTrue(np.isnan(asof_values([101],[],'x',100)[0]))
 def test_oi_required_not_synthesized_from_volume(self):
  ts=np.arange(60)*BAR;c=np.ones(60)*100;c[50:]=104
  f=pd.DataFrame({'close':c,'quote_volume':1e7,'taker_buy_quote_volume':6e6},index=ts)
  rates={'X':[{'timestamp':49*BAR,'rate':.0001}]}
  a=signals({'X':f},rates,{},'flow',0,60*BAR);b=signals({'X':f},rates,{},'flow_oi_funding',0,60*BAR)
  self.assertGreater(sum(len(v) for m in a.values() for v in m.values()),0)
  self.assertEqual(sum(len(v) for m in b.values() for v in m.values()),0)
if __name__=='__main__':unittest.main()
