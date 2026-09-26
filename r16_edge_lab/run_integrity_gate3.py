"""Gate 3: exercises the production replay and independently reconstructs cash.

PASS means a tested invariant, BLOCKED means missing source evidence. Neither a
green workflow nor a fixed funding-rate assumption can override a BLOCKED gate.
"""
from collections import Counter
import math
import numpy as np
import pandas as pd
from r16_sim_core import PortfolioLedger
from r16_usdm_engine import CONFIG, START, END, BAR, Dataset, generate_signals, replay, exit_reference, fingerprint


def near(a, b, label):
    assert abs(a-b) <= 1e-7*max(1., abs(a), abs(b)), (label, a, b)


def independent_audit(result, data, scenario):
    """Reconstruct positions, costs, funding and margin from event payloads.

    Deliberately does not call ledger.equity(), assert_reconciles() or Position
    methods, so the audit cannot merely repeat a success flag from production.
    """
    model = CONFIG["scenarios"][scenario]
    cash = CONFIG["capital"]; gross = fees = slips = funding = 0.
    positions = {}; previous = -1; orders = {}; count = Counter(); shadows = []
    source_rates = {(t, s): r for t, s, r in data.funding}
    max_entry_gross = max_entry_risk = 0.
    maximum_error = 0.
    for row in result.ledger.events:
        event, timestamp = row["event"], row["timestamp"]
        assert timestamp >= previous, (timestamp, previous)
        previous = timestamp
        count[event] += 1
        if event == "ORDER":
            orders[row["id"]] = row
        elif event == "OPEN":
            key, qty = row["position_id"], row["qty"]
            side = row["side"]; ref = row["reference_price"]; fill = row["fill_price"]
            order = orders[key]
            assert timestamp > order["knowledge_ts"] >= order["source_open_ts"]
            assert timestamp >= order["earliest_fill_ts"]
            times = data.bars[row["symbol"]][0]
            expected_idx = np.searchsorted(times, order["earliest_fill_ts"])
            assert int(times[expected_idx]) == timestamp, "not next available execution observation"
            bar = data.bar(row["symbol"], timestamp)
            near(ref, float(bar[0]), "entry reference")
            near(fill, ref*(1+model["slip"]), "adverse entry slippage")
            assert timestamp >= data.pit[row["symbol"]]
            commission = qty*fill*model["fee"]
            slippage = side*qty*(fill-ref)
            near(commission, row["commission"], "entry fee")
            near(slippage, row["slippage_cost_event"], "entry slippage")
            cash -= commission+slippage; fees += commission; slips += slippage
            positions[key] = {"symbol": row["symbol"], "side": side, "qty": qty, "fill": fill, "ref": ref,
                              "mark": ref, "stop": row["stop_price"], "margin": qty*fill, "funding": 0.}
        elif event == "MARK":
            for p in positions.values():
                if p["symbol"] == row["symbol"]:
                    p["mark"] = row["price"]
        elif event == "MARK_BATCH":
            for p in positions.values():
                if p["symbol"] in row["prices"]:
                    p["mark"] = row["prices"][p["symbol"]]
        elif event == "FUNDING":
            near(row["rate"], source_rates[(timestamp, row["symbol"])], "historical rate")
            net = 0.
            for key, p in positions.items():
                if p["symbol"] != row["symbol"]:
                    continue
                payment = -p["side"]*p["qty"]*p["mark"]*row["rate"]
                p["funding"] += payment; net += payment
                allocation = next(a for a in row["allocations"] if a["position_id"] == key)
                near(payment, allocation["cashflow"], "funding allocation")
            near(net, row["funding_cashflow"], "funding cashflow")
            cash += net; funding += net
        elif event == "CLOSE":
            p = positions.pop(row["position_id"])
            pnl = p["side"]*p["qty"]*(row["reference_price"]-p["ref"])
            commission = p["qty"]*row["fill_price"]*model["fee"]
            slippage = -p["side"]*p["qty"]*(row["fill_price"]-row["reference_price"])
            near(pnl, row["gross_pnl_event"], "gross pnl")
            near(commission, row["commission"], "exit commission")
            near(slippage, row["slippage_cost_event"], "exit slippage")
            assert slippage >= 0
            cash += pnl-commission-slippage; gross += pnl; fees += commission; slips += slippage
        elif event == "SHADOW_CLOSE":
            assert row["entry_ts"] < row["exit_ts"] == timestamp
            shadows.append(row)
        elif event == "ALLOCATION":
            assert all(t is None or t <= timestamp for t in row["regime_last_exit"].values())
            month = pd.Timestamp(timestamp, unit="ms", tz="UTC").tz_localize(None).to_period("M")
            cutoff = int((month-CONFIG["regime_months"]).start_time.tz_localize("UTC").timestamp()*1000)
            for engine, score in row["scores"].items():
                eligible = [x for x in shadows if x["engine"] == engine and cutoff <= x["exit_ts"] <= timestamp]
                near(score, sum(x["net_pct"] for x in eligible)/len(eligible) if eligible else 0., "independent closed-only regime score")
        unrealized = sum(p["side"]*p["qty"]*(p["mark"]-p["ref"]) for p in positions.values())
        margin = sum(p["margin"]+p["funding"] for p in positions.values())
        equity = cash+unrealized
        notional = sum(p["qty"]*p["mark"] for p in positions.values())
        risk = sum(max(0., p["side"]*p["qty"]*(p["fill"]-p["stop"]))+
                   abs(p["qty"]*p["stop"])*(model["fee"]+model["slip"]) for p in positions.values())
        reconstructed = {"cash": cash, "equity": equity, "unrealized": unrealized,
                         "reserved_margin": margin, "available_collateral": cash-margin,
                         "gross_notional": notional, "open_stop_risk": risk,
                         "commissions": fees, "slippage_cost": slips, "funding": funding, "realized_gross": gross}
        for field, value in reconstructed.items():
            maximum_error = max(maximum_error, abs(value-row[field]))
            near(value, row[field], field)
        near(CONFIG["capital"]+gross-fees-slips+funding, cash, "independent cash identity")
        assert cash-margin >= -1e-7, "cash collateral deficit"
        if positions:
            assert min(p["margin"]+p["funding"]+p["side"]*p["qty"]*(p["mark"]-p["ref"]) for p in positions.values()) > 0, "isolated wallet requires liquidation modeling"
        if event == "OPEN":
            max_entry_gross = max(max_entry_gross, notional/equity)
            max_entry_risk = max(max_entry_risk, risk/equity)
            assert notional/equity <= 1+1e-9, "entry exposure breach"
            assert risk/equity <= CONFIG["max_stop_risk"]+1e-9, "entry stop-risk breach"
    return {"events": len(result.ledger.events), "event_counts": dict(count),
            "max_entry_gross_equity": max_entry_gross, "max_entry_stop_risk": max_entry_risk,
            "maximum_absolute_reconciliation_error": maximum_error}


