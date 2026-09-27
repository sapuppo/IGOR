#!/usr/bin/env python3
"""Reproduce Jan-Jun 2026 month-end MTM for fixed H1, with no optimization."""
import argparse
import gzip
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from r16_31_funding_source_gate import SOURCE_CUTOFF, END_EXCLUSIVE, DATA_SHA
from r16_usdm_engine import CONFIG, Dataset, replay, fingerprint

SIGNALS_SHA = 'c6a01e1e0a7f32640861213e3dba83fcdfebbef5eb8d172dc1ecc955579be71d'
EXPECTED_LEDGER = {
    'BASE': '4f29c9046ea921dfc676616670f63987422d75474ea7419feaac1482ee9fe151',
    'STRESS': '1499a6fb2ef83f56d0054f1354c3a2f7d4164fa2a8c4584066cfb027801782cc',
}
MONTHS = [f'2026-{i:02d}' for i in range(1, 7)]


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def summarize(monthly):
    values = [monthly[k] for k in MONTHS]
    cumulative = math.prod(1 + v for v in values) - 1
    return dict(months=len(values), cumulative_return=cumulative,
                compound_monthly=(1+cumulative)**(1/6)-1,
                arithmetic_monthly=sum(values)/6,
                positive_months=sum(v > 0 for v in values),
                negative_months=sum(v < 0 for v in values),
                months_at_least_20pct=sum(v >= .2 for v in values))


