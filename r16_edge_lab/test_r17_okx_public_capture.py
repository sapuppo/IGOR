#!/usr/bin/env python3
"""Synthetic checks for independent public OKX source pilot."""
from copy import deepcopy
import unittest

from r17_forward_capture import BAR_MS, CaptureError
from r17_okx_public_capture import PublicOKX, capture, SYMBOL

START = 1790640000000
END = START + BAR_MS
SERVER = END + 60_100


class FakeOKX:
    def __init__(self):
        self.bars = [[str(START), '100', '102', '99', '101', '10', '1', '10', '1']]
        self.funding = []
        self.ticker = [{'instId': SYMBOL, 'bidPx': '100', 'askPx': '101', 'bidSz': '1',
                        'askSz': '2', 'ts': str(SERVER - 1000)}]

    def get(self, path, params=None):
        if path == '/api/v5/public/time':
            return [{'ts': str(SERVER)}]
        if path == '/api/v5/public/instruments':
            return [{'instId': SYMBOL, 'state': 'live', 'ctType': 'linear'}]
        if path == '/api/v5/market/candles':
            return deepcopy(self.bars)
        if path == '/api/v5/public/funding-rate-history':
            return deepcopy(self.funding)
        if path == '/api/v5/market/ticker':
            return deepcopy(self.ticker)
        raise AssertionError(path)


class OKXPilotTest(unittest.TestCase):
    def test_public_allowlist(self):
        with self.assertRaisesRegex(CaptureError, 'lista pública'):
            PublicOKX().get('/api/v5/trade/order')

    def test_timely_single_bar_without_funding(self):
        snapshot = capture(FakeOKX(), START, END, clock_ms=SERVER, source_sha='synthetic')
        self.assertEqual(snapshot['status'], 'COMPLETE')
        self.assertEqual(snapshot['snapshot_class'], 'TIMELY_OBSERVATION')
        self.assertEqual(snapshot['observations'][SYMBOL]['funding'], [])

    def test_rejects_open_bar_and_stale_quote(self):
        fake = FakeOKX()
        fake.bars[0][-1] = '0'
        self.assertIn('UNCONFIRMED_CANDLE', capture(fake, START, END, clock_ms=SERVER)['problems'])
        fake.bars[0][-1] = '1'
        fake.ticker[0]['ts'] = str(SERVER - 6000)
        self.assertIn('STALE_BOOK', capture(fake, START, END, clock_ms=SERVER)['problems'])


if __name__ == '__main__':
    unittest.main()
