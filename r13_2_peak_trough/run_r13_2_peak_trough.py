from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from r13_1_mtf import run_r13_1_mtf as base

VERSION = "V10-R13.2-HORIZON-ALIGNED-PEAK-TROUGH"
EXPECTED_R13_1_PREDICTION_HASH = "4424cdfc150818dbbb031cdda9c8d05ce3f760c515527a0be9c8e95d219e957b"

# Ranking and entry logic are intentionally frozen from R13.1.
ENTRY_TAIL = base.ENTRY_TAIL
HOLD_TAIL = base.HOLD_TAIL
MIN_SLOTS = base.MIN_SLOTS
ONE_WAY_COST = base.ONE_WAY_COST
STRESS_ONE_WAY_COST = base.STRESS_ONE_WAY_COST
INITIAL_EQUITY = base.INITIAL_EQUITY

# R13.2 exit hypothesis, frozen before the run.
MIN_HOLD_HOURS = 12
MAX_HOLD_HOURS = 72
EXIT_COOLDOWN_HOURS = 1

# Only catastrophic price protection is allowed before MIN_HOLD_HOURS.
EMERGENCY_ATR_MULT = 6.0
EMERGENCY_STOP_MIN = 0.08
EMERGENCY_STOP_MAX = 0.15

# Peak/trough exhaustion detector on completed 15m bars.
EXHAUSTION_MIN_MFE = 0.010
EXHAUSTION_ENTRY_ATR_MULT = 2.0
COMPRESSION_MAX = 0.55
EXTREME_LONG_MIN = 0.70
EXTREME_SHORT_MAX = 0.30
EXHAUSTION_CONFIRM_BARS = 2

# Exit only after a meaningful giveback plus a confirmed structural break.
GIVEBACK_FRACTION_OF_MFE = 0.30
GIVEBACK_ATR_MULT = 1.25

R13_1_BASELINE = {
    "trades": 12808,
    "win_rate": 0.3206589631480325,
    "avg_trade_net_return": -0.0026100017269323414,
    "profit_factor_cash": 0.7757826467867264,
    "positive_fold_share": 0.05263157894736842,
    "compounded_fold_return": -0.9736457868908938,
    "max_fold_drawdown": 0.43347567720766356,
    "avg_hold_hours": 9.387336039975015,
}


