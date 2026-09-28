#!/usr/bin/env python3
"""Causality and warmup checks for frozen OKX 4h paper candidates."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

from r17_forward_capture import BAR_MS, CaptureError
from r17_okx_breakout_signal import signal

START = 1790640000000
END = START + 49 * BAR_MS
SERVER = END + 80_000
SYMBOLS = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP']


def fixture():
    older, newest = {}, {}
    for symbol in SYMBOLS:
        candles = []
        for i in range(49):
            close = (100+i if symbol == 'BTC-USDT-SWAP' else 103 if i == 48 else 100)
            high = close+1
            row = [str(START+i*BAR_MS), str(close), str(high), '99', str(close),
                   '1', '1', '2000000', '1']
            candles.append(row)
        older[symbol] = {'status': 'COMPLETE', 'klines': candles[:-1], 'ticker': None}
        newest[symbol] = {'status': 'COMPLETE', 'klines': candles[-1:], 'funding':[],
                          'instrument': {'ctVal':'0.1','ctMult':'1','ctType':'linear',
                                         'ctValCcy':symbol.split('-')[0],
                                         'lotSz':'0.01','minSz':'0.01'},
                          'ticker': {'bidPx': '102.9', 'askPx': '103', 'askSz': '300',
                                     'bidSz': '300', 'ts': str(SERVER-1000)}}
    a={'schema':'IGOR_R17_03_OKX_COHORT_CAPTURE_V1','universe':SYMBOLS,
       'observations':older,'server_time_ms':END-1000,
       'snapshot_class':'RETROSPECTIVE_BACKFILL'}
    b={'schema':'IGOR_R17_03_OKX_COHORT_CAPTURE_V1','universe':SYMBOLS,
       'observations':newest,'server_time_ms':SERVER,
       'status':'COMPLETE',
       'snapshot_class':'TIMELY_OBSERVATION',
       'end_exclusive_utc':datetime.fromtimestamp(END/1000,timezone.utc).isoformat().replace('+00:00','Z')}
    return a,b


class SignalTest(unittest.TestCase):
    def test_breakout_after_completed_48_bar_warmup(self):
        old,now=fixture()
        result=signal([old,now],now)
        self.assertEqual(result['status'],'PAPER_CANDIDATES_ONLY')
        self.assertEqual([(x['symbol'],x['side']) for x in result['candidates']],
                         [('ETH-USDT-SWAP','BUY')])
        self.assertEqual(result['candidates'][0]['signal_time_ms'],END)
        self.assertEqual(result['candidates'][0]['contracts'],'96.99')
        self.assertEqual(result['candidates'][0]['contract_notional_usdt'],'10.3')

    def test_late_quote_and_missing_warmup_do_not_trade(self):
        old,now=fixture()
        now['snapshot_class']='RETROSPECTIVE_BACKFILL'
        self.assertEqual(signal([old,now],now)['status'],'SKIP_NOT_TIMELY')
        now['snapshot_class']='TIMELY_OBSERVATION'
        old['observations']['BTC-USDT-SWAP']['klines'].pop()
        self.assertEqual(signal([old,now],now)['status'],'WARMUP_BTC')
        old,now=fixture()
        now['observations']['ETH-USDT-SWAP']['status']='INVALID'
        self.assertEqual(signal([old,now],now)['candidates'],[])

    def test_book_depth_is_in_contracts_not_coins(self):
        old,now=fixture()
        now['observations']['ETH-USDT-SWAP']['ticker']['askSz']='0.6'
        self.assertEqual(signal([old,now],now)['candidates'],[])

    def test_future_capture_rejected(self):
        old,now=fixture()
        future=deepcopy(old)
        future['server_time_ms']=SERVER+1
        with self.assertRaisesRegex(CaptureError,'futura'):
            signal([old,future,now],now)


if __name__ == '__main__':
    unittest.main()
