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
from r13_2_peak_trough import run_r13_2_peak_trough as r2

VERSION = "V10-R13.4-RELATIVE-RISK-TIME-DECAY"
EXPECTED_PREDICTION_HASH = r2.EXPECTED_R13_1_PREDICTION_HASH

DATA_ROOT = Path(os.environ.get("R13_DATA_ROOT", "../r13_1_dataset"))
FROZEN_RESULTS = Path(os.environ.get("R13_FROZEN_RESULTS", "../frozen_r13_2"))

ENTRY_TAIL = base.ENTRY_TAIL
HOLD_TAIL = base.HOLD_TAIL
MIN_SLOTS = base.MIN_SLOTS
ONE_WAY_COST = base.ONE_WAY_COST
STRESS_ONE_WAY_COST = base.STRESS_ONE_WAY_COST
INITIAL_EQUITY = base.INITIAL_EQUITY

# Preserve R13.2 structural exit logic.
MIN_HOLD_HOURS = r2.MIN_HOLD_HOURS
MAX_HOLD_HOURS = r2.MAX_HOLD_HOURS
EXIT_COOLDOWN_HOURS = r2.EXIT_COOLDOWN_HOURS
EMERGENCY_ATR_MULT = r2.EMERGENCY_ATR_MULT
EMERGENCY_STOP_MIN = r2.EMERGENCY_STOP_MIN
EMERGENCY_STOP_MAX = r2.EMERGENCY_STOP_MAX
EXHAUSTION_MIN_MFE = r2.EXHAUSTION_MIN_MFE
EXHAUSTION_ENTRY_ATR_MULT = r2.EXHAUSTION_ENTRY_ATR_MULT
COMPRESSION_MAX = r2.COMPRESSION_MAX
EXTREME_LONG_MIN = r2.EXTREME_LONG_MIN
EXTREME_SHORT_MAX = r2.EXTREME_SHORT_MAX
EXHAUSTION_CONFIRM_BARS = r2.EXHAUSTION_CONFIRM_BARS
GIVEBACK_FRACTION_OF_MFE = r2.GIVEBACK_FRACTION_OF_MFE
GIVEBACK_ATR_MULT = r2.GIVEBACK_ATR_MULT

# R13.4: less aggressive profit lock + earlier thesis invalidation.
# Profit lock only protects mature moves; it should not cut the trend too early.
PROFIT_LOCK_MIN_MFE = 0.040
PROFIT_LOCK_ENTRY_ATR_MULT = 4.0
PROFIT_LOCK_TRAIL_ATR_MULT = 2.5
PROFIT_LOCK_MAX_GIVEBACK_FRAC = 0.60
PROFIT_LOCK_MIN_AGE_HOURS = 12

# Relative-risk invalidation. A losing asset is not closed merely because price is red:
# rank/structure must fail, and if the book spread is still positive we require full rank reversal.
REL_RISK_MIN_AGE_HOURS = 3
REL_RISK_MIN_ADVERSE = 0.030
REL_RISK_ENTRY_ATR_MULT = 3.0
REL_RISK_CONFIRM_BARS = 4

# Hard catastrophe cap is tighter than R13.2/3, but remains wide enough for 15m noise.
EMERGENCY_ATR_MULT = 5.0
EMERGENCY_STOP_MIN = 0.07
EMERGENCY_STOP_MAX = 0.10

# Time decay: after 48h a damaged thesis needs more evidence to remain open.
TIME_DECAY_START_HOURS = 48
TIME_DECAY_STRICT_HOURS = 60
TIME_DECAY_CONFIRM_BARS = 4

# Volatility-parity sizing inside each side.
VOL_WEIGHT_MIN = 0.60
VOL_WEIGHT_MAX = 1.40

# Portfolio circuit breaker pauses new entries; it never force-closes winners.
CIRCUIT_DD_SOFT = 0.08
CIRCUIT_DD_HARD = 0.10
CIRCUIT_SOFT_PAUSE_HOURS = 12
CIRCUIT_HARD_PAUSE_HOURS = 24

