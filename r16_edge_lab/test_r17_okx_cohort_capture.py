#!/usr/bin/env python3
"""Transport checks for frozen multiactive OKX observation, using synthetic data."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from r17_forward_capture import BAR_MS, CaptureError, save_snapshot, verify_chain
from r17_okx_cohort_capture import capture, fixed_universe

START = 1790640000000
END = START + BAR_MS
SERVER = END + 60_100
SYMBOLS = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP']


class FakeOKX:
    def __init__(self):
        self.candles = {s: [[str(START), '100', '102', '99', '101', '10', '1', '10', '1']] for s in SYMBOLS}
        self.funding = {s: [] for s in SYMBOLS}
        self.quotes = [{'instId': s, 'bidPx': '100', 'askPx': '101', 'bidSz': '1',
                        'askSz': '1', 'ts': str(SERVER - 1000)} for s in SYMBOLS]

    def get(self, path, params=None):
        if path == '/api/v5/public/time': return [{'ts': str(SERVER)}]
        if path == '/api/v5/public/instruments':
            return [{'instId': s, 'state': 'live', 'ctType': 'linear'} for s in SYMBOLS]
        if path == '/api/v5/market/candles': return deepcopy(self.candles[params['instId']])
        if path == '/api/v5/public/funding-rate-history': return deepcopy(self.funding[params['instId']])
        if path == '/api/v5/market/tickers': return deepcopy(self.quotes)
        raise AssertionError(path)


class CohortTest(unittest.TestCase):
    def test_pin_and_tamper_detection(self):
        original = Path(__file__).with_name('R17_03_OKX_UNIVERSE.json')
        self.assertEqual(len(fixed_universe(original)), 35)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'edited.json'
            bad.write_bytes(original.read_bytes() + b' ')
            with self.assertRaisesRegex(CaptureError, 'alterado'):
                fixed_universe(bad)

    def test_two_symbols_complete_and_chained(self):
        item = capture(FakeOKX(), SYMBOLS, START, END, clock_ms=SERVER, source_sha='synthetic')
        self.assertEqual(item['status'], 'COMPLETE')
        self.assertEqual(item['snapshot_class'], 'TIMELY_OBSERVATION')
        with tempfile.TemporaryDirectory() as tmp:
            save_snapshot(tmp, item)
            self.assertEqual(verify_chain(tmp)['snapshots'], 1)

    def test_stale_quote_or_candle_gap_fails_per_symbol(self):
        fake = FakeOKX()
        fake.quotes[1]['ts'] = str(SERVER - 7000)
        fake.candles[SYMBOLS[0]] = []
        item = capture(fake, SYMBOLS, START, END, clock_ms=SERVER)
        self.assertEqual(item['status'], 'INCOMPLETE')
        self.assertIn(SYMBOLS[1]+':STALE_BOOK', item['problems'])
        self.assertIn(SYMBOLS[0]+':CANDLE_GAP', item['problems'])


if __name__ == '__main__':
    unittest.main()
