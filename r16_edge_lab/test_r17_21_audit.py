import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np
import r17_21_audited_engine as e

class Audit(unittest.TestCase):
 def run_case(self,side=1,hold=6,funding=None,bar=None,extra=None):
  start=e.START;end=start+6*e.BAR_MS;times=np.arange(start,end,e.BAR_MS)
  f=pd.DataFrame(dict(open=100.,high=100.,low=100.,close=100.,atr=1.),index=times)
  f.loc[start-e.BAR_MS]=[100.,100.,100.,100.,1.]
  if bar is not None:f.loc[times[1],['open','high','low','close']]=bar
  spec=dict(id='test',direction='long' if side==1 else 'short',lookback_bars=55,btc_gate=False,hold_bars=hold,**(extra or {}))
  with patch.object(e,'END',end),patch.object(e,'FEE',.001),patch.object(e,'SLIP',0),patch.object(e,'STOP',.05),patch.object(e,'TARGET',.10):
   return e.replay(spec,{'X':f},{'X':funding or {}},{(55,side):{start:[('X',side,1)]}},pd.Series(dtype=float))
 def test_terminal_cost_in_drawdown_and_cash(self):
  r=self.run_case();self.assertAlmostEqual(r['return'],-.0005);self.assertAlmostEqual(r['max_4h_mtm_drawdown'],.0005);self.assertEqual(r['daily_details'][-1]['gross'],0)
 def test_existing_position_pays_funding_before_time_exit(self):
  t=e.START+e.BAR_MS
  for side in [1,-1]:
   r=self.run_case(side=side,hold=1,funding={t:[(t,.01)]});self.assertAlmostEqual(r['trade_details'][0]['funding'],-side*25.)
 def test_new_entry_after_boundary_does_not_receive_old_funding(self):
  r=self.run_case(funding={e.START:[(e.START,.01)]});self.assertEqual(r['trade_details'][0]['funding'],0)
 def test_ambiguous_bar_stop_first(self):
  r=self.run_case(bar=[100,115,90,100]);self.assertEqual(r['trade_details'][0]['reason'],'STOP');self.assertLess(r['trade_details'][0]['net'],0)
 def test_risk_budget_position_size(self):
  r=self.run_case(extra=dict(risk_fraction=.0025,atr_stop=2,max_weight=.15,max_exposure=.6))
  tr=r['trade_details'][0];notional=tr['qty']*tr['entry_fill'];self.assertAlmostEqual(notional,10000*.0025/(.02+.002))
 def test_independent_trade_accounting(self):
  for side in [1,-1]:
   r=self.run_case(side=side,bar=[100,102,98,101]);tr=r['trade_details'][0]
   expected=side*tr['qty']*(tr['exit_fill']-tr['entry_fill'])-tr['entry_fee']-tr['exit_fee']+tr['funding']
   self.assertAlmostEqual(tr['net'],expected)

 def test_cooldown_prevents_reentry_after_stop(self):
  start=e.START;times=np.arange(start,start+6*e.BAR_MS,e.BAR_MS)
  f=pd.DataFrame(dict(open=100.,high=101.,low=99.,close=100.,atr=1.),index=times)
  f.loc[times[0],'low']=90.
  spec=dict(id='cooldown',direction='long',lookback_bars=55,btc_gate=False,hold_bars=6,cooldown_bars=6)
  sig={(55,1):{start:[('X',1,1.)],start+e.BAR_MS:[('X',1,1.)]}}
  with patch.object(e,'END',start+6*e.BAR_MS):
   r=e.replay(spec,{'X':f},{'X':{}},sig,pd.Series(dtype=float))
  self.assertEqual(len(r['trade_details']),1)
  self.assertEqual(r['costs']['cooldown_skips'],1)

if __name__=='__main__':unittest.main()