def add_exec_features(d: pd.DataFrame) -> pd.DataFrame:
    q = d.copy()
    prev = q.close.shift(1)
    tr = pd.concat([
        (q.high - q.low),
        (q.high - prev).abs(),
        (q.low - prev).abs(),
    ], axis=1).max(axis=1)
    q["atr14"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    q["atr_pct"] = q.atr14 / q.close
    q["atr_pct_prev"] = q.atr_pct.shift(1)

    q["ema20"] = q.close.ewm(span=20, adjust=False, min_periods=20).mean()
    q["ema50"] = q.close.ewm(span=50, adjust=False, min_periods=50).mean()
    q["ema20_slope_1h"] = q.ema20.pct_change(4)
    q["ret_1h"] = q.close.pct_change(4)
    q["ret_2h"] = q.close.pct_change(8)

    q["high_1h_prev"] = q.high.shift(1).rolling(4, min_periods=4).max()
    q["low_1h_prev"] = q.low.shift(1).rolling(4, min_periods=4).min()
    q["high_2h"] = q.high.rolling(8, min_periods=8).max()
    q["low_2h"] = q.low.rolling(8, min_periods=8).min()
    q["high_8h"] = q.high.rolling(32, min_periods=32).max()
    q["low_8h"] = q.low.rolling(32, min_periods=32).min()

    range2 = (q.high_2h - q.low_2h) / q.close.replace(0, np.nan)
    range8 = (q.high_8h - q.low_8h) / q.close.replace(0, np.nan)
    q["compression_2h_vs_8h"] = range2 / range8.replace(0, np.nan)
    den = (q.high_8h - q.low_8h).replace(0, np.nan)
    q["range_pos_8h"] = (q.close - q.low_8h) / den
    return q


def mark_equity(realized_equity, positions, prices):
    u = 0.0
    for s, p in positions.items():
        px = prices.get(s)
        if px is None or not np.isfinite(px):
            continue
        u += p["notional"] * p["side"] * (px / p["entry_price"] - 1.0)
    return realized_equity + u


def simulate_fold_peak_trough(pred, data15, fold_start, fold_end, one_way_cost):
    if pred.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "NO_PREDICTIONS"}

    syms = sorted(pred.symbol.unique())
    bars = {
        s: add_exec_features(
            data15[s].loc[
                (data15[s].index >= fold_start - pd.Timedelta(hours=24))
                & (data15[s].index < fold_end + pd.Timedelta(minutes=15))
            ].copy()
        )
        for s in syms
    }

    timeline = pd.date_range(
        fold_start,
        fold_end - pd.Timedelta(minutes=15),
        freq="15min",
        tz="UTC",
    )

    signal_at = {}
    for ts, g in pred.groupby(level=0, sort=True):
        et = ts + pd.Timedelta(minutes=15)
        if fold_start <= et < fold_end:
            signal_at[et] = g.sort_values("pred_rank", ascending=False).copy()

    realized = INITIAL_EQUITY
    positions = {}
    trades = []
    curve = []
    peak_equity = INITIAL_EQUITY
    last_prices = {}
    cooldown_until = {}
    latest_rank_pct = {}

    def close_position(s, when, price, reason):
        nonlocal realized
        p = positions.pop(s)
        gross_ret = p["side"] * (price / p["entry_price"] - 1.0)
        pnl_gross = p["notional"] * gross_ret
        exit_cost = p["notional"] * one_way_cost
        realized += pnl_gross - exit_cost
        net_ret = gross_ret - 2.0 * one_way_cost
        mfe = float(max(p.get("mfe_return", 0.0), 0.0))
        mae = float(max(p.get("mae_return", 0.0), 0.0))
        capture = float(gross_ret / mfe) if mfe > 1e-12 else None
        trades.append({
            "symbol": s,
            "side": "LONG" if p["side"] > 0 else "SHORT",
            "entry_time": p["entry_time"],
            "exit_time": when,
            "entry_price": p["entry_price"],
            "exit_price": float(price),
            "notional": p["notional"],
            "gross_return": float(gross_ret),
            "net_return": float(net_ret),
            "pnl_cash": float(pnl_gross - p["entry_cost"] - exit_cost),
            "hold_hours": float((when - p["entry_time"]) / pd.Timedelta(hours=1)),
            "entry_atr_pct": p["entry_atr_pct"],
            "emergency_stop_frac": p["emergency_stop_frac"],
            "mfe_return": mfe,
            "mae_return": mae,
            "mfe_capture_ratio": capture,
            "mfe_giveback": float(mfe - gross_ret),
            "exhaustion_seen": bool(p.get("exhaustion_seen", False)),
            "exit_state": p.get("state", "TRENDING"),
            "exit_reason": reason,
        })
        cooldown_until[s] = when + pd.Timedelta(hours=EXIT_COOLDOWN_HOURS)

    for t in timeline:
        rows = {}
        opens, highs, lows, closes = {}, {}, {}, {}
        for s in syms:
            if t not in bars[s].index:
                continue
            r = bars[s].loc[t]
            rows[s] = r
            opens[s] = float(r.open)
            highs[s] = float(r.high)
            lows[s] = float(r.low)
            closes[s] = float(r.close)
            last_prices[s] = float(r.close)

        # Exits confirmed on a completed 15m bar execute at the next 15m open.
        for s in list(positions):
            p = positions[s]
            reason = p.get("pending_exit")
            if reason and s in opens:
                close_position(s, t, opens[s], reason)

        # Hourly OOS ranking update (same signal and 15m delay as R13.1).
        if t in signal_at:
            q = signal_at[t]
            pct = q.set_index("symbol").pred_pct.to_dict()
            latest_rank_pct.update(pct)

            n = len(q)
            k = max(MIN_SLOTS, int(math.floor(n * ENTRY_TAIL)))
            long_entry = list(
                q[q.pred_pct >= 1.0 - ENTRY_TAIL]
                .sort_values("pred_rank", ascending=False)
                .symbol
            )[:k]
            short_entry = list(
                q[q.pred_pct <= ENTRY_TAIL]
                .sort_values("pred_rank", ascending=True)
                .symbol
            )[:k]

            open_equity = mark_equity(realized, positions, opens)
            if open_equity <= 0:
                break

            for side, candidates in ((1, long_entry), (-1, short_entry)):
                existing = [p for p in positions.values() if p["side"] == side]
                side_exposure = 0.0
                for p in existing:
                    px = opens.get(p["symbol"], p["entry_price"])
                    side_exposure += p["notional"] * px / p["entry_price"]
                capacity = max(0.0, 0.5 * open_equity - side_exposure)

                new_syms = []
                for s in candidates:
                    if s in positions or s not in opens:
                        continue
                    if cooldown_until.get(s, pd.Timestamp.min.tz_localize("UTC")) > t:
                        continue
                    atr = rows[s].get("atr_pct_prev", np.nan)
                    if not np.isfinite(atr):
                        continue
                    new_syms.append(s)

                if not new_syms or capacity <= 0:
                    continue

                target_each = 0.5 * open_equity / max(k, 1)
                for s in new_syms:
                    if capacity <= 1e-9:
                        break
                    notional = min(target_each, capacity)
                    if notional <= 1e-9:
                        continue
                    entry_atr = float(rows[s].atr_pct_prev)
                    emergency_frac = float(np.clip(
                        EMERGENCY_ATR_MULT * entry_atr,
                        EMERGENCY_STOP_MIN,
                        EMERGENCY_STOP_MAX,
                    ))
                    entry_price = opens[s]
                    entry_cost = notional * one_way_cost
                    realized -= entry_cost
                    positions[s] = {
                        "symbol": s,
                        "side": side,
                        "entry_time": t,
                        "entry_price": float(entry_price),
                        "notional": float(notional),
                        "entry_cost": float(entry_cost),
                        "entry_atr_pct": entry_atr,
                        "emergency_stop_frac": emergency_frac,
                        "emergency_stop_price": float(
                            entry_price * (1.0 - emergency_frac if side > 0 else 1.0 + emergency_frac)
                        ),
                        "best_price": float(entry_price),
                        "worst_price": float(entry_price),
                        "mfe_return": 0.0,
                        "mae_return": 0.0,
                        "state": "TRENDING",
                        "exhaustion_count": 0,
                        "exhaustion_seen": False,
                        "pending_exit": None,
                    }
                    capacity -= notional

        # Catastrophic protection only. Ordinary 15m stops were deliberately removed.
        for s in list(positions):
            if s not in rows:
                continue
            p = positions[s]
            sp = p["emergency_stop_price"]
            if p["side"] > 0:
                if opens[s] <= sp:
                    close_position(s, t, opens[s], "EMERGENCY_GAP")
                    continue
                if lows[s] <= sp:
                    close_position(s, t, sp, "EMERGENCY_STOP")
                    continue
            else:
                if opens[s] >= sp:
                    close_position(s, t, opens[s], "EMERGENCY_GAP")
                    continue
                if highs[s] >= sp:
                    close_position(s, t, sp, "EMERGENCY_STOP")
                    continue

        # Update state on the completed 15m bar. Any normal exit is delayed to next open.
        for s in list(positions):
            if s not in rows:
                continue
            p = positions[s]
            r = rows[s]
            side = p["side"]
            entry = p["entry_price"]

            if side > 0:
                p["best_price"] = max(p["best_price"], highs[s])
                p["worst_price"] = min(p["worst_price"], lows[s])
                p["mfe_return"] = max(p["mfe_return"], p["best_price"] / entry - 1.0)
                p["mae_return"] = max(p["mae_return"], 1.0 - p["worst_price"] / entry)
            else:
                p["best_price"] = min(p["best_price"], lows[s])
                p["worst_price"] = max(p["worst_price"], highs[s])
                p["mfe_return"] = max(p["mfe_return"], 1.0 - p["best_price"] / entry)
                p["mae_return"] = max(p["mae_return"], p["worst_price"] / entry - 1.0)

            age_h = float((t + pd.Timedelta(minutes=15) - p["entry_time"]) / pd.Timedelta(hours=1))
            gross_close = side * (closes[s] / entry - 1.0)

            if age_h >= MAX_HOLD_HOURS:
                p["pending_exit"] = "MAX_HOLD"
                continue

            if age_h < MIN_HOLD_HOURS:
                continue

            atr = float(r.atr_pct) if np.isfinite(r.atr_pct) else p["entry_atr_pct"]
            activation = max(
                EXHAUSTION_MIN_MFE,
                EXHAUSTION_ENTRY_ATR_MULT * p["entry_atr_pct"],
            )
            mfe = float(p["mfe_return"])
            giveback = max(0.0, mfe - gross_close)
            giveback_gate = (
                mfe > 0
                and giveback >= max(
                    GIVEBACK_ATR_MULT * atr,
                    GIVEBACK_FRACTION_OF_MFE * mfe,
                )
            )

            compression = float(r.compression_2h_vs_8h) if np.isfinite(r.compression_2h_vs_8h) else np.inf
            range_pos = float(r.range_pos_8h) if np.isfinite(r.range_pos_8h) else 0.5
            ret1h = float(r.ret_1h) if np.isfinite(r.ret_1h) else 0.0
            ema20 = float(r.ema20) if np.isfinite(r.ema20) else closes[s]
            ema_slope = float(r.ema20_slope_1h) if np.isfinite(r.ema20_slope_1h) else 0.0
            low_prev = float(r.low_1h_prev) if np.isfinite(r.low_1h_prev) else -np.inf
            high_prev = float(r.high_1h_prev) if np.isfinite(r.high_1h_prev) else np.inf

            if side > 0:
                at_extreme = range_pos >= EXTREME_LONG_MIN
                decelerating = ret1h <= atr
                structure_break = (
                    closes[s] < low_prev
                    or (closes[s] < ema20 and ema_slope < 0)
                )
                rank_bad = latest_rank_pct.get(s, 1.0) < 1.0 - HOLD_TAIL
                rank_reversed = latest_rank_pct.get(s, 1.0) <= ENTRY_TAIL
            else:
                at_extreme = range_pos <= EXTREME_SHORT_MAX
                decelerating = (-ret1h) <= atr
                structure_break = (
                    closes[s] > high_prev
                    or (closes[s] > ema20 and ema_slope > 0)
                )
                rank_bad = latest_rank_pct.get(s, 0.0) > HOLD_TAIL
                rank_reversed = latest_rank_pct.get(s, 0.0) >= 1.0 - ENTRY_TAIL

            near_extreme = giveback <= max(0.5 * atr, 0.25 * max(mfe, 1e-9))
            exhaustion_now = (
                mfe >= activation
                and at_extreme
                and compression <= COMPRESSION_MAX
                and decelerating
                and near_extreme
            )

            if exhaustion_now:
                p["exhaustion_count"] += 1
            else:
                p["exhaustion_count"] = max(0, p["exhaustion_count"] - 1)

            if p["exhaustion_count"] >= EXHAUSTION_CONFIRM_BARS:
                p["state"] = "EXHAUSTION"
                p["exhaustion_seen"] = True

            # Primary hypothesis: lateralization at an extreme followed by a structural reversal.
            if (
                p["state"] == "EXHAUSTION"
                and structure_break
                and giveback_gate
            ):
                p["state"] = "REVERSAL_CONFIRMED"
                p["pending_exit"] = "EXHAUSTION_REVERSAL"
                continue

            # Sharp reversals can skip a clean lateralization. Require both structure and rank damage.
            if (
                mfe >= activation
                and structure_break
                and giveback_gate
                and rank_bad
            ):
                p["state"] = "REVERSAL_CONFIRMED"
                p["pending_exit"] = "STRUCTURE_RANK_REVERSAL"
                continue

            # Strong rank inversion is allowed only after the move has first produced favorable excursion.
            if (
                mfe >= activation
                and giveback_gate
                and rank_reversed
            ):
                p["state"] = "REVERSAL_CONFIRMED"
                p["pending_exit"] = "RANK_REVERSAL_CONFIRMED"
                continue

        eq = mark_equity(realized, positions, closes)
        peak_equity = max(peak_equity, eq)
        dd = 1.0 - eq / peak_equity if peak_equity > 0 else 1.0
        curve.append({
            "time": t,
            "equity": float(eq),
            "realized_equity": float(realized),
            "drawdown": float(dd),
            "open_positions": int(len(positions)),
            "exhaustion_positions": int(sum(p.get("state") == "EXHAUSTION" for p in positions.values())),
        })
        if eq <= 0:
            break

    final_t = timeline[-1] if len(timeline) else fold_end - pd.Timedelta(minutes=15)
    for s in list(positions):
        px = last_prices.get(s)
        if px is not None:
            close_position(s, final_t, px, "FOLD_END")

    td = pd.DataFrame(trades)
    cd = pd.DataFrame(curve)
    if td.empty:
        return td, cd, {
            "status": "NO_TRADES",
            "portfolio_return": float(realized / INITIAL_EQUITY - 1.0),
        }

    gross_win = float(td.loc[td.pnl_cash > 0, "pnl_cash"].sum())
    gross_loss = float(-td.loc[td.pnl_cash < 0, "pnl_cash"].sum())
    pf = math.inf if gross_loss <= 0 and gross_win > 0 else gross_win / gross_loss if gross_loss > 0 else None
    captures = td.loc[(td.mfe_return > 0) & (td.gross_return > 0), "mfe_capture_ratio"]
    return td, cd, {
        "status": "OK",
        "trades": int(len(td)),
        "long_trades": int((td.side == "LONG").sum()),
        "short_trades": int((td.side == "SHORT").sum()),
        "win_rate": float((td.pnl_cash > 0).mean()),
        "avg_trade_net_return": float(td.net_return.mean()),
        "median_trade_net_return": float(td.net_return.median()),
        "profit_factor_cash": pf,
        "portfolio_return": float(realized / INITIAL_EQUITY - 1.0),
        "ending_equity": float(realized),
        "max_drawdown": float(cd.drawdown.max()) if not cd.empty else 0.0,
        "avg_hold_hours": float(td.hold_hours.mean()),
        "median_hold_hours": float(td.hold_hours.median()),
        "avg_mfe_return": float(td.mfe_return.mean()),
        "avg_mae_return": float(td.mae_return.mean()),
        "mean_positive_mfe_capture": float(captures.mean()) if len(captures) else None,
        "median_positive_mfe_capture": float(captures.median()) if len(captures) else None,
        "exhaustion_seen_share": float(td.exhaustion_seen.mean()),
        "exit_reasons": td.exit_reason.value_counts().to_dict(),
        "symbols": td.symbol.value_counts().to_dict(),
    }


