"""Synthetic, labelled test data; never evidence of the user's actual fills."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from r16_30_execution_reconcile import reconcile

START = 1788220800000


class ExecutionGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.plans, self.trades, self.income = [base / x for x in ('plans.csv', 'trades.json', 'income.json')]
        self.plan_rows = [
            ['p1', 'ENTRY', 'BTCUSDT', 'BUY', '101', START + 1000, '100', '2', '0.2'],
            ['p1', 'EXIT', 'BTCUSDT', 'SELL', '102', START + 8000, '110', '2', '0.2'],
        ]
        self.trade_rows = [
            dict(id=1, orderId=101, symbol='BTCUSDT', side='BUY', time=START+2000,
                 qty='1', price='100', commission='0.05', commissionAsset='USDT', realizedPnl='0'),
            dict(id=2, orderId=101, symbol='BTCUSDT', side='BUY', time=START+3000,
                 qty='1', price='101', commission='0.05', commissionAsset='USDT', realizedPnl='0'),
            dict(id=3, orderId=102, symbol='BTCUSDT', side='SELL', time=START+9000,
                 qty='2', price='109', commission='0.10', commissionAsset='USDT', realizedPnl='17'),
        ]
        self.income_rows = [
            dict(tranId=1, incomeType='FUNDING_FEE', income='-0.25', asset='USDT', time=START+5000, symbol='BTCUSDT'),
            dict(tranId=2, incomeType='COMMISSION', income='-0.20', asset='USDT', time=START+9000, symbol='BTCUSDT'),
            dict(tranId=3, incomeType='REALIZED_PNL', income='17', asset='USDT', time=START+9000, symbol='BTCUSDT'),
        ]

    def run_gate(self, asserted=True, expected_funding=None):
        with self.plans.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['position_id','leg','symbol','side','exchange_order_id','submit_ts_ms','reference_price','planned_qty','sim_fee_usdt'])
            w.writerows(self.plan_rows)
        self.trades.write_text(json.dumps(self.trade_rows), encoding='utf-8')
        self.income.write_text(json.dumps(self.income_rows), encoding='utf-8')
        return reconcile(self.plans, self.trades, self.income, START, START+10000,
                         asserted, asserted, asserted, expected_funding)

    def test_partial_fills_adverse_price_and_funding(self):
        out = self.run_gate()
        self.assertEqual(out['status'], 'SAMPLE_RECONCILED')
        self.assertEqual(out['totals_usdt']['net_trade_fields_and_funding'], '16.55')
        self.assertEqual(out['totals_usdt']['net_paired_cash_and_funding'], '16.55')
        self.assertEqual(out['orders'][0]['fills'], 2)
        self.assertEqual(out['orders'][0]['adverse_execution_usdt'], '1.0')
        self.assertEqual(out['orders'][1]['adverse_execution_usdt'], '2')
        self.assertEqual(out['totals_usdt']['execution_price_delta_vs_reference'], '-3')
        self.assertEqual(out['totals_usdt']['fee_delta_actual_minus_model'], '-0.20')

    def test_missing_half_of_partial_fill_blocks(self):
        self.trade_rows.pop(1)
        out = self.run_gate()
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertIn('PARTIAL_OR_OVERFILL', [p['code'] for p in out['problems']])

    def test_funding_and_commission_mismatch_block(self):
        self.income_rows[0]['income'] = '-2'
        self.income_rows[1]['income'] = '-0.01'
        out = self.run_gate(expected_funding='-0.25')
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertIn('COMMISSION_LEDGER_MISMATCH', [p['code'] for p in out['problems']])
        self.assertIn('FUNDING_MODEL_MISMATCH', [p['code'] for p in out['problems']])
        self.assertEqual(out['totals_usdt']['funding'], '-2')

    def test_missing_coverage_or_non_usdt_fee_blocks(self):
        self.trade_rows[0]['commissionAsset'] = 'BNB'
        out = self.run_gate(asserted=False)
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertIn('FEE_CONVERSION_REQUIRED', [p['code'] for p in out['problems']])
        self.assertIn('COVERAGE_UNPROVEN', [p['code'] for p in out['problems']])

    def test_unrelated_execution_blocks_even_when_export_asserted_complete(self):
        self.trade_rows.append(dict(self.trade_rows[0], id=99, orderId=999))
        out = self.run_gate()
        self.assertIn('UNMATCHED_TRADE', [p['code'] for p in out['problems']])

    def test_no_account_records_never_passes(self):
        self.trade_rows = []
        self.income_rows = []
        out = self.run_gate(asserted=False)
        self.assertEqual(out['status'], 'BLOCKED')
        self.assertIn('NO_REAL_TRADES', [p['code'] for p in out['problems']])
        self.assertIn('NO_INCOME_LEDGER', [p['code'] for p in out['problems']])


if __name__ == '__main__':
    unittest.main()
