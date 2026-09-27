"""Preregistered H1 ablation of REV15M, using untouched R16.29.2 engine."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--audit-root', type=Path, required=True)
parser.add_argument('--data-root', type=Path, required=True)
parser.add_argument('--gap-root', type=Path, required=True)
parser.add_argument('--funding-mark-root', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from r16_usdm_engine import CONFIG, Dataset, replay, fingerprint  # noqa: E402
from r16_usdm_reports import metrics  # noqa: E402

AUDIT = args.audit_root
OUT = args.out
OUT.mkdir(parents=True,exist_ok=True)

assert fingerprint(CONFIG) == json.loads((AUDIT / 'fingerprints.json').read_text())['config_sha256']
data = Dataset(args.data_root, gap_root=args.gap_root, funding_mark_root=args.funding_mark_root)
with gzip.open(AUDIT / 'signals.jsonl.gz', 'rt') as stream:
    signals = [json.loads(line) for line in stream]
assert len(signals) == 6650
print('VERIFIED_INPUTS', len(data.manifest['files']), len(signals), data.supplements, flush=True)

result = {'prereg_branch': 'r16-30-research', 'trial': 'H1_remove_REV15M',
          'code_commit': 'f8c2307533265653f1faf0832fda836b21641f85',
          'data_fingerprint': CONFIG['dataset_manifest_sha256'],
          'signals_sha256': hashlib.sha256((AUDIT / 'signals.jsonl.gz').read_bytes()).hexdigest(),
          'scenario': {}}
for scenario in ('BASE', 'STRESS'):
    t0 = time.monotonic()
    full = replay(data, signals, scenario=scenario)
    old = json.loads((AUDIT / f'{scenario.lower()}_ledger_manifest.json').read_text())
    assert full.ledger.manifest()['ledger_sha256'] == old['ledger_sha256'], 'environment failed to reproduce baseline'
    report = metrics(full)
    benchmark = json.loads((AUDIT / f'{scenario.lower()}_metrics.json').read_text())
    for key in ('return', 'compound_monthly', 'max_drawdown_mtm','trades'):
        assert abs(report[key] - benchmark[key]) <= 1e-11, (scenario, key, report[key], benchmark[key])
    print('BASELINE_REPRODUCED', scenario, len(full.ledger.events),old['ledger_sha256'],round(time.monotonic()-t0,1),flush=True)
    del full

    t0 = time.monotonic()
    trimmed = [x for x in signals if x['engine'] != 'REV15M']
    trial = replay(data, trimmed, scenario=scenario)
    m = metrics(trial)
    assert trial.diagnostics['missing_active_bars'] == 0
    assert max(e['gross_to_equity'] for e in trial.ledger.events if e['event'] == 'OPEN') <= 1 + 1e-6
    assert m['max_open_stop_risk_fraction'] <= CONFIG['max_stop_risk'] + 1e-8
    assert all(t['engine'] in ('CORE', 'REV1H') for t in trial.trades)
    with (OUT / f'h1_{scenario.lower()}_trades.csv').open('w',newline='') as stream:
        if trial.trades:
            writer = csv.DictWriter(stream, fieldnames=list(trial.trades[0]))
            writer.writeheader(); writer.writerows(trial.trades)
    (OUT / f'h1_{scenario.lower()}_metrics.json').write_text(json.dumps(m, indent=2, sort_keys=True) + '\n')
    (OUT / f'h1_{scenario.lower()}_ledger_manifest.json').write_text(json.dumps(trial.ledger.manifest(),indent=2,sort_keys=True) + '\n')
    (OUT / f'h1_{scenario.lower()}_diagnostics.json').write_text(json.dumps(trial.diagnostics,indent=2,sort_keys=True) + '\n')
    result['scenario'][scenario] = {'baseline_ledger_sha256': old['ledger_sha256'],
                                   'h1_ledger_sha256': trial.ledger.manifest()['ledger_sha256'],
                                   'baseline_metrics': {k:benchmark[k] for k in ('return','compound_monthly','max_drawdown_mtm','trades','gross_pnl','commissions','slippage','funding_cashflow','time_weighted_capital_utilization')},
                                   'h1_metrics': {k:m[k] for k in ('return','compound_monthly','max_drawdown_mtm','trades','gross_pnl','commissions','slippage','funding_cashflow','time_weighted_capital_utilization','max_gross_equity','max_open_stop_risk_fraction')},
                                   'h1_engine_attribution': m['attribution']['engine'],
                                   'h1_annual': m['annual'],
                                   'funding_evidence': trial.diagnostics['funding_settlement_evidence'],
                                   'elapsed_seconds': round(time.monotonic()-t0,2)}
    print('H1_RESULT', scenario, 'trades',m['trades'],'monthly',m['compound_monthly'],'drawdown',m['max_drawdown_mtm'],round(time.monotonic()-t0,1),flush=True)
    (OUT / 'progress.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
result['technical_status'] = 'TECHNICALLY_INVALID: historical funding markPrice incomplete; no OOS'
(OUT / 'h1_result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
(OUT / 'artifact_manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir()) if p.is_file() and p.name not in ('artifact_manifest.json','progress.json')}, indent=2)+'\n')
print('RESEARCH_COMPLETE',flush=True)
