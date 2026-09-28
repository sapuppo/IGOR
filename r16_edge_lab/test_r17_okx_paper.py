#!/usr/bin/env python3
"""Paper execution and adverse funding estimation over synthetic public snapshots."""
from copy import deepcopy
from decimal import Decimal
import unittest

from r17_forward_capture import BAR_MS
from r17_okx_paper import init_state, step
from test_r17_okx_breakout_signal import END, SERVER, fixture


class FakeMark:
    def get(self, path, params=None):
        assert path == '/api/v5/market/history-mark-price-candles'
        when=params['after']-60000
        return [[str(when),'101','105','99','102','1']]


def warmup():
    return {'observations':{'BTC-USDT-SWAP':{'klines':[]},
                            'ETH-USDT-SWAP':{'klines':[]}}}


class PaperTest(unittest.TestCase):
    def test_late_processing_never_enters(self):
        old,now=fixture()
        state,events=step(init_state(),warmup(),[old],now,SERVER+120001,FakeMark(),True)
        self.assertFalse(state['positions'])
        self.assertEqual(events[0]['type'],'SKIP')

    def test_entry_next_candle_exit_cooldown_and_fees(self):
        old,now=fixture()
        initial,events=step(init_state(),warmup(),[old],now,SERVER+1000,FakeMark(),True)
        self.assertEqual([x['type'] for x in events].count('ENTRY'),1)
        pos=initial['positions']['ETH-USDT-SWAP']
        self.assertEqual(pos['contracts'],'96.99')
        self.assertEqual(pos['entry_fill'],'103.103')
        self.assertLess(Decimal(initial['cash']),Decimal('10000'))
        next_capture=deepcopy(now)
        next_capture['server_time_ms']+=BAR_MS
        from r17_okx_paper import timestamp
        from r17_forward_capture import utc
        next_capture['end_exclusive_utc']=utc(timestamp(now['end_exclusive_utc'])+BAR_MS)
        next_capture['observations']['ETH-USDT-SWAP']['klines'][0][0]=str(END)
        next_capture['observations']['ETH-USDT-SWAP']['klines'][0][4]='109'
        next_capture['observations']['ETH-USDT-SWAP']['klines'][0][2]='110'
        next_capture['observations']['ETH-USDT-SWAP']['ticker']['ts']=str(SERVER+BAR_MS-1000)
        next_capture['observations']['ETH-USDT-SWAP']['ticker']['bidPx']='109'
        next_capture['observations']['ETH-USDT-SWAP']['ticker']['askPx']='109.1'
        next_capture['observations']['BTC-USDT-SWAP']['klines'][0][0]=str(END)
        next_capture['observations']['BTC-USDT-SWAP']['ticker']['ts']=str(SERVER+BAR_MS-1000)
        second,events=step(initial,warmup(),[old,now],next_capture,SERVER+BAR_MS+1000,FakeMark(),True)
        self.assertEqual([x['type'] for x in events].count('EXIT'),1)
        self.assertEqual(events[0]['reason'],'TAKE')
        self.assertEqual(second['closed_trades'],1)
        self.assertFalse(second['positions'])
        self.assertGreater(Decimal(second['cash']),Decimal('10000'))
        self.assertEqual(second['last_closed']['ETH-USDT-SWAP'],END+BAR_MS)

    def test_adverse_funding_cannot_be_zeroed(self):
        old,now=fixture()
        state,_=step(init_state(),warmup(),[old],now,SERVER+1000,FakeMark(),True)
        position=state['positions']['ETH-USDT-SWAP']
        later=deepcopy(now)
        later['server_time_ms']+=BAR_MS
        from r17_forward_capture import utc
        later['end_exclusive_utc']=utc(END+BAR_MS)
        for symbol in later['universe']:
            row=later['observations'][symbol]
            row['klines'][0][0]=str(END)
            row['ticker']['ts']=str(SERVER+BAR_MS-1000)
        later['observations']['ETH-USDT-SWAP']['funding']=[{
            'fundingTime':str(END+3600000),'realizedRate':'0.001'}]
        second,events=step(state,warmup(),[old,now],later,SERVER+BAR_MS+1000,FakeMark(),True)
        fund=second['funding'][0]
        self.assertEqual(fund['status'],'ESTIMATED_STRESS')
        self.assertEqual(Decimal(fund['amount_usdt']),
                         -Decimal(position['base_quantity'])*Decimal('0.001')*Decimal('105'))
        self.assertIn('FUNDING_STRESS_ESTIMATE',[x['type'] for x in events])


if __name__=='__main__':
    unittest.main()
