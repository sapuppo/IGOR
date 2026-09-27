#!/usr/bin/env python3
"""Audit source coverage of frozen USD-M funding rates and actual settlement marks.

This is a read-only SOURCE gate. It does not change the R16.29.2 replay, approve
fees/fills, establish an untouched OOS period, or imply profitability.
"""
import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

SOURCE_CUTOFF = 1698796800000  # 2023-11-01T00:00:00Z, post addition of markPrice to USD-M fundingRate
END_EXCLUSIVE = 1782864000000  # 2026-07-01T00:00:00Z, frozen R16.29.2 end
DATA_SHA = 'a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def year(ms):
    return str(datetime.fromtimestamp(ms / 1000, timezone.utc).year)


def audit(dataset, marks_root, ledgers):
    dataset_manifest = json.loads((dataset / 'manifest.json').read_text())
    unsigned = {k: v for k, v in dataset_manifest.items() if k != 'dataset_manifest_sha256'}
    if fingerprint(unsigned) != DATA_SHA or dataset_manifest.get('dataset_manifest_sha256') != DATA_SHA:
        raise ValueError('frozen dataset manifest fingerprint mismatch')
    mark_manifest_path = marks_root / 'manifest.json'
    marks_manifest = json.loads(mark_manifest_path.read_text())
    if marks_manifest['source_dataset_sha256'] != DATA_SHA:
        raise ValueError('mark supplement belongs to another dataset')
    official_files = {Path(f['path']).name: f['sha256'] for f in dataset_manifest['files'] if 'funding/' in f['path']}
    symbols = {s['symbol'] for s in dataset_manifest['symbols'] if s['eligible']}
    mark_rows = {s['symbol']: s for s in marks_manifest['symbols']}
    if symbols != set(mark_rows):
        raise ValueError('frozen eligible symbols and mark supplement symbols differ')
    totals = Counter()
    annual = {}
    source = {}
    first = {}
    last_missing = {}
    for symbol in sorted(symbols):
        fund_path = dataset / 'funding' / (symbol + '.csv.gz')
        mark_path = marks_root / (symbol + '.json.gz')
        if digest(fund_path) != official_files.get(fund_path.name):
            raise ValueError(f'{symbol}: frozen funding CSV checksum mismatch')
        if digest(mark_path) != mark_rows[symbol]['sha256']:
            raise ValueError(f'{symbol}: mark JSON checksum mismatch')
        with gzip.open(fund_path, 'rt', newline='') as f:
            original = list(csv.DictReader(f))
        with gzip.open(mark_path, 'rt') as f:
            supplement = json.load(f)
        if len(original) != mark_rows[symbol]['expected'] or len(supplement) != mark_rows[symbol]['received']:
            raise ValueError(f'{symbol}: source row count mismatch')
        last = -1
        missing = 0
        for a, b in zip(original, supplement, strict=True):
            when = int(a['fundingTime'])
            if when <= last or when != int(b['fundingTime']) or b['symbol'] != symbol:
                raise ValueError(f'{symbol}: missing, shifted or unsorted funding event')
            last = when
            if abs(Decimal(a['fundingRate']) - Decimal(b['fundingRate'])) > Decimal('0.000000000001'):
                raise ValueError(f'{symbol}: funding rate mismatch at {when}')
            mark = str(b.get('markPrice') or '')
            exact = bool(mark and Decimal(mark).is_finite() and Decimal(mark) > 0)
            if not exact:
                missing += 1
                last_missing[symbol] = when
            elif symbol not in first:
                first[symbol] = when
            row = annual.setdefault(year(when), Counter())
            row['events'] += 1
            row['exact' if exact else 'missing_mark'] += 1
            totals['events'] += 1
            totals['exact' if exact else 'missing_mark'] += 1
            if SOURCE_CUTOFF <= when < END_EXCLUSIVE:
                totals['cut_window_events'] += 1
                if not exact:
                    totals['cut_window_missing'] += 1
            source[(when, symbol)] = (Decimal(b['fundingRate']), Decimal(mark) if exact else None)
        if missing != mark_rows[symbol]['missing_mark_price']:
            raise ValueError(f'{symbol}: declared missing mark count mismatch')

    checks = {}
    for name, path in sorted(ledgers.items()):
        total = Counter()
        mismatches = []
        with gzip.open(path, 'rt') as f:
            for line in f:
                row = json.loads(line)
                if row['event'] != 'FUNDING':
                    continue
                when, symbol = int(row['timestamp']), row['symbol']
                key = when, symbol
                if key not in source:
                    mismatches.append(f'ledger event not in official source: {symbol} {when}')
                    continue
                rate, mark = source[key]
                if abs(rate - Decimal(str(row['rate']))) > Decimal('0.000000000001'):
                    mismatches.append(f'rate mismatch: {symbol} {when}')
                total['events'] += 1
                total['pre_cut' if when < SOURCE_CUTOFF else 'post_cut'] += 1
                if mark is None:
                    total['missing_mark'] += 1
                if when >= SOURCE_CUTOFF:
                    if mark is None:
                        mismatches.append(f'missing post-cut mark: {symbol} {when}')
                    else:
                        for alloc in row['allocations']:
                            if abs(Decimal(str(alloc['mark_price'])) - mark) > Decimal('0.000001'):
                                mismatches.append(f'ledger mark mismatch: {symbol} {when}')
                            expected = -Decimal(str(alloc['qty'])) * mark * rate * Decimal(str(alloc['side']))
                            if abs(Decimal(str(alloc['cashflow'])) - expected) > Decimal('0.000001'):
                                mismatches.append(f'ledger funding cash mismatch: {symbol} {when}')
        checks[name] = {'counts': dict(total), 'ledger_sha256': digest(path),
                        'mismatch_count': len(mismatches), 'examples': mismatches[:5]}
    return {
        'status_full_2021_2026': 'BLOCKED_MISSING_EXACT_MARKS' if totals['missing_mark'] else 'SOURCE_EXACT',
        'status_2023_11_2026_06': 'SOURCE_COVERAGE_PASS' if not totals['cut_window_missing'] and all(not c['mismatch_count'] for c in checks.values()) else 'BLOCKED',
        'scope': 'funding source/ledger checks only; never a new backtest, technical validity, OOS or promotion',
        'cut_utc': '2023-11-01T00:00:00Z', 'end_exclusive_utc': '2026-07-01T00:00:00Z',
        'source_dataset_sha256': DATA_SHA, 'marks_manifest_sha256': digest(mark_manifest_path),
        'eligible_symbols': len(symbols), 'total': dict(totals),
        'by_utc_year': {k: dict(v) for k, v in sorted(annual.items())},
        'first_exact_marks_ms': first, 'last_missing_marks_ms': last_missing,
        'ledger_evidence': checks,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--marks', type=Path, required=True)
    p.add_argument('--base-ledger', type=Path, required=True)
    p.add_argument('--stress-ledger', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    try:
        result = audit(a.dataset, a.marks, {'BASE': a.base_ledger, 'STRESS': a.stress_ledger})
    except (ValueError, KeyError, OSError, ArithmeticError, json.JSONDecodeError) as e:
        print(f'BLOCKED: {e}', file=sys.stderr)
        return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('status_full_2021_2026','status_2023_11_2026_06','eligible_symbols','total')}, sort_keys=True))
    return 0 if result['status_2023_11_2026_06'] == 'SOURCE_COVERAGE_PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
