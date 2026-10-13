"""Regression: a trailing stop learned at close cannot exit earlier in that bar."""
import unittest
import pandas as pd
import numpy as np
import r17_19_trailing_engine as e

class TrailingKnowledgeTests(unittest.TestCase):
    def check_side(self,side):
        times=np.arange(e.START,e.END,e.BAR_MS)
        f=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'atr':1.},index=times)
        if side==1:
            f.loc[times[0],['open','high','low','close']]=[100,112,99,110]
            f.loc[times[1],['open','high','low','close']]=[111,112,105,110]
        else:
            f.loc[times[0],['open','high','low','close']]=[100,101,88,90]
            f.loc[times[1],['open','high','low','close']]=[89,95,88,90]
        signals={(55,side):{e.START:[('X',side,1.)]}}
        spec={'id':'fixture','direction':'long' if side==1 else 'short','lookback_bars':55,'btc_gate':False,'hold_bars':180,'trail_atr':4}
        result=e.replay(spec,{'X':f},{'X':{}},signals,pd.Series(dtype=float))
        trade=result['trade_details'][0]
        self.assertEqual(len(result['trade_details']),1)
        self.assertEqual(trade['reason'],'STOP')
        self.assertEqual(trade['exit'],e.START+2*e.BAR_MS)
        self.assertGreater(trade['net'],0)
    def test_long_stop_only_next_bar(self):self.check_side(1)
    def test_short_stop_only_next_bar(self):self.check_side(-1)

if __name__=='__main__':unittest.main()
