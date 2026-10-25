import unittest
import numpy as np
import pandas as pd
from r17_24_online_strategies import seeded_ema,indicators,conditions,signals,MODES,BAR_MS
class OnlineStrategies(unittest.TestCase):
 def frame(self):
  n=500;c=100+8*np.sin(np.arange(n)/11)+np.arange(n)*.03
  return pd.DataFrame(dict(open=c-.2,high=c+1,low=c-1,close=c,quote_volume=1e7),index=np.arange(n)*BAR_MS)
 def test_seeded_ema_known_recurrence(self):
  r=seeded_ema(pd.Series([1.,2.,3.,6.]),3)
  self.assertTrue(r.iloc[:2].isna().all());self.assertEqual(r.iloc[2],2.);self.assertEqual(r.iloc[3],4.)
 def test_heikin_ashi_uses_prior_bar(self):
  f=self.frame();x=indicators(f)
  self.assertEqual(x.ha_open.iloc[0],(f.open.iloc[0]+f.close.iloc[0])/2)
  self.assertAlmostEqual(x.ha_open.iloc[1],(x.ha_open.iloc[0]+x.ha_close.iloc[0])/2)
 def test_bollinger_macd_predicates(self):
  x=pd.DataFrame(dict(bbp=[-.1,1.1,-.1,1.1,0,1],hist=[1,-1,-1,1,1,-1],macd=[-1,1,-1,1,-1,1]))
  a,b=conditions(x,'hb_macd_bb');self.assertEqual(list(a),[True,False,False,False,False,False]);self.assertEqual(list(b),[False,True,False,False,False,False])
  a,b=conditions(x,'hb_bollinger');self.assertEqual(int(a.sum()),2);self.assertEqual(int(b.sum()),2)
 def test_ft_cross_not_persistent_no_short(self):
  x=pd.DataFrame(dict(ema20=[1,3,4],ema50=[2,2,2],ha_close=[4,4,5],ha_open=[3,3,4]))
  a,b=conditions(x,'ft_ema_ha');self.assertEqual(list(a),[False,True,False]);self.assertFalse(b.any())
 def test_flat_price_no_signal(self):
  f=self.frame();f[['open','high','low','close']]=100
  for mode in MODES:self.assertFalse(any(signals({'X':f},mode,0,10**15).values()))
 def test_next_open_and_prefix_invariance(self):
  f=self.frame();cut=f.index[350]
  for mode in MODES:
   full=signals({'X':f},mode,0,10**15);pre=signals({'X':f.loc[f.index<cut]},mode,0,10**15)
   for k in full:self.assertEqual({t:v for t,v in full[k].items() if t<=cut},dict(pre[k]))
   for side,mask in zip((1,-1),conditions(indicators(f),mode)):
    for t in full[1,side]:self.assertTrue(mask.at[t-BAR_MS])
 def test_liquidity_and_duplicate_guard(self):
  f=self.frame();f.quote_volume=0
  self.assertFalse(any(signals({'X':f},'hb_bollinger',0,10**15).values()))
  with self.assertRaises(ValueError):signals({'X':pd.concat([f,f.iloc[-1:]])},'hb_bollinger',0,10**15)
if __name__=='__main__':unittest.main()
