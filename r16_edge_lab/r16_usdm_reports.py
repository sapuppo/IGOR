"""Calendar MTM and trade/cost attribution, independent of alpha selection."""
from collections import defaultdict
import math
import numpy as np
import pandas as pd
from r16_usdm_engine import CONFIG, START, END, DAY, fingerprint


def metrics(result):
    ledger = result.ledger
    events = ledger.events
    daily = pd.DataFrame(result.daily)
    daily.index = pd.to_datetime(daily.timestamp, unit="ms", utc=True)
    eq = daily.equity
    month_end = eq.resample("ME").last()
    monthly = month_end / month_end.shift(fill_value=ledger.start_cash) - 1
    year_end = eq.resample("YE").last()
    annual = year_end / year_end.shift(fill_value=ledger.start_cash) - 1
    returns = eq / eq.shift(fill_value=ledger.start_cash) - 1
    values = np.array([e["equity"] for e in events])
    dd = 1-values/np.maximum.accumulate(values)
    net = np.array([t["net"] for t in result.trades])
    duration_days = (int(daily.timestamp.iloc[-1])+1-START)/DAY
    final = ledger.equity()
    std = float(returns.std(ddof=1))
    downside = float(np.sqrt(np.mean(np.minimum(returns, 0)**2)))
    gains = float(net[net > 0].sum()); losses = float(-net[net < 0].sum())
    groups = {}
    for label in ("engine", "symbol", "regime"):
        stats = defaultdict(lambda: {"trades": 0, "gross": 0., "commissions": 0., "slippage": 0., "funding": 0., "net": 0.})
        for trade in result.trades:
            row = stats[trade[label]]
            row["trades"] += 1
            for field in ("gross", "commissions", "slippage", "funding", "net"):
                row[field] += trade[field]
        groups[label] = dict(stats)
    weights = []
    utilization = []
    gross_exposure = []
    for i in range(1, len(events)-1):
        e = events[i]
        duration = max(0, events[i+1]["timestamp"]-max(e["timestamp"], START))
        weights.append(duration)
        utilization.append(e["reserved_margin"]/e["equity"])
        gross_exposure.append(e["gross_to_equity"])
    turnover = sum(t["qty"]*(t["entry_fill"]+t["exit_fill"]) for t in result.trades)/float(eq.mean())
    sub = monthly[monthly.index >= "2022-01-01"]
    result_dict = {
        "economic_status": "DIAGNOSTIC_UNTIL_ALL_INTEGRITY_GATES_PASS; historical sample is not untouched OOS",
        "return": final/ledger.start_cash-1,
        "cagr": (final/ledger.start_cash)**(365.25/duration_days)-1,
        "compound_monthly": (final/ledger.start_cash)**(1/len(monthly))-1,
        "monthly_mean": float(monthly.mean()), "monthly_median": float(monthly.median()),
        "positive_month_fraction": float((monthly > 0).mean()),
        "worst_month": float(monthly.min()), "best_month": float(monthly.max()),
        "monthly": {k.strftime("%Y-%m"): float(v) for k, v in monthly.items()},
        "annual": {str(k.year): float(v) for k, v in annual.items()},
        "max_drawdown_mtm": float(dd.max()),
        "sharpe_daily_365_zero_rf": float(returns.mean())/std*math.sqrt(365) if std > 0 else None,
        "sortino_daily_365_zero_target": float(returns.mean())/downside*math.sqrt(365) if downside > 0 else None,
        "ratios_scope": "descriptive daily crypto returns, not corrected for autocorrelation or selection/multiple-testing",
        "profit_factor_net": gains/losses if losses > 0 else None,
        "expectancy_usdt": float(net.mean()) if len(net) else None,
        "win_rate": float((net > 0).mean()) if len(net) else None,
        "trades": len(net), "turnover_gross_over_mean_daily_equity": turnover,
        "time_weighted_capital_utilization": float(np.average(utilization, weights=weights)) if sum(weights) else 0.,
        "time_weighted_gross_equity": float(np.average(gross_exposure, weights=weights)) if sum(weights) else 0.,
        "max_gross_equity": max(e["gross_to_equity"] for e in events),
        "max_open_stop_risk_fraction": max(e["open_stop_risk"]/e["equity"] for e in events),
        "gross_pnl": ledger.realized_gross, "commissions": ledger.commissions,
        "slippage": ledger.slippage_cost, "funding_cashflow": ledger.funding,
        "total_cost_net_of_funding_receipts": ledger.commissions+ledger.slippage_cost-ledger.funding,
        "attribution": groups,
        "period_2022_2026": {"return": float((1+sub).prod()-1), "compound_monthly": float((1+sub).prod()**(1/len(sub))-1)},
    }
    return result_dict


def chronological_diagnostics(report, protocol):
    rows = []
    config_hash = fingerprint(CONFIG)
    for window in protocol["historical_windows"]:
        a = window["evaluation_start"][:7]; b = window["evaluation_end_exclusive"][:7]
        monthly = [v for k, v in report["monthly"].items() if a <= k < b]
        rows.append({**window, "config_sha256": config_hash, "fitting": False, "selection": False,
                     "label": protocol["historical_label"], "months": len(monthly),
                     "return": float(np.prod(np.array(monthly)+1)-1)})
    return {"windows": rows, "oos_validated": False, "untouched_holdout_result": None,
            "reason": protocol["contamination"], "prospective_holdout": protocol["prospective_holdout"]}