def run(ds, data15):
    fold_rows, pred_all = [], []
    trades_all, curves_all = [], []
    stress_trades_all, stress_curves_all = [], []

    for fi, (t0, t1) in enumerate(base.fold_schedule(ds), start=1):
        tr0 = t0 - pd.Timedelta(hours=base.PURGE_HOURS) - pd.Timedelta(days=base.TRAIN_DAYS)
        tr1 = t0 - pd.Timedelta(hours=base.PURGE_HOURS)
        tr = ds[(ds.index >= tr0) & (ds.index < tr1)]
        te = ds[(ds.index >= t0) & (ds.index < t1)]

        base_row = {
            "fold": fi,
            "train_start": str(tr0),
            "train_end": str(tr1),
            "test_start": str(t0),
            "test_end": str(t1),
            "train_rows": int(len(tr)),
            "test_rows": int(len(te)),
        }
        if len(tr) < 40_000 or te.empty:
            fold_rows.append({**base_row, "status": "SKIP_INSUFFICIENT"})
            continue

        print(f"FOLD {fi} train={len(tr)} test={len(te)} {t0} -> {t1}", flush=True)
        m = base.model()
        m.fit(tr[base.FEATURES], tr.target_rank)
        pred = base.score_test(m, te)
        pred["fold"] = fi
        pred_all.append(pred)

        corr = base.spearman_stats(pred)
        trades, curve, port = simulate_fold_peak_trough(pred, data15, t0, t1, ONE_WAY_COST)
        strades, scurve, sport = simulate_fold_peak_trough(pred, data15, t0, t1, STRESS_ONE_WAY_COST)

        if not trades.empty:
            trades["fold"] = fi
            trades_all.append(trades)
        if not curve.empty:
            curve["fold"] = fi
            curves_all.append(curve)
        if not strades.empty:
            strades["fold"] = fi
            stress_trades_all.append(strades)
        if not scurve.empty:
            scurve["fold"] = fi
            stress_curves_all.append(scurve)

        row = {
            **base_row,
            "status": "OOS",
            "predictions": int(len(pred)),
            "rank_corr_mean": corr["mean"],
            "rank_corr_median": corr["median"],
            "rank_corr_positive_share": corr["positive_share"],
            "portfolio_return": port.get("portfolio_return"),
            "trades": port.get("trades", 0),
            "pf": port.get("profit_factor_cash"),
            "win_rate": port.get("win_rate"),
            "max_drawdown": port.get("max_drawdown"),
            "avg_hold_hours": port.get("avg_hold_hours"),
            "mfe_capture": port.get("mean_positive_mfe_capture"),
            "stress_return": sport.get("portfolio_return"),
            "stress_pf": sport.get("profit_factor_cash"),
        }
        fold_rows.append(row)
        print("FOLD_RESULT " + json.dumps(row, default=str, separators=(",", ":")), flush=True)

    folds = pd.DataFrame(fold_rows)
    pred = pd.concat(pred_all).sort_index() if pred_all else pd.DataFrame()
    trades = pd.concat(trades_all, ignore_index=True) if trades_all else pd.DataFrame()
    curve = pd.concat(curves_all, ignore_index=True) if curves_all else pd.DataFrame()
    strades = pd.concat(stress_trades_all, ignore_index=True) if stress_trades_all else pd.DataFrame()
    scurve = pd.concat(stress_curves_all, ignore_index=True) if stress_curves_all else pd.DataFrame()
    return folds, pred, trades, curve, strades, scurve


def aggregate(folds, trades, strades):
    valid = folds[folds.status == "OOS"].copy()
    if valid.empty:
        return {"folds": 0}

    def compound(col):
        x = pd.to_numeric(valid[col], errors="coerce").dropna()
        return float((1.0 + x).prod() - 1.0) if len(x) else None

    if trades.empty:
        pf = None
    else:
        win = float(trades.loc[trades.pnl_cash > 0, "pnl_cash"].sum())
        loss = float(-trades.loc[trades.pnl_cash < 0, "pnl_cash"].sum())
        pf = math.inf if loss <= 0 and win > 0 else win / loss if loss > 0 else None

    if strades.empty:
        spf = None
    else:
        win = float(strades.loc[strades.pnl_cash > 0, "pnl_cash"].sum())
        loss = float(-strades.loc[strades.pnl_cash < 0, "pnl_cash"].sum())
        spf = math.inf if loss <= 0 and win > 0 else win / loss if loss > 0 else None

    captures = (
        trades.loc[(trades.mfe_return > 0) & (trades.gross_return > 0), "mfe_capture_ratio"]
        if not trades.empty else pd.Series(dtype=float)
    )
    return {
        "folds": int(len(valid)),
        "positive_folds": int((valid.portfolio_return > 0).sum()),
        "positive_fold_share": float((valid.portfolio_return > 0).mean()),
        "mean_fold_return": float(valid.portfolio_return.mean()),
        "median_fold_return": float(valid.portfolio_return.median()),
        "compounded_fold_return": compound("portfolio_return"),
        "mean_rank_corr": float(valid.rank_corr_mean.mean()),
        "median_rank_corr": float(valid.rank_corr_median.median()),
        "rank_corr_positive_fold_share": float((valid.rank_corr_mean > 0).mean()),
        "trades": int(len(trades)),
        "win_rate": float((trades.pnl_cash > 0).mean()) if not trades.empty else None,
        "avg_trade_net_return": float(trades.net_return.mean()) if not trades.empty else None,
        "median_trade_net_return": float(trades.net_return.median()) if not trades.empty else None,
        "profit_factor_cash": pf,
        "max_fold_drawdown": float(valid.max_drawdown.max()),
        "stress_compounded_fold_return": compound("stress_return"),
        "stress_profit_factor_cash": spf,
        "symbols_traded": int(trades.symbol.nunique()) if not trades.empty else 0,
        "avg_hold_hours": float(trades.hold_hours.mean()) if not trades.empty else None,
        "median_hold_hours": float(trades.hold_hours.median()) if not trades.empty else None,
        "avg_mfe_return": float(trades.mfe_return.mean()) if not trades.empty else None,
        "avg_mae_return": float(trades.mae_return.mean()) if not trades.empty else None,
        "mean_positive_mfe_capture": float(captures.mean()) if len(captures) else None,
        "median_positive_mfe_capture": float(captures.median()) if len(captures) else None,
        "exhaustion_seen_share": float(trades.exhaustion_seen.mean()) if not trades.empty else None,
        "exit_reasons": trades.exit_reason.value_counts().to_dict() if not trades.empty else {},
    }


