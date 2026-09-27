#!/usr/bin/env python3
"""Preregistered, technical-only H1 funding replay; does not output PnL/returns."""
import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from r16_31_funding_source_gate import SOURCE_CUTOFF, END_EXCLUSIVE, DATA_SHA
from r16_usdm_engine import CONFIG, Dataset, replay, fingerprint

SIGNALS_SHA = 'c6a01e1e0a7f32640861213e3dba83fcdfebbef5eb8d172dc1ecc955579be71d'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit-root', type=Path, required=True)
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--gap-root', type=Path, required=True)
    p.add_argument('--marks', type=Path, required=True)
    p.add_argument('--source-report', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    source = json.loads(a.source_report.read_text())
    assert source['status_2023_11_2026_06'] == 'SOURCE_COVERAGE_PASS'
    assert source['source_dataset_sha256'] == DATA_SHA
    assert fingerprint(CONFIG) == json.loads((a.audit_root / 'fingerprints.json').read_text())['config_sha256']
    signal_file = a.audit_root / 'signals.jsonl.gz'
    assert hashlib.sha256(signal_file.read_bytes()).hexdigest() == SIGNALS_SHA
    with gzip.open(signal_file, 'rt') as stream:
        signals = [json.loads(line) for line in stream]
    assert len(signals) == 6650
    selected = [x for x in signals if x['engine'] in ('CORE', 'REV1H')]
    data = Dataset(a.dataset, gap_root=a.gap_root, funding_mark_root=a.marks)
    result = {'prereg_commit': '5e408fa85bd852186597e891ea105a298208fe58',
              'classification': 'TECHNICALLY_INVALID; OOS_VALIDATED=false; no live approval',
              'cut_utc': '2023-11-01T00:00:00Z', 'until_exclusive_utc': '2026-07-01T00:00:00Z',
              'source_report_sha256': hashlib.sha256(a.source_report.read_bytes()).hexdigest(),
              'frozen_signals_sha256': SIGNALS_SHA, 'dataset_sha256': DATA_SHA,
              'scenarios': {}}
    for scenario in ('BASE', 'STRESS'):
        scoped = replay(data, selected, scenario=scenario, trade_start=SOURCE_CUTOFF,
                        until=END_EXCLUSIVE-1)
        evidence = scoped.diagnostics['funding_settlement_evidence']
        funding_rows = [e for e in scoped.ledger.events if e['event'] == 'FUNDING']
        mismatches = []
        for row in funding_rows:
            key = (row['timestamp'], row['symbol'])
            mark = data.funding_marks.get(key)
            if mark is None or any(abs(v['mark_price'] - mark) > 1e-6 for v in row['allocations']):
                mismatches.append(key)
        verdict = ('PASS' if evidence.get('proxy', 0) == 0 and
                   scoped.diagnostics['missing_active_bars'] == 0 and
                   not mismatches else 'BLOCKED')
        result['scenarios'][scenario] = {
            'status': verdict, 'funding_shadow_evidence': evidence,
            'ledger_funding_events': len(funding_rows),
            'ledger_funding_allocation_count': sum(len(r['allocations']) for r in funding_rows),
            'ledger_missing_exact_mark': len(mismatches),
            'missing_active_bars': scoped.diagnostics['missing_active_bars'],
            'ledger_sha256': scoped.ledger.manifest()['ledger_sha256'],
            'ledger_event_count': len(scoped.ledger.events),
        }
        print(scenario, verdict, result['scenarios'][scenario]['funding_shadow_evidence'], flush=True)
        del scoped
    result['funding_subtest_status'] = ('SOURCE_AND_SCOPED_FUNDING_PASS' if
                                        all(v['status'] == 'PASS' for v in result['scenarios'].values())
                                        else 'BLOCKED')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print('FUNDING_SUBTEST', result['funding_subtest_status'], flush=True)
    return 0 if result['funding_subtest_status'].endswith('_PASS') else 2


if __name__ == '__main__':
    raise SystemExit(main())