R13_3_BASELINE = {
    "trades": 7336,
    "win_rate": 0.6534896401308615,
    "avg_trade_net_return": -0.002940580078625241,
    "median_trade_net_return": 0.01107764439262208,
    "profit_factor_cash": 0.841037626985233,
    "positive_fold_share": 0.05263157894736842,
    "compounded_fold_return": -0.8080870978398029,
    "max_fold_drawdown": 0.31566079881632114,
    "avg_hold_hours": 23.581209105779717,
    "mean_positive_mfe_capture": 0.5286181905061068,
    "emergency_stops": 1184,
}


def load_frozen_predictions():
    p = FROZEN_RESULTS / "r13_2_predictions.parquet"
    f = FROZEN_RESULTS / "r13_2_folds.csv"
    if not p.exists() or not f.exists():
        raise FileNotFoundError(f"Frozen predictions/folds missing in {FROZEN_RESULTS}")
    pred = pd.read_parquet(p)
    time_col = "time" if "time" in pred.columns else pred.columns[0]
    pred[time_col] = pd.to_datetime(pred[time_col], utc=True)
    pred = pred.rename(columns={time_col: "time"}).set_index("time").sort_index()
    folds = pd.read_csv(f)
    return pred, folds


def load_data15(symbols):
    old_root = base.DATA_ROOT
    base.DATA_ROOT = DATA_ROOT
    try:
        d15, d1, d4, skipped = base.load_universe(symbols)
    finally:
        base.DATA_ROOT = old_root
    return d15, d1, d4, skipped


def mark_equity(realized_equity, positions, prices):
    u = 0.0
    for s, p in positions.items():
        px = prices.get(s)
        if px is None or not np.isfinite(px):
            continue
        u += p["notional"] * p["side"] * (px / p["entry_price"] - 1.0)
    return realized_equity + u


