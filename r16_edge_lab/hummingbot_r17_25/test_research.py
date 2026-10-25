import unittest
import numpy as np,pandas as pd
from strategies import features,intent
from engine import Risk,round_order,maker_side,replay
from data import STEP,BAR,DAY,ms,SYMS

def fixture():
 start=ms('2026-01-01');base=start-BAR;times=np.arange(base,start+2*DAY,STEP);prices={s:np.tile([100,100,100,100,1e8],(len(times),1)).astype(float) for s in SYMS}
 row=dict(close=100,atr=1,natr=.01,st=1,mom=.1,eff=.5,reference=100,liq=True,long20=True,short20=False,long55=True,short55=False,long0=True,short0=False,control_long=True,control_short=False,btc_side=1)
 ft={s:pd.DataFrame([row]*13,index=np.arange(start,start+2*DAY+BAR,BAR)) for s in SYMS}
 for s in SYMS[1:]:ft[s]['liq']=False
 return dict(start=base,end=start+2*DAY,prices=prices,features=ft,funding={s:{} for s in SYMS}),start

class ResearchTests(unittest.TestCase):
 def test_no_future_feature_leakage(self):
  n=500;x=np.arange(n);c=100+np.sin(x/9)*3+x*.02
  f=pd.DataFrame(dict(open=c-.1,high=c+1,low=c-1,close=c,quote_volume=1e7),index=x*BAR)
  full=features(f);pre=features(f.iloc[:350]);pd.testing.assert_frame_equal(full.iloc[:350],pre)
  f.iloc[350:,f.columns.get_loc('close')]*=2
  pd.testing.assert_frame_equal(full.iloc[:350],features(f).iloc[:350])
 def test_prior_breakout_excludes_signal_bar(self):
  n=300;c=np.arange(n)+100.;f=pd.DataFrame(dict(open=c-.1,high=c+.5,low=c-.5,close=c,quote_volume=1e7))
  self.assertTrue(features(f).long20.iloc[-1])
 def test_regime_routing(self):
  row=dict(liq=True,atr=1,eff=.1,long20=True,short20=False)
  self.assertEqual(intent(row,dict(family='hybrid',spread_atr=1,breakout=20),1),('pmm',0))
  row['eff']=.25;self.assertEqual(intent(row,dict(family='hybrid',spread_atr=1,breakout=20),1),('cash',0))
  row['eff']=.5;self.assertEqual(intent(row,dict(family='hybrid',spread_atr=1,breakout=20),1),('trend',1))
 def test_risk_drawdown_and_streak(self):
  r=Risk();self.assertEqual(r.factor(9100,0),.5)
  for _ in range(3):r.closed(-1,0)
  self.assertEqual(r.factor(10000,1),0);self.assertEqual(r.factor(10000,DAY),1)
  self.assertEqual(r.factor(7900,DAY),0);self.assertEqual(r.factor(11000,DAY*2),0)
 def test_tick_lot_and_min_notional(self):
  rule=dict(tick=.1,step=.01,minqty=.01,maxqty=100,minnotional=5)
  self.assertEqual(round_order(10.09,1.019,1,rule),(10.,1.01));self.assertIsNone(round_order(1,.01,1,rule))
 def test_maker_dual_fill_and_touch_rejected(self):
  self.assertEqual(maker_side(100,103,97,99,101,.0002),0)
  self.assertEqual(maker_side(100,100,99,99,101,.0002),0)
  self.assertEqual(maker_side(98,100,97,99,101,.0002),1)
 def test_entry_latency_and_trade_accounting(self):
  ds,start=fixture();spec=dict(id='t',family='trend',breakout=20,spread_atr=1)
  r,d,tr=replay(ds,spec,start,start+DAY)
  self.assertEqual(tr[0]['entry'],start+STEP)
  for t in tr:self.assertAlmostEqual(t['net'],t['side']*t['qty']*(t['exit_fill']-t['entry_fill'])-t['entry_fee']-t['exit_fee']+t['funding'])
  self.assertAlmostEqual(d[-1]['equity'],10000+sum(x['net'] for x in tr))
 def test_ambiguous_bar_stop_first(self):
  ds,start=fixture();i=(start+2*STEP-ds['start'])//STEP
  ds['prices']['BTCUSDT'][i]=[100,120,80,100,1e8]
  r,d,tr=replay(ds,dict(id='t',family='control',breakout=20,spread_atr=1),start,start+DAY,adaptive=False)
  self.assertEqual(tr[0]['reason'],'STOP');self.assertLess(tr[0]['net'],0)
 def test_funding_existing_only_at_boundary(self):
  ds,start=fixture();t=start+8*STEP;ds['funding']['BTCUSDT']={t:[(t,.01)]}
  r,d,tr=replay(ds,dict(id='t',family='control',breakout=20,spread_atr=1),start,start+DAY,adaptive=False)
  self.assertAlmostEqual(sum(x['funding'] for x in tr),-tr[0]['qty']*100*.01)
 def test_maker_no_entry_bar_target_profit(self):
  ds,start=fixture();i=(start+STEP-ds['start'])//STEP
  ds['prices']['BTCUSDT'][i]=[100,100.5,98.5,100,1e8]
  # Bid99 fills, target100 reached but uncertain sequence: cannot exit profit same bar.
  r,d,tr=replay(ds,dict(id='p',family='pmm',breakout=20,spread_atr=1),start,start+DAY)
  self.assertGreaterEqual(tr[0]['exit'],start+2*STEP);self.assertEqual(tr[0]['reason'],'GAP_TARGET')
 def test_same_bar_loss_cannot_change_other_entry_size(self):
  spec=dict(id='t',family='trend',breakout=20,spread_atr=1)
  sizes=[]
  for crash in [False,True]:
   ds,start=fixture();ds['features']['ETHUSDT']['liq']=True
   if crash:
    i=(start+STEP-ds['start'])//STEP;ds['prices']['BTCUSDT'][i]=[100,100,80,100,1e8]
   _,_,tr=replay(ds,spec,start,start+DAY)
   sizes.append(next(x['qty'] for x in tr if x['symbol']=='ETHUSDT'))
  self.assertEqual(sizes[0],sizes[1])
 def test_resting_quote_gap_gets_adverse_stop_price(self):
  ds,start=fixture();i=(start+2*STEP-ds['start'])//STEP
  ds['prices']['BTCUSDT'][i]=[90,91,89,90,1e8]
  _,_,tr=replay(ds,dict(id='p',family='pmm',breakout=20,spread_atr=1),start,start+DAY)
  self.assertEqual(tr[0]['entry_fill'],99);self.assertLessEqual(tr[0]['exit_fill'],90)
 def test_risk_sizing_includes_execution_costs(self):
  ds,start=fixture();_,_,tr=replay(ds,dict(id='t',family='trend',breakout=20,spread_atr=1),start,start+DAY)
  x=tr[0];notional=x['qty']*x['entry_fill']
  self.assertLessEqual(notional,10000*.0025/(.02+.0006+.0006+2*.0006)+.2)
if __name__=='__main__':unittest.main()
