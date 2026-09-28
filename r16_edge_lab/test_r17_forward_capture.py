#!/usr/bin/env python3
"""Offline transport checks: incomplete bars, stale quotes and altered files."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from r17_forward_capture import BAR_MS, CaptureError, PublicUSDm, capture_batch, fixed_universe, save_snapshot, verify_chain

START = 1790640000000  # 2026-09-29 00:00 UTC
END = START + 2 * BAR_MS
SERVER = END + 60_001


class FakePublic:
    def __init__(self):
        self.calls = []
        self.bars = {}
        self.funding = {}
        self.quotes = []
        for symbol in ('BTCUSDT', 'ETHUSDT'):
            self.bars[symbol] = [
                [START + i * BAR_MS, '100', '101', '99', '100', '10',
                 START + (i + 1) * BAR_MS - 1, '10000000', 200, '5', '5000000', '0']
                for i in range(2)]
            self.funding[symbol] = [
                {'symbol': symbol, 'fundingTime': START + 1000,
                 'fundingRate': '0.0001', 'markPrice': '100'}]
            self.quotes.append({'symbol': symbol, 'bidPrice': '99', 'askPrice': '101',
                                'bidQty': '100', 'askQty': '100', 'time': SERVER - 1000})

    def get(self, path, params=None):
        self.calls.append(path)
        if path == '/fapi/v1/time':
            return {'serverTime': SERVER}
        if path == '/fapi/v1/exchangeInfo':
            return {'symbols': [{'symbol': s, 'status': 'TRADING'} for s in self.bars]}
        if path == '/fapi/v1/ticker/bookTicker':
            return deepcopy(self.quotes)
        if path == '/fapi/v1/klines':
            return deepcopy(self.bars[params['symbol']])
        if path == '/fapi/v1/fundingRate':
            return deepcopy(self.funding[params['symbol']])
        raise AssertionError('endpoint inesperado')


def capture(fake):
    return capture_batch(fake, ['BTCUSDT', 'ETHUSDT'], START, END,
                         clock_ms=SERVER, source_sha='fake-code-hash')


class CaptureTest(unittest.TestCase):
    def test_order_endpoint_cannot_be_called(self):
        with self.assertRaisesRegex(CaptureError, 'não permitido'):
            PublicUSDm().get('/fapi/v1/order', {'symbol': 'BTCUSDT'})

    def test_frozen_universe_file_is_pinned(self):
        source = Path(__file__).with_name('R17_01_UNIVERSE.json')
        self.assertEqual(len(fixed_universe(source)), 38)
        with tempfile.TemporaryDirectory() as tmp:
            modified = Path(tmp) / 'universe.json'
            modified.write_bytes(source.read_bytes() + b' ')
            with self.assertRaisesRegex(CaptureError, 'modificada'):
                fixed_universe(modified)

    def test_readonly_complete_and_timely(self):
        fake = FakePublic()
        value = capture(fake)
        self.assertEqual(value['status'], 'COMPLETE')
        self.assertEqual(value['snapshot_class'], 'TIMELY_OBSERVATION')
        self.assertEqual(fake.calls[-2:], ['/fapi/v1/ticker/bookTicker', '/fapi/v1/time'])
        self.assertEqual(len(value['observations']['BTCUSDT']['klines']), 2)

    def test_gap_and_missing_mark_are_visible(self):
        fake = FakePublic()
        fake.bars['ETHUSDT'].pop()
        fake.funding['BTCUSDT'][0]['markPrice'] = ''
        value = capture(fake)
        self.assertEqual(value['status'], 'INCOMPLETE')
        self.assertIn('ETHUSDT:CANDLE_GAP_OR_PAGE_MISMATCH', value['problems'])
        self.assertIn('BTCUSDT:FUNDING_MARK_MISSING', value['problems'])

    def test_stale_quote_and_forming_candle(self):
        fake = FakePublic()
        fake.quotes[0]['time'] = SERVER - 6000
        self.assertIn('BTCUSDT:QUOTE_STALE_OR_FUTURE', capture(fake)['problems'])
        fake.bars['BTCUSDT'][1][6] = END + BAR_MS - 1
        with self.assertRaisesRegex(CaptureError, 'candle não consolidado'):
            capture(fake)

    def test_chain_detects_tampering_and_rejects_backwards_time(self):
        value = capture(FakePublic())
        with tempfile.TemporaryDirectory() as tmp:
            first = save_snapshot(tmp, value)
            self.assertEqual(verify_chain(tmp)['snapshots'], 1)
            with self.assertRaisesRegex(CaptureError, 'sem sobrescrita'):
                save_snapshot(tmp, value)
            value['server_time_ms'] += 1000
            value['source_sha256'] = 'changed-after-first-capture'
            with self.assertRaisesRegex(CaptureError, 'código alterado'):
                save_snapshot(tmp, value)
            value['source_sha256'] = 'fake-code-hash'
            save_snapshot(tmp, value)
            self.assertEqual(verify_chain(tmp)['snapshots'], 2)
            first.write_bytes(first.read_bytes() + b' ')  # raw bytes differ from file name and chain
            with self.assertRaisesRegex(CaptureError, 'hash do arquivo'):
                verify_chain(tmp)


if __name__ == '__main__':
    unittest.main()