def execution_fixture():
    p = {"stop": 95., "target": 110., "deadline": 99}
    assert exit_reference(p, [100, 115, 90, 112], 50) == (95., "STOP_AMBIGUOUS")
    assert exit_reference(p, [90, 115, 85, 112], 50, at_open=True) == (90., "STOP_GAP")
    assert exit_reference(p, [115, 120, 112, 116], 50, at_open=True) == (110., "TARGET_GAP")
    risk_ledger = PortfolioLedger(10000.)
    ok, reason = risk_ledger.can_open(side=1, qty=80, fill_price=100, stop_price=92.6,
                                      entry_fee_rate=0, exit_fee_rate=0)
    assert not ok and reason == "aggregate_stop_risk", "risk reserve ignored open-loss equity floor"
    for side in (1, -1):
        ledger = PortfolioLedger(10000., max_stop_risk_fraction=.5)
        fill = 100*(1+side*.0002)
        stop = 95 if side == 1 else 105
        assert ledger.open(1, "p", "FIXTURE", "X", side, 10, fill, stop, .0004, .0004, 100., .0002)[0]
        ledger.mark(2, "X", 102.)
        ledger.funding_event(3, "X", .001)
        near(ledger.funding, -side*1.02, "signed positive funding")
        ledger.funding_event(4, "X", -.002)
        near(ledger.funding, side*1.02, "signed negative funding")
        exit_ref = 110. if side == 1 else 90.
        exit_fill = exit_ref*(1-side*.0002)
        ledger.close(5, "p", exit_fill, .0004, "FIXTURE", exit_ref)
        expected = 10000+side*10*(exit_ref-100)-10*(fill+exit_fill)*.0004
        expected -= side*10*(fill-100)-side*10*(exit_fill-exit_ref)
        expected += side*1.02
        near(ledger.cash, expected, "independent nonzero cost fixture")
        try:
            ledger.mark(4, "X", 100.)
        except AssertionError:
            pass
        else:
            raise AssertionError("monotonicity guard weakened")
    return {"same_bar": "stop_first", "gap": "adverse", "sides": ["long", "short"], "nonzero_slippage": True}