def simulate_fold(pred, data15, fold_start, fold_end, one_way_cost):
    if pred.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "NO_PREDICTIONS"}

    syms = sorted(pred.symbol.unique())
    bars = {
        s: r2.add_exec_features(
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
    entry_pause_until = pd.Timestamp.min.tz_localize("UTC")

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
            "profit_lock_activated": bool(p.get("profit_lock_activated", False)),
            "profit_lock_floor_return": p.get("profit_lock_floor_return"),
            "relative_risk_triggered": bool(p.get("relative_risk_triggered", False)),
            "exit_book_edge": p.get("last_book_edge"),
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

        # Normal exits confirmed on prior completed 15m bar.
        for s in list(positions):
            p = positions[s]
            reason = p.get("pending_exit")
            if reason and s in opens:
                close_position(s, t, opens[s], reason)

        # Hourly ranking update and unchanged R13.1 entry logic.
        if t in signal_at:
            q = signal_at[t]
            pct = q.set_index("symbol").pred_pct.to_dict()
            latest_rank_pct.update(pct)
            n = len(q)
            k = max(MIN_SLOTS, int(math.floor(n * ENTRY_TAIL)))
            long_entry = list(
                q[q.pred_pct >= 1.0 - ENTRY_TAIL]
                .sort_values("pred_rank", ascending=False).symbol
            )[:k]
            short_entry = list(
                q[q.pred_pct <= ENTRY_TAIL]
                .sort_values("pred_rank", ascending=True).symbol
            )[:k]

            open_equity = mark_equity(realized, positions, opens)
            if open_equity <= 0:
                break
            pre_entry_dd = 1.0 - open_equity / peak_equity if peak_equity > 0 else 1.0
            if pre_entry_dd >= CIRCUIT_DD_HARD:
                entry_pause_until = max(entry_pause_until, t + pd.Timedelta(hours=CIRCUIT_HARD_PAUSE_HOURS))
            elif pre_entry_dd >= CIRCUIT_DD_SOFT:
                entry_pause_until = max(entry_pause_until, t + pd.Timedelta(hours=CIRCUIT_SOFT_PAUSE_HOURS))
            if t < entry_pause_until:
                long_entry = []
                short_entry = []

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
                valid_atrs = [float(rows[x].atr_pct_prev) for x in new_syms if np.isfinite(rows[x].atr_pct_prev)]
                median_atr = float(np.median(valid_atrs)) if valid_atrs else np.nan
                for s in new_syms:
                    if capacity <= 1e-9:
                        break
                    entry_atr = float(rows[s].atr_pct_prev)
                    risk_factor = 1.0
                    if np.isfinite(median_atr) and entry_atr > 1e-12:
                        risk_factor = float(np.clip(median_atr / entry_atr, VOL_WEIGHT_MIN, VOL_WEIGHT_MAX))
                    notional = min(target_each * risk_factor, capacity)
                    if notional <= 1e-9:
                        continue
                    emergency_frac = float(np.clip(
                        EMERGENCY_ATR_MULT * entry_atr,
                        EMERGENCY_STOP_MIN,
                        EMERGENCY_STOP_MAX,
                    ))
                    entry_price = float(opens[s])
                    entry_cost = notional * one_way_cost
                    realized -= entry_cost
                    positions[s] = {
                        "symbol": s,
                        "side": side,
                        "entry_time": t,
                        "entry_price": entry_price,
                        "notional": float(notional),
                        "entry_cost": float(entry_cost),
                        "entry_atr_pct": entry_atr,
                        "emergency_stop_frac": emergency_frac,
                        "emergency_stop_price": float(
                            entry_price * (1.0 - emergency_frac if side > 0 else 1.0 + emergency_frac)
                        ),
                        "best_price": entry_price,
                        "worst_price": entry_price,
                        "mfe_return": 0.0,
                        "mae_return": 0.0,
                        "state": "TRENDING",
                        "exhaustion_count": 0,
                        "exhaustion_seen": False,
                        "pending_exit": None,
                        "profit_lock_activated": False,
                        "profit_lock_floor_return": None,
                        "profit_lock_price": None,
                        "relative_fail_bars": 0,
                        "time_decay_bars": 0,
                        "relative_risk_triggered": False,
                        "last_book_edge": None,
                    }
                    capacity -= notional

        # Protective stops use only levels known before the current bar.
        for s in list(positions):
            if s not in rows:
                continue
            p = positions[s]
            side = p["side"]

            # Profit-lock stop has precedence once activated.
            lp = p.get("profit_lock_price")
            if lp is not None and np.isfinite(lp):
                if side > 0:
                    if opens[s] <= lp:
                        close_position(s, t, opens[s], "PROFIT_LOCK_GAP")
                        continue
                    if lows[s] <= lp:
                        close_position(s, t, lp, "PROFIT_LOCK")
                        continue
                else:
                    if opens[s] >= lp:
                        close_position(s, t, opens[s], "PROFIT_LOCK_GAP")
                        continue
                    if highs[s] >= lp:
                        close_position(s, t, lp, "PROFIT_LOCK")
                        continue

            # Catastrophic stop remains for trades that never establish a favorable move.
            sp = p["emergency_stop_price"]
            if side > 0:
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

        # Completed-bar state update.
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
            atr = float(r.atr_pct) if np.isfinite(r.atr_pct) else p["entry_atr_pct"]
            mfe = float(p["mfe_return"])

            # Book-relative edge: average side-adjusted return of all open positions.
            current_book = []
            for osym, op in positions.items():
                px = closes.get(osym)
                if px is None or not np.isfinite(px):
                    continue
                current_book.append(op["side"] * (px / op["entry_price"] - 1.0))
            book_edge = float(np.mean(current_book)) if current_book else 0.0
            p["last_book_edge"] = book_edge

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
                structure_break = closes[s] < low_prev or (closes[s] < ema20 and ema_slope < 0)
                rank_bad = latest_rank_pct.get(s, 1.0) < 1.0 - HOLD_TAIL
                rank_reversed = latest_rank_pct.get(s, 1.0) <= ENTRY_TAIL
            else:
                at_extreme = range_pos <= EXTREME_SHORT_MAX
                decelerating = (-ret1h) <= atr
                structure_break = closes[s] > high_prev or (closes[s] > ema20 and ema_slope > 0)
                rank_bad = latest_rank_pct.get(s, 0.0) > HOLD_TAIL
                rank_reversed = latest_rank_pct.get(s, 0.0) >= 1.0 - ENTRY_TAIL

            # Relative-risk invalidation: require price damage + structure/rank damage.
            adverse_gate = max(REL_RISK_MIN_ADVERSE, REL_RISK_ENTRY_ATR_MULT * p["entry_atr_pct"])
            relative_rank_fail = rank_reversed if book_edge > 0 else rank_bad
            relative_fail = (
                age_h >= REL_RISK_MIN_AGE_HOURS
                and gross_close <= -adverse_gate
                and structure_break
                and relative_rank_fail
            )
            if relative_fail:
                p["relative_fail_bars"] += 1
                p["relative_risk_triggered"] = True
            else:
                p["relative_fail_bars"] = max(0, p["relative_fail_bars"] - 1)
            if p["relative_fail_bars"] >= REL_RISK_CONFIRM_BARS:
                p["state"] = "THESIS_INVALID"
                p["pending_exit"] = "RELATIVE_INVALIDATION"
                continue

            # R13.4 profit lock: activate only on mature favorable moves.
            lock_activation = max(PROFIT_LOCK_MIN_MFE, PROFIT_LOCK_ENTRY_ATR_MULT * p["entry_atr_pct"])
            if age_h >= PROFIT_LOCK_MIN_AGE_HOURS and mfe >= lock_activation:
                allowed_giveback = max(
                    PROFIT_LOCK_TRAIL_ATR_MULT * atr,
                    PROFIT_LOCK_MAX_GIVEBACK_FRAC * mfe,
                )
                floor_ret = max(2.0 * one_way_cost, mfe - allowed_giveback)
                old_floor = p.get("profit_lock_floor_return")
                if old_floor is None or floor_ret > old_floor:
                    p["profit_lock_floor_return"] = float(floor_ret)
                    if side > 0:
                        p["profit_lock_price"] = float(entry * (1.0 + floor_ret))
                    else:
                        p["profit_lock_price"] = float(entry * (1.0 - floor_ret))
                p["profit_lock_activated"] = True

            if age_h >= MAX_HOLD_HOURS:
                p["pending_exit"] = "MAX_HOLD"
                continue

            # Time decay after 48h: a damaged ranking/structure is no longer given unlimited room.
            td_fail = False
            if age_h >= TIME_DECAY_STRICT_HOURS:
                td_fail = rank_bad
            elif age_h >= TIME_DECAY_START_HOURS:
                td_fail = rank_bad and structure_break
            if td_fail:
                p["time_decay_bars"] += 1
            else:
                p["time_decay_bars"] = max(0, p["time_decay_bars"] - 1)
            if p["time_decay_bars"] >= TIME_DECAY_CONFIRM_BARS:
                p["state"] = "DECAYED"
                p["pending_exit"] = "TIME_DECAY"
                continue

            # Structural peak/trough logic remains from R13.2 after 12h.
            if age_h < MIN_HOLD_HOURS:
                continue

            activation = max(EXHAUSTION_MIN_MFE, EXHAUSTION_ENTRY_ATR_MULT * p["entry_atr_pct"])
            giveback = max(0.0, mfe - gross_close)
            giveback_gate = (
                mfe > 0
                and giveback >= max(GIVEBACK_ATR_MULT * atr, GIVEBACK_FRACTION_OF_MFE * mfe)
            )
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

            if p["state"] == "EXHAUSTION" and structure_break and giveback_gate:
                p["state"] = "REVERSAL_CONFIRMED"
                p["pending_exit"] = "EXHAUSTION_REVERSAL"
                continue

            if mfe >= activation and structure_break and giveback_gate and rank_bad:
                p["state"] = "REVERSAL_CONFIRMED"
                p["pending_exit"] = "STRUCTURE_RANK_REVERSAL"
                continue

            if mfe >= activation and giveback_gate and rank_reversed:
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
            "profit_lock_positions": int(sum(bool(p.get("profit_lock_activated")) for p in positions.values())),
            "entry_paused": bool(t < entry_pause_until),
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
        return td, cd, {"status": "NO_TRADES", "portfolio_return": float(realized / INITIAL_EQUITY - 1.0)}

    gross_win = float(td.loc[td.pnl_cash > 0, "pnl_cash"].sum())
    gross_loss = float(-td.loc[td.pnl_cash < 0, "pnl_cash"].sum())
    pf = math.inf if gross_loss <= 0 and gross_win > 0 else gross_win / gross_loss if gross_loss > 0 else None
    captures = td.loc[(td.mfe_return > 0) & (td.gross_return > 0), "mfe_capture_ratio"]
    return td, cd, {
        "status": "OK",
        "trades": int(len(td)),
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
        "profit_lock_share": float(td.profit_lock_activated.mean()),
        "exit_reasons": td.exit_reason.value_counts().to_dict(),
    }


def aggregate(folds, trades, strades):
    valid = folds[folds.status == "OOS"].copy()
    if valid.empty:
        return {"folds": 0}

    def compound(col):
        x = pd.to_numeric(valid[col], errors="coerce").dropna()
        return float((1.0 + x).prod() - 1.0) if len(x) else None

    def pf_for(d):
        if d.empty:
            return None
        win = float(d.loc[d.pnl_cash > 0, "pnl_cash"].sum())
        loss = float(-d.loc[d.pnl_cash < 0, "pnl_cash"].sum())
        return math.inf if loss <= 0 and win > 0 else win / loss if loss > 0 else None

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
        "trades": int(len(trades)),
        "win_rate": float((trades.pnl_cash > 0).mean()) if not trades.empty else None,
        "avg_trade_net_return": float(trades.net_return.mean()) if not trades.empty else None,
        "median_trade_net_return": float(trades.net_return.median()) if not trades.empty else None,
        "profit_factor_cash": pf_for(trades),
        "max_fold_drawdown": float(valid.max_drawdown.max()),
        "stress_compounded_fold_return": compound("stress_return"),
        "stress_profit_factor_cash": pf_for(strades),
        "symbols_traded": int(trades.symbol.nunique()) if not trades.empty else 0,
        "avg_hold_hours": float(trades.hold_hours.mean()) if not trades.empty else None,
        "median_hold_hours": float(trades.hold_hours.median()) if not trades.empty else None,
        "avg_mfe_return": float(trades.mfe_return.mean()) if not trades.empty else None,
        "avg_mae_return": float(trades.mae_return.mean()) if not trades.empty else None,
        "mean_positive_mfe_capture": float(captures.mean()) if len(captures) else None,
        "median_positive_mfe_capture": float(captures.median()) if len(captures) else None,
        "profit_lock_activated_share": float(trades.profit_lock_activated.mean()) if not trades.empty else None,
        "relative_risk_triggered_share": float(trades.relative_risk_triggered.mean()) if not trades.empty else None,
        "exit_reasons": trades.exit_reason.value_counts().to_dict() if not trades.empty else {},
    }


def main():
    pred, old_folds = load_frozen_predictions()
    pred_hash = base.prediction_hash(pred)
    if pred_hash != EXPECTED_PREDICTION_HASH:
        raise RuntimeError(f"Frozen prediction hash mismatch: {pred_hash}")

    requested = [s for s in base.DEV_CANDIDATES if s != "MNTUSDT"]
    data15, data1, data4, skipped = load_data15(requested)
    dev = [s for s in requested if s in data15 and s in data1 and s in data4]
    if len(dev) < 30:
        raise RuntimeError(f"insufficient universe: {len(dev)}")

    fold_rows = []
    trades_all, curves_all = [], []
    strades_all, scurves_all = [], []

    for _, fr in old_folds[old_folds.status == "OOS"].iterrows():
        fi = int(fr["fold"])
        t0 = pd.Timestamp(fr["test_start"])
        t1 = pd.Timestamp(fr["test_end"])
        p = pred[pred.fold == fi].copy()

        print(f"FOLD {fi} frozen_predictions={len(p)} {t0}->{t1}", flush=True)
        td, cd, port = simulate_fold(p, data15, t0, t1, ONE_WAY_COST)
        sd, scd, sport = simulate_fold(p, data15, t0, t1, STRESS_ONE_WAY_COST)

        if not td.empty:
            td["fold"] = fi
            trades_all.append(td)
        if not cd.empty:
            cd["fold"] = fi
            curves_all.append(cd)
        if not sd.empty:
            sd["fold"] = fi
            strades_all.append(sd)
        if not scd.empty:
            scd["fold"] = fi
            scurves_all.append(scd)

        row = {
            "fold": fi,
            "test_start": str(t0),
            "test_end": str(t1),
            "status": "OOS",
            "predictions": int(len(p)),
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
        print("FOLD_RESULT " + json.dumps(row, separators=(",",":"), default=str), flush=True)

    folds = pd.DataFrame(fold_rows)
    trades = pd.concat(trades_all, ignore_index=True) if trades_all else pd.DataFrame()
    curves = pd.concat(curves_all, ignore_index=True) if curves_all else pd.DataFrame()
    strades = pd.concat(strades_all, ignore_index=True) if strades_all else pd.DataFrame()
    scurves = pd.concat(scurves_all, ignore_index=True) if scurves_all else pd.DataFrame()
    agg = aggregate(folds, trades, strades)

    result = {
        "version": VERSION,
        "period": [str(base.START), str(base.END_EXCLUSIVE)],
        "prediction_source": "Frozen R13.2 artifact, itself identical to R13.1 OOS ranking.",
        "prediction_hash": pred_hash,
        "outer_holdout_preregistered": base.OUTER_HOLDOUT,
        "outer_holdout_opened": False,
        "ranking_timeframe": "1h",
        "context_timeframe": "4h",
        "execution_timeframe": "15m",
        "profit_lock": {
            "activation_min_mfe": PROFIT_LOCK_MIN_MFE,
            "activation_entry_atr_mult": PROFIT_LOCK_ENTRY_ATR_MULT,
            "trail_atr_mult": PROFIT_LOCK_TRAIL_ATR_MULT,
            "max_giveback_fraction_of_mfe": PROFIT_LOCK_MAX_GIVEBACK_FRAC,
            "min_age_hours": PROFIT_LOCK_MIN_AGE_HOURS,
            "minimum_locked_gross_return": "2x one-way cost",
            "uses_only_prior_completed_15m_information": True,
        },
        "relative_risk": {
            "min_age_hours": REL_RISK_MIN_AGE_HOURS,
            "min_adverse": REL_RISK_MIN_ADVERSE,
            "entry_atr_mult": REL_RISK_ENTRY_ATR_MULT,
            "confirm_bars": REL_RISK_CONFIRM_BARS,
            "book_positive_requires_rank_reversal": True,
        },
        "hard_catastrophe_stop": {
            "atr_mult": EMERGENCY_ATR_MULT,
            "min_frac": EMERGENCY_STOP_MIN,
            "max_frac": EMERGENCY_STOP_MAX,
        },
        "time_decay": {
            "start_hours": TIME_DECAY_START_HOURS,
            "strict_hours": TIME_DECAY_STRICT_HOURS,
            "confirm_bars": TIME_DECAY_CONFIRM_BARS,
        },
        "volatility_sizing": {
            "min_factor": VOL_WEIGHT_MIN,
            "max_factor": VOL_WEIGHT_MAX,
        },
        "circuit_breaker": {
            "soft_dd": CIRCUIT_DD_SOFT,
            "hard_dd": CIRCUIT_DD_HARD,
            "soft_pause_hours": CIRCUIT_SOFT_PAUSE_HOURS,
            "hard_pause_hours": CIRCUIT_HARD_PAUSE_HOURS,
        },
        "r13_3_baseline": R13_3_BASELINE,
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
        "outer_holdout_reason": "SHIB/OP/ARB remain unopened. R13.4 is development-only.",
    }

    folds.to_csv("r13_4_folds.csv", index=False)
    if not trades.empty:
        trades.to_csv("r13_4_trades.csv", index=False)
    if not curves.empty:
        curves.to_parquet("r13_4_equity_curve.parquet", index=False, compression="zstd")
    if not strades.empty:
        strades.to_csv("r13_4_trades_stress.csv", index=False)
    if not scurves.empty:
        scurves.to_parquet("r13_4_equity_curve_stress.parquet", index=False, compression="zstd")
    Path("r13_4_result.json").write_text(json.dumps(result, indent=2, default=str))
    Path("r13_4_report.md").write_text(
        "# V10 R13.4 Relative Risk + Time Decay\n\n"
        "Frozen R13.1/R13.2 OOS ranking; relative-risk invalidation, time decay, volatility sizing and circuit breaker change.\n\n"
        + json.dumps(result, indent=2, default=str) + "\n"
    )
    print("===R13_4_RESULT_JSON===")
    print(json.dumps(result, separators=(",",":"), default=str))
    print("===END_R13_4_RESULT_JSON===")


if __name__ == "__main__":
    main()