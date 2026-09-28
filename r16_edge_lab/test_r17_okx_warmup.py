#!/usr/bin/env python3
"""Warmup must exclude later prices and preserve missing historical bars."""
import unittest

from r17_forward_capture import BAR_MS
from r17_okx_warmup import build, CUTOFF_MS, LENGTH

SYMBOL='BTC-USDT-SWAP'


class Fake:
    def __init__(self):
        self.rows=[]
        for opened in range(CUTOFF_MS-LENGTH*BAR_MS,CUTOFF_MS+BAR_MS,BAR_MS):
            self.rows.append([str(opened),'100','101','99','100','1','1','2000000','1'])

    def get(self,path,params=None):
        assert path=='/api/v5/market/candles'
        return list(reversed(self.rows))


def first():
    return {'schema':'IGOR_R17_03_OKX_COHORT_CAPTURE_V1','start_utc':'2026-09-28T12:00:00Z',
            'universe':[SYMBOL]}


class WarmupTest(unittest.TestCase):
    def test_causal_49_bars(self):
        out=build(Fake(),[SYMBOL],first())
        self.assertEqual(out['status'],'COMPLETE')
        bars=out['observations'][SYMBOL]['klines']
        self.assertEqual(len(bars),49)
        self.assertEqual(int(bars[-1][0]),CUTOFF_MS-BAR_MS)
        self.assertTrue(all(int(x[0])<CUTOFF_MS for x in bars))
        self.assertIsNone(out['pnl'])

    def test_gap_blocks_instead_of_filling(self):
        fake=Fake()
        fake.rows.pop(3)
        out=build(fake,[SYMBOL],first())
        self.assertEqual(out['status'],'INCOMPLETE')
        self.assertIn(SYMBOL+':WARMUP_BAR_GAP',out['problems'])


if __name__=='__main__':
    unittest.main()