def main():
    requested = [s for s in base.DEV_CANDIDATES if s != "MNTUSDT"]
    data15, data1, data4, skipped = base.load_universe(requested)
    dev = [s for s in requested if s in data15 and s in data1 and s in data4]
    if "BTCUSDT" not in dev or len(dev) < 30:
        raise RuntimeError(f"insufficient universe: {len(dev)}")

    features = base.make_features(data1, data4, dev)
    ds = base.attach_forward_labels(features, data15, dev)
    folds, pred, trades, curve, strades, scurve = run(ds, data15)

    pred_hash = base.prediction_hash(pred)
    if pred_hash != EXPECTED_R13_1_PREDICTION_HASH:
        raise RuntimeError(
            f"Frozen ranking mismatch: expected {EXPECTED_R13_1_PREDICTION_HASH}, got {pred_hash}"
        )

    agg = aggregate(folds, trades, strades)
    result = {
        "version": VERSION,
        "period": [str(base.START), str(base.END_EXCLUSIVE)],
        "development_symbols": dev,
        "skipped": skipped,
        "outer_holdout_preregistered": base.OUTER_HOLDOUT,
        "outer_holdout_opened": False,
        "ranking_source": "Frozen R13.1 OOS ranking; same features/model/folds.",
        "expected_r13_1_prediction_hash": EXPECTED_R13_1_PREDICTION_HASH,
        "prediction_hash": pred_hash,
        "ranking_timeframe": "1h",
        "context_timeframe": "4h",
        "execution_timeframe": "15m",
        "target_horizon_hours": base.TARGET_HOURS,
        "min_hold_hours": MIN_HOLD_HOURS,
        "max_hold_hours": MAX_HOLD_HOURS,
        "ordinary_15m_stop_removed": True,
        "emergency_stop": {
            "atr_mult": EMERGENCY_ATR_MULT,
            "min_frac": EMERGENCY_STOP_MIN,
            "max_frac": EMERGENCY_STOP_MAX,
        },
        "exhaustion_detector": {
            "min_mfe": EXHAUSTION_MIN_MFE,
            "entry_atr_mult": EXHAUSTION_ENTRY_ATR_MULT,
            "compression_max": COMPRESSION_MAX,
            "long_range_pos_min": EXTREME_LONG_MIN,
            "short_range_pos_max": EXTREME_SHORT_MAX,
            "confirm_bars": EXHAUSTION_CONFIRM_BARS,
            "giveback_fraction_of_mfe": GIVEBACK_FRACTION_OF_MFE,
            "giveback_atr_mult": GIVEBACK_ATR_MULT,
            "normal_exit_executes_next_15m_open": True,
        },
        "one_way_cost": ONE_WAY_COST,
        "stress_one_way_cost": STRESS_ONE_WAY_COST,
        "funding_modeled": False,
        "baseline_r13_1": R13_1_BASELINE,
        "aggregate": agg,
        "development_pass": bool(
            agg.get("compounded_fold_return", -1) > 0
            and agg.get("profit_factor_cash") is not None
            and agg.get("profit_factor_cash") >= 1.15
            and agg.get("positive_fold_share", 0) >= 0.55
            and agg.get("max_fold_drawdown", 1) < 0.10
            and agg.get("stress_compounded_fold_return", -1) > 0
            and agg.get("stress_profit_factor_cash") is not None
            and agg.get("stress_profit_factor_cash") >= 1.05
            and agg.get("symbols_traded", 0) >= 12
        ),
        "outer_holdout_reason": "SHIB/OP/ARB remain unopened. R13.2 is development-only.",
        "methodology_note": (
            "R13.2 changes only exit/risk management relative to R13.1. "
            "Ranking predictions are required to reproduce the exact R13.1 OOS hash. "
            "Normal exits are triggered only from completed 15m bars and execute at the next 15m open."
        ),
    }

    folds.to_csv("r13_2_folds.csv", index=False)
    if not pred.empty:
        pred.reset_index().to_parquet("r13_2_predictions.parquet", index=False, compression="zstd")
    if not trades.empty:
        trades.to_csv("r13_2_trades.csv", index=False)
    if not curve.empty:
        curve.to_parquet("r13_2_equity_curve.parquet", index=False, compression="zstd")
    if not strades.empty:
        strades.to_csv("r13_2_trades_stress.csv", index=False)
    if not scurve.empty:
        scurve.to_parquet("r13_2_equity_curve_stress.parquet", index=False, compression="zstd")

    Path("r13_2_result.json").write_text(json.dumps(result, indent=2, default=str))
    Path("r13_2_report.md").write_text(
        "# V10 R13.2 Horizon-Aligned Peak/Trough Engine\n\n"
        "Frozen R13.1 OOS ranking -> 15m exhaustion / peak-trough confirmation -> next-bar exit.\n\n"
        + json.dumps(result, indent=2, default=str)
        + "\n"
    )
    print("===R13_2_RESULT_JSON===")
    print(json.dumps(result, separators=(",", ":"), default=str))
    print("===END_R13_2_RESULT_JSON===")


if __name__ == "__main__":
    main()