def monthly_from_daily(daily):
    ends = {}
    for row in daily:
        ts = int(row['timestamp'])
        date = datetime.fromtimestamp(ts / 1000, timezone.utc)
        ends[date.strftime('%Y-%m')] = {'day': date.strftime('%Y-%m-%d'),
                                         'equity': float(row['equity']), 'snapshot': row}
    sequence = ['2025-12'] + MONTHS
    if any(k not in ends for k in sequence):
        raise ValueError(f'missing month end: {[k for k in sequence if k not in ends]}')
    for k in sequence:
        y, m = map(int, k.split('-'))
        next_month = datetime(y+1, 1, 1, tzinfo=timezone.utc) if m == 12 else datetime(y, m+1, 1, tzinfo=timezone.utc)
        if ends[k]['day'] != (next_month - timedelta(days=1)).strftime('%Y-%m-%d'):
            raise ValueError(f'{k}: last daily mark not on calendar month end')
    monthly = {}
    for prev, now in zip(sequence, sequence[1:]):
        monthly[now] = ends[now]['equity'] / ends[prev]['equity'] - 1
    stats = summarize(monthly)
    direct = ends['2026-06']['equity'] / ends['2025-12']['equity'] - 1
    if abs(direct - stats['cumulative_return']) > 1e-10:
        raise ValueError('monthly compounding and MTM endpoints disagree')
    final = ends['2026-06']['snapshot']; before = ends['2025-12']['snapshot']
    cashflow = {
        'realized_gross_usdt': float(final['realized_gross'] - before['realized_gross']),
        'commission_usdt': float(final['commissions'] - before['commissions']),
        'slippage_usdt': float(final['slippage_cost'] - before['slippage_cost']),
        'funding_cashflow_usdt': float(final['funding'] - before['funding']),
    }
    cashflow['equity_delta_usdt'] = ends['2026-06']['equity'] - ends['2025-12']['equity']
    cashflow['gross_minus_cost_plus_funding_usdt'] = (cashflow['realized_gross_usdt'] -
         cashflow['commission_usdt'] - cashflow['slippage_usdt'] + cashflow['funding_cashflow_usdt'])
    if abs(cashflow['equity_delta_usdt'] - cashflow['gross_minus_cost_plus_funding_usdt']) > 1e-6:
        raise ValueError('2026 monthly equity change fails cashflow reconciliation')
    return monthly, {k: ends[k]['equity'] for k in sequence}, stats, cashflow


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit-root', type=Path, required=True)
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--gap-root', type=Path, required=True)
    p.add_argument('--marks', type=Path, required=True)
    p.add_argument('--h1-archive', type=Path, required=True)
    p.add_argument('--funding-report', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    prior = json.loads(a.funding_report.read_text())
    assert prior['funding_subtest_status'] == 'SOURCE_AND_SCOPED_FUNDING_PASS'
    assert prior['dataset_sha256'] == DATA_SHA
    assert fingerprint(CONFIG) == json.loads((a.audit_root / 'fingerprints.json').read_text())['config_sha256']
    signals_file = a.audit_root / 'signals.jsonl.gz'
    assert digest(signals_file) == SIGNALS_SHA
    with gzip.open(signals_file, 'rt') as f:
        all_signals = [json.loads(line) for line in f]
    assert len(all_signals) == 6650
    selected = [v for v in all_signals if v['engine'] in ('CORE','REV1H')]
    data = Dataset(a.dataset, gap_root=a.gap_root, funding_mark_root=a.marks)
    archive_checksums = json.loads((a.h1_archive / 'artifact_manifest.json').read_text())
    result = {
        'status': 'RETROSPECTIVE_DIAGNOSTIC_ONLY', 'method_commit': '498febaf8d17607e537dcb9bafa4ed6ed9a8425a',
        'period_utc': ['2026-01-01', '2026-07-01 (exclusive)'],
        '2026_july_december': 'NO_DATA_IN_FROZEN_REPLAY',
        'live_account_return': 'NOT_MEASURED',
        'source_report_sha256': digest(a.funding_report),
        'dataset_sha256': DATA_SHA, 'signals_sha256': SIGNALS_SHA,
        'scoped_2023_start': {}, 'continuous_2021_start': {},
    }
    for scenario in ('BASE','STRESS'):
        scoped = replay(data, selected, scenario=scenario, trade_start=SOURCE_CUTOFF,
                        until=END_EXCLUSIVE-1)
        ledger_sha = scoped.ledger.manifest()['ledger_sha256']
        if ledger_sha != EXPECTED_LEDGER[scenario] or ledger_sha != prior['scenarios'][scenario]['ledger_sha256']:
            raise ValueError(f'{scenario} scoped ledger differs from R16.31')
        if scoped.diagnostics['funding_settlement_evidence'].get('proxy', 0):
            raise ValueError(f'{scenario} has proxy funding')
        monthly, ends, stats, cost = monthly_from_daily(scoped.daily)
        start_2026 = int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp()*1000)
        closed = [t for t in scoped.trades if start_2026 <= t['exit_ts'] < END_EXCLUSIVE]
        by_engine = {}
        for trade in closed:
            row = by_engine.setdefault(trade['engine'], {'trades': 0, 'gross_usdt': 0.,
                                   'commissions_usdt': 0., 'slippage_usdt': 0.,
                                   'funding_usdt': 0., 'net_usdt': 0.})
            row['trades'] += 1
            for field, target in [('gross','gross_usdt'),('commissions','commissions_usdt'),
                                  ('slippage','slippage_usdt'),('funding','funding_usdt'),('net','net_usdt')]:
                row[target] += trade[field]
        result['scoped_2023_start'][scenario] = {
            'monthly': monthly, 'month_end_equity_usdt': ends,
            'jan_jun': stats, 'model_cashflows_2026': cost,
            'closed_trades_2026': len(closed), 'closed_trade_attribution_by_engine': by_engine,
            'ledger_sha256': ledger_sha,
            'funding_events_exact': scoped.diagnostics['funding_settlement_evidence'].get('exact', 0),
        }
        archive = a.h1_archive / f'h1_{scenario.lower()}_metrics.json'
        if digest(archive) != archive_checksums[archive.name]:
            raise ValueError(f'{scenario} H1 archive checksum mismatch')
        frozen = json.loads(archive.read_text())
        historic = {k: frozen['monthly'][k] for k in MONTHS}
        historical_stats = summarize(historic)
        if abs(historical_stats['cumulative_return'] - frozen['annual']['2026']) > 1e-10:
            raise ValueError('continuous H1 2026 monthly / annual mismatch')
        result['continuous_2021_start'][scenario] = {
            'monthly': historic, 'jan_jun': historical_stats,
            'archive_metrics_sha256': digest(archive),
            'warning': '2021-2023 funding price proxies influence the later equity path',
        }
        print(scenario,'scoped Jan-Jun',stats,'continuous Jan-Jun',historical_stats,flush=True)
        del scoped
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('REPORT_SAVED',a.out,flush=True)


if __name__ == '__main__':
    main()
