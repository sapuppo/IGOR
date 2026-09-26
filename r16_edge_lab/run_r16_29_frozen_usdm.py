#!/usr/bin/env python3
"""R16.29.2 USD-M rebuild, production Gate 3 and chronological diagnostics."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import platform
import sys
import time
import numpy as np
import pandas as pd
from r16_usdm_engine import CONFIG, Dataset, generate_signals, replay, fingerprint
from r16_usdm_reports import metrics, chronological_diagnostics
from run_integrity_gate3 import run_gate


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="r16_edge_lab/usdm_history")
    parser.add_argument("--out", default="r16_edge_lab/r16_29_frozen_usdm")
    args = parser.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).parent
    protocol = json.loads((source/"r16_29_validation_protocol.json").read_text())
    code_names = ["run_r16_29_frozen_usdm.py", "r16_usdm_engine.py", "r16_sim_core.py", "run_integrity_gate3.py",
                  "r16_usdm_reports.py", "collect_r16_29_funding_marks.py", "collect_r16_29_gap_evidence.py", "r16_29_frozen_config.json",
                  "r16_29_validation_protocol.json", "requirements-r16-29.txt", "BACKTEST_INTEGRITY_CONTRACT.md"]
    fingerprints = {"dataset_manifest_sha256": CONFIG["dataset_manifest_sha256"],
                    "config_sha256": fingerprint(CONFIG), "protocol_sha256": fingerprint(protocol),
                    "code_files": {n: hashlib.sha256((source/n).read_bytes()).hexdigest() for n in code_names},
                    "code_commit": os.environ.get("IGOR_CODE_SHA", "LOCAL_UNCOMMITTED"),
                    "workflow_sha": os.environ.get("GITHUB_SHA"), "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
                    "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__}}
    save_json(out/"frozen_config.json", CONFIG)
    save_json(out/"validation_protocol.json", protocol)
    save_json(out/"fingerprints.json", fingerprints)
    started = time.monotonic()
    data = Dataset(args.root)
    fingerprints["supplements"] = data.supplements
    fingerprints["effective_input_sha256"] = fingerprint({"original":CONFIG["dataset_manifest_sha256"],"supplements":data.supplements})
    save_json(out/"fingerprints.json", fingerprints)
    print("FROZEN_DATA_VERIFIED", len(data.manifest["files"]), flush=True)
    signals = generate_signals(data)
    print("NATIVE_USDM_SIGNALS", dict(pd.Series([s["engine"] for s in signals]).value_counts()), flush=True)
    with gzip.GzipFile(filename=str(out/"signals.jsonl.gz"), mode="wb", mtime=0) as f:
        for row in signals:
            f.write((json.dumps(row, sort_keys=True, allow_nan=False)+"\n").encode())
    results = {}; reports = {}
    for scenario in ("BASE", "STRESS"):
        result = replay(data, signals, scenario=scenario)
        results[scenario] = result
        report = metrics(result)
        reports[scenario] = report
        name = scenario.lower()
        save_json(out/f"{name}_metrics.json", report)
        save_json(out/f"{name}_diagnostics.json", result.diagnostics)
        save_json(out/f"{name}_ledger_manifest.json", result.ledger.manifest())
        pd.DataFrame(result.trades).to_csv(out/f"{name}_trades.csv", index=False)
        pd.DataFrame(result.daily).to_csv(out/f"{name}_daily_mtm.csv", index=False)
        with gzip.GzipFile(filename=str(out/f"{name}_ledger.jsonl.gz"), mode="wb", mtime=0) as f:
            for row in result.ledger.events:
                f.write((json.dumps(row, sort_keys=True, allow_nan=False)+"\n").encode())
        save_json(out/f"{name}_chronological_windows.json", chronological_diagnostics(report, protocol))
        print("REPLAY_COMPLETE", scenario, "events", len(result.ledger.events), "trades", len(result.trades), flush=True)
    gate = run_gate(data, signals, results["BASE"], results["STRESS"], reports, protocol, fingerprints)
    save_json(out/"integrity_gate3.json", gate)
    summary = {"version": CONFIG["version"], "status": gate["status"], "gate3": gate["counts"],
               "dataset_manifest_sha256": CONFIG["dataset_manifest_sha256"],
               "config_sha256": fingerprints["config_sha256"], "code_commit": fingerprints["code_commit"],
               "blocking_reasons": [{"invariant": r["number"], "reason": r.get("blocking_reason", r.get("error"))}
                                    for r in gate["invariants"] if r["status"] != "PASS"],
               "oos_validated": False, "untouched_oos_result": None,
               "economic_results_scope": "diagnostics only; no valid realized/live edge claim",
               "base": reports["BASE"], "stress": reports["STRESS"],
               "limitations": ["Funding cashflows use historical rates/timestamps with last-traded price proxy; settlement markPrice is absent from frozen source.",
                               "MTM uses last-traded 15m OHLC, not exchange markPrice; intrabar funding/stop order is unresolved by OHLC.",
                               "Fixed 39-symbol research cohort is not an unbiased historical reconstruction of the complete exchange universe.",
                               "Listing lower bound uses first archived funding, not independently archived onboard/delist metadata.",
                               "All historical windows were previously available for alpha selection; no untouched OOS claim.",
                               "Continuous quantity, assumed fees and spread/slippage; historical lot/tick/min-notional filters not reconstructed.",
                               "No margin-tier liquidation engine; isolated equity checked, 1x entry collateral enforced.",
                               "Prior full strategy-search attempt count is unknown; no deflated significance claim."],
               "elapsed_seconds": round(time.monotonic()-started, 2)}
    save_json(out/"summary.json", summary)
    save_json(out/"artifact_manifest.json", {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in sorted(out.iterdir()) if p.is_file() and p.name != "artifact_manifest.json"})
    print(json.dumps({"version": summary["version"], "status": summary["status"], "gate3": gate["counts"],
                      "blockers": summary["blocking_reasons"], "elapsed_seconds": summary["elapsed_seconds"]}, indent=2), flush=True)
    return 2 if gate["counts"].get("FAIL", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
