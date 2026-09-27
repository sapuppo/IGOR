"""Independent synthetic source and ledger corruption tests; no user returns."""
import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import r16_31_funding_source_gate as gate


class FundingSourceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.dataset = self.root / 'dataset'
        self.marks = self.root / 'marks'
        (self.dataset / 'funding').mkdir(parents=True)
        self.marks.mkdir()
        self.fund_path = self.dataset / 'funding' / 'BTCUSDT.csv.gz'
        self.mark_path = self.marks / 'BTCUSDT.json.gz'
        self.ledger_path = self.root / 'ledger.jsonl.gz'
        self.pre = 1698624000000
        self.post = gate.SOURCE_CUTOFF
        with gzip.open(self.fund_path, 'wt', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['fundingTime', 'fundingRate'])
            w.writeheader()
            w.writerows([{'fundingTime': self.pre, 'fundingRate': '0.01'},
                         {'fundingTime': self.post, 'fundingRate': '0.01'}])
        self.marks_rows = [dict(symbol='BTCUSDT', fundingTime=self.pre, fundingRate='0.01', markPrice=''),
                           dict(symbol='BTCUSDT', fundingTime=self.post, fundingRate='0.01', markPrice='100')]
        self.ledger_rows = [dict(event='FUNDING', timestamp=self.pre, symbol='BTCUSDT', rate=0.01,
                                 allocations=[dict(qty=2, side=1, mark_price=90, cashflow=-1.8)]),
                            dict(event='FUNDING', timestamp=self.post, symbol='BTCUSDT', rate=0.01,
                                 allocations=[dict(qty=2, side=1, mark_price=100, cashflow=-2)])]
        self.rewrite()

    def rewrite(self):
        with gzip.open(self.mark_path, 'wt') as f:
            json.dump(self.marks_rows, f)
        self.marks_manifest = {'source_dataset_sha256': '', 'symbols': [
            dict(symbol='BTCUSDT', expected=2, received=2,
                 missing_mark_price=sum(not x['markPrice'] for x in self.marks_rows),
                 sha256=gate.digest(self.mark_path))]}
        with gzip.open(self.ledger_path, 'wt') as f:
            for row in self.ledger_rows:
                f.write(json.dumps(row) + '\n')
        unsigned = {'files': [dict(path='funding/BTCUSDT.csv.gz', sha256=gate.digest(self.fund_path))],
                    'symbols': [dict(symbol='BTCUSDT', eligible=True)]}
        self.dataset_sha = gate.fingerprint(unsigned)
        (self.dataset / 'manifest.json').write_text(json.dumps({**unsigned, 'dataset_manifest_sha256': self.dataset_sha}))
        self.marks_manifest['source_dataset_sha256'] = self.dataset_sha
        (self.marks / 'manifest.json').write_text(json.dumps(self.marks_manifest))

    def check(self):
        with patch.object(gate, 'DATA_SHA', self.dataset_sha):
            return gate.audit(self.dataset, self.marks, {'BASE': self.ledger_path})

    def test_verified_window_is_separate_from_full_block(self):
        r = self.check()
        self.assertEqual(r['status_full_2021_2026'], 'BLOCKED_MISSING_EXACT_MARKS')
        self.assertEqual(r['status_2023_11_2026_06'], 'SOURCE_COVERAGE_PASS')
        self.assertEqual(r['ledger_evidence']['BASE']['mismatch_count'], 0)

    def test_bad_ledger_cash_cannot_pass(self):
        self.ledger_rows[1]['allocations'][0]['cashflow'] = -1.5
        self.rewrite()
        r = self.check()
        self.assertEqual(r['status_2023_11_2026_06'], 'BLOCKED')
        self.assertIn('ledger funding cash mismatch', r['ledger_evidence']['BASE']['examples'][0])

    def test_post_cut_missing_mark_cannot_pass(self):
        self.marks_rows[1]['markPrice'] = ''
        self.rewrite()
        r = self.check()
        self.assertEqual(r['status_2023_11_2026_06'], 'BLOCKED')
        self.assertEqual(r['total']['cut_window_missing'], 1)

    def test_tampered_mark_archive_fails_checksum(self):
        with gzip.open(self.mark_path, 'wt') as f:
            json.dump(self.marks_rows[:1], f)
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.check()


if __name__ == '__main__':
    unittest.main()
