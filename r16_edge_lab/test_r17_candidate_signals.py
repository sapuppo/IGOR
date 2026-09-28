#!/usr/bin/env python3
"""Causal boundary tests for the preregistered weekly signal."""
import unittest
from datetime import datetime, timezone

import pandas as pd

from r17_candidate_signals import BAR_MS, MIN_4H_BARS, parse_ms, rank_week


class SignalTest(unittest.TestCase):
    def setUp(self):
        self.monday = parse_ms('2026-03-02T00:00:00Z')
        first = self.monday - MIN_4H_BARS * BAR_MS
        times = [first + i * BAR_MS for i in range(MIN_4H_BARS + 3)]
        self.data = {
            f'S{i:02d}USDT': pd.DataFrame({'open_time': times,
                                            'close': [100 * (1 + i / 10000) ** j for j in range(len(times))],
                                            'quote_volume': [6_000_000] * len(times)}).set_index('open_time')
            for i in range(20)
        }

    def test_future_candles_cannot_change_picks(self):
        before = rank_week(self.data, self.monday)
        self.assertEqual(before['status'], 'RESEARCH_SIGNAL')
        self.assertEqual(before['fill_open_utc'], '2026-03-02T04:00:00Z')
        self.data['S00USDT'].loc[self.monday + BAR_MS, 'close'] = 1_000_000
        after = rank_week(self.data, self.monday)
        self.assertEqual(before, after)
        self.assertEqual(len(after['legs']), 4)

    def test_data_gap_blocks_cycle_below_20_symbols(self):
        missing = self.monday - BAR_MS * 10
        self.data['S01USDT'] = self.data['S01USDT'].drop(missing)
        self.assertEqual(rank_week(self.data, self.monday)['status'], 'SKIP_INSUFFICIENT_SYMBOLS')

    def test_wrong_clock_is_rejected(self):
        with self.assertRaises(ValueError):
            rank_week(self.data, self.monday + BAR_MS)


if __name__ == '__main__':
    unittest.main()