def run_gate(data, signals, base, stress, reports, protocol, fingerprints):
    results = []
    def check(number, name, fn):
        try:
            evidence = fn()
            results.append({"number": number, "name": name, "status": "PASS", "evidence": evidence})
        except Exception as exc:
            results.append({"number": number, "name": name, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        print("GATE3", number, name, results[-1]["status"], flush=True)

    cutoff = int(pd.Timestamp("2021-07-01", tz="UTC").timestamp()*1000)-1
    full_prefix = [e for e in base.ledger.events if e["timestamp"] <= cutoff]
    def perturb():
        altered = Dataset(data.root, perturb_after=cutoff, verify=False, gap_root=data.gap_root, funding_mark_root=data.funding_mark_root)
        changed_signals = generate_signals(altered)
        assert signals != changed_signals, "test failed to change future signals"
        assert [s for s in signals if s["timestamp"] <= cutoff] == [s for s in changed_signals if s["timestamp"] <= cutoff]
        r = replay(altered, changed_signals, until=cutoff, liquidate_end=False)
        assert r.ledger.events == full_prefix, "future perturbation changed past ledger"
        return {"cutoff": cutoff, "compared_events": len(full_prefix), "future_signals_changed": True}
    check(1, "future_data_perturbation", perturb)
    def prefix():
        truncated = Dataset(data.root, cutoff=cutoff, verify=False, gap_root=data.gap_root, funding_mark_root=data.funding_mark_root)
        prefix_signals = generate_signals(truncated)
        assert prefix_signals == [s for s in signals if s["timestamp"] <= cutoff]
        r = replay(truncated, prefix_signals, until=cutoff, liquidate_end=False)
        assert r.ledger.events == full_prefix, "truncated replay differs from full prefix"
        engine_counts = Counter(t["engine"] for t in r.trades)
        assert set(engine_counts) == set(CONFIG["engines"]), "prefix fixture lacks engine coverage"
        return {"compared_events": len(full_prefix), "trades_by_engine": dict(engine_counts), "open_positions_at_cut": len(r.ledger.positions)}
    check(2, "prefix_replay", prefix)
    audit = {}
    def accounting():
        audit["BASE"] = independent_audit(base, data, "BASE")
        audit["STRESS"] = independent_audit(stress, data, "STRESS")
        return audit
    # Run the independent checks once; linked gates cannot pass if it fails.
    accounting_error = None
    try:
        accounting()
    except Exception as exc:
        accounting_error = exc
    def audited(field):
        if accounting_error:
            raise accounting_error
        return {name: row[field] for name, row in audit.items()}
    check(3, "next_observation_execution", lambda: audited("event_counts"))
    check(4, "no_prelisting_trades", lambda: {"events": audited("events"), "scope": "fixed cohort; first historical funding is a conservative tradability lower bound, not complete listing metadata"})
    if results[-1]["status"] == "PASS" and (base.diagnostics["missing_active_bars"] or stress.diagnostics["missing_active_bars"]):
        results[-1]["status"] = "BLOCKED"
        results[-1]["blocking_reason"] = "No prelisting trades, but active-position observations are missing from the frozen dataset and its supplement."
    check(5, "conservative_intrabar_execution", execution_fixture)
    check(6, "closed_only_realized_regime", lambda: audited("event_counts"))
    check(7, "mtm_equity_reconciliation", lambda: {"errors": audited("maximum_absolute_reconciliation_error"), "mark_scope": "last-traded-price model, not exchange mark series"})
    check(8, "cash_margin_collateral_reconciliation", lambda: audited("maximum_absolute_reconciliation_error"))
    check(9, "exposure_at_entry", lambda: audited("max_entry_gross_equity"))
    def risk_check():
        evidence = audited("max_entry_stop_risk")
        # The contract requires reporting all-event risk as well as entry checks.
        for name, r in reports.items():
            assert r["max_open_stop_risk_fraction"] <= CONFIG["max_stop_risk"]+1e-9, (name, r["max_open_stop_risk_fraction"])
        return {"entry": evidence, "all_event_max": {n: r["max_open_stop_risk_fraction"] for n, r in reports.items()}}
    check(10, "aggregate_stop_risk", risk_check)
    check(11, "modeled_fees_and_funding_arithmetic", lambda: {"reconciliation": audited("maximum_absolute_reconciliation_error"), "fixture": execution_fixture()})
    proxy_count = sum(r.diagnostics["funding_settlement_evidence"].get("proxy",0) for r in (base,stress))
    if results[-1]["status"] == "PASS" and proxy_count:
        results[-1]["status"] = "BLOCKED"
        results[-1]["name"] = "historical_fee_funding_reconciliation"
        results[-1]["blocking_reason"] = f"Arithmetic and historical rates/timestamps reconcile, but {proxy_count} BASE+STRESS shadow/portfolio funding events lack official settlement markPrice and use an explicit price proxy. Fixed fees remain a declared modeling assumption."
    def deterministic():
        duplicate = replay(data, signals)
        expected, actual = base.ledger.manifest(), duplicate.ledger.manifest()
        assert expected == actual and base.trades == duplicate.trades and base.daily == duplicate.daily
        return {"full_history_ledger_sha256": actual["ledger_sha256"], "events": actual["events"]}
    check(12, "deterministic_full_replay", deterministic)
    def isolation():
        windows = protocol["historical_windows"]
        assert not protocol["optimization"] and not protocol["selection_on_evaluation_windows"]
        for i, window in enumerate(windows):
            assert window["feature_history_start"] < window["evaluation_start"] < window["evaluation_end_exclusive"]
            if i:
                assert windows[i-1]["evaluation_end_exclusive"] <= window["evaluation_start"]
        assert fingerprint(CONFIG) == fingerprints["config_sha256"]
        assert results[0]["status"] == results[1]["status"] == "PASS"
        return {"windows": len(windows), "fitting": False, "selection": False,
                "causal_prefix_proof": results[0]["status"] == results[1]["status"] == "PASS",
                "untouched_oos": False, "contamination": protocol["contamination"]}
    check(13, "chronological_walkforward_isolation", isolation)
    def reporting():
        for name, result in (("BASE", base), ("STRESS", stress)):
            r = reports[name]; final = result.ledger.equity()
            near(np.prod([1+x for x in r["monthly"].values()])*CONFIG["capital"], final, "monthly compounding")
            near(np.prod([1+x for x in r["annual"].values()])*CONFIG["capital"], final, "annual compounding")
            assert not result.ledger.positions, "report contains censored trades"
            near(sum(t["net"] for t in result.trades), final-CONFIG["capital"], "trade to equity")
            for label in ("engine", "symbol", "regime"):
                near(sum(v["net"] for v in r["attribution"][label].values()), final-CONFIG["capital"], "attribution")
        return {"months": len(reports["BASE"]["monthly"]), "years": len(reports["BASE"]["annual"])}
    check(14, "ledger_monthly_yearly_reconciliation", reporting)
    def baseline():
        assert fingerprints["dataset_manifest_sha256"] == CONFIG["dataset_manifest_sha256"]
        assert fingerprints["config_sha256"] == fingerprint(CONFIG)
        assert len(fingerprints["code_files"]) >= 5
        assert fingerprints["protocol_sha256"] == fingerprint(protocol)
        return fingerprints
    check(15, "baseline_fingerprint", baseline)
    counts = Counter(row["status"] for row in results)
    return {"version": "Gate 3", "status": "TECHNICALLY_VALID" if counts["PASS"] == 15 else "TECHNICALLY_INVALID",
            "counts": dict(counts), "invariants": results,
            "oos_validated": False, "live_capital_authorized": False}
