#!/usr/bin/env python3
"""Check reconciliation failure paths on synthetic, explicitly non-account data."""
import copy
import unittest

from r17_execution_audit import AuditError, audit


def fixture():
    trades = [
        {'symbol': 'BTCUSDT', 'id': 1, 'orderId': 21, 'time': 1000, 'side': 'BUY', 'maker': False,
         'price': '100', 'qty': '1', 'quoteQty': '100', 'commissionAsset': 'USDT',
         'commission': '0.06', 'realizedPnl': '0'},
        {'symbol': 'BTCUSDT', 'id': 2, 'orderId': 22, 'time': 2000, 'side': 'SELL', 'maker': False,
         'price': '110', 'qty': '1', 'quoteQty': '110', 'commissionAsset': 'USDT',
         'commission': '0.066', 'realizedPnl': '10'},
    ]
    income = [
        {'incomeType': 'COMMISSION', 'income': '-0.126', 'asset': 'USDT', 'tranId': 1, 'time': 2000},
        {'incomeType': 'REALIZED_PNL', 'income': '10', 'asset': 'USDT', 'tranId': 2, 'time': 2000},
        {'incomeType': 'FUNDING_FEE', 'income': '-0.4', 'asset': 'USDT', 'tranId': 3, 'time': 1500},
    ]
    decisions = [
        {'symbol': 'BTCUSDT', 'orderId': 21, 'decisionTime': 900, 'referencePrice': '99'},
        {'symbol': 'BTCUSDT', 'orderId': 22, 'decisionTime': 1900, 'referencePrice': '111'},
    ]
    return trades, income, decisions


class AuditTest(unittest.TestCase):
    def test_funding_and_realized_are_counted_once_and_slippage_is_adverse(self):
        got = audit(*fixture())
        self.assertEqual(got['totals_usdt']['realized_after_commission_and_funding'], '9.474')
        self.assertGreater(float(got['adverse_signed_slippage_rate_p95']), 0)
        self.assertEqual(got['status'], 'NOT_READY')
        self.assertIn('EXPORT_COVERAGE_UNVERIFIED', got['blocking_reasons'])

    def test_duplicate_fill_and_wrong_income_fail(self):
        trades, income, decisions = fixture()
        with self.assertRaises(AuditError):
            audit(trades + [copy.deepcopy(trades[0])], income, decisions)
        income[0]['income'] = '-0.100'
        self.assertIn('COMMISSION_MISMATCH', audit(trades, income, decisions)['blocking_reasons'])

    def test_no_reference_never_means_zero_slippage(self):
        trades, income, _ = fixture()
        got = audit(trades, income)
        self.assertIsNone(got['adverse_signed_slippage_rate_p95'])
        self.assertIn('MISSING_DECISION_PRICE', got['blocking_reasons'])

    def test_future_decision_or_non_usdt_fee_is_rejected(self):
        trades, income, decisions = fixture()
        decisions[0]['decisionTime'] = 1001
        with self.assertRaisesRegex(AuditError, 'depois do fill'):
            audit(trades, income, decisions)
        trades[0]['commissionAsset'] = 'BNB'
        with self.assertRaisesRegex(AuditError, 'outra moeda'):
            audit(trades, income)


if __name__ == '__main__':
    unittest.main()
