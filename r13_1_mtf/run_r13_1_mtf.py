from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "r12_2_code"))

from r11_multitimeframe_rank_engine import (
    R11Config, R11_FEATURES, build_features_tf, config_for_timeframe
)
from r8_setup_experts_engine import _add_market_context
from r9_2_cross_sectional_rank_engine import _add_extra_ranks
from run_r8_real import DEV_CANDIDATES, OUTER_HOLDOUT

VERSION = "V10-R13.1-MTF-1H-RANK-4H-CONTEXT-15M-EXEC"
DATA_ROOT = Path(os.environ.get("R13_DATA_ROOT", "V10_R13_1_BINANCE_SPOT_MTF_DATASET"))
START = pd.Timestamp("2024-01-01T00:00:00Z")
END_EXCLUSIVE = pd.Timestamp("2026-09-21T00:00:00Z")

TRAIN_DAYS = 360
TEST_DAYS = 30
PURGE_HOURS = 96
TARGET_HOURS = 72
MIN_GROUP_ASSETS = 12
MIN_QUOTE_VOLUME_24H = 10_000_000.0
MIN_MOVE_TO_COST = 3.0

ENTRY_TAIL = 0.15
HOLD_TAIL = 0.35
MIN_SLOTS = 3
MAX_HOLD_HOURS = 72

STOP_ATR_MULT_15M = 2.5
MIN_STOP_FRAC = 0.008
MAX_STOP_FRAC = 0.030

INITIAL_EQUITY = 10_000.0
ONE_WAY_COST = 0.0016
STRESS_ONE_WAY_COST = 0.0021

CTX4_BASE = [
    "ret_24h","ret_72h","rel_btc_24h","rel_btc_72h",
    "atr_pct","volatility_24h","ema20_dist","ema50_dist","ema200_dist",
    "ema50_slope_24h","rsi14","adx14","bb_width","vol_z_24h",
    "range_overlap_72h","range_pos_72h","breakout_48h",
    "btc_ret_24h","btc_ema200_dist","btc_adx14",
    "market_breadth_ema200","market_breadth_ret24_pos",
    "market_risk_on","market_range","market_recovery",
    "cs_ret24_rank","cs_ret72_rank","cs_ema200_rank","cs_atr_rank",
    "cs_volatility_rank","cs_rsi_rank"
]
CTX4_FEATURES = [f"ctx4_{x}" for x in CTX4_BASE]
FEATURES = R11_FEATURES + CTX4_FEATURES


def cfg_1h() -> R11Config:
    return R11Config(
        bar_interval="1h",
        decision_hours=tuple(range(24)),
        rank_horizon_bars=TARGET_HOURS,
        train_days=TRAIN_DAYS,
        test_days=TEST_DAYS,
        purge_bars=PURGE_HOURS,
        min_training_rows=40_000,
        min_group_assets=MIN_GROUP_ASSETS,
        min_quote_volume_24h=MIN_QUOTE_VOLUME_24H,
        min_move_to_cost=MIN_MOVE_TO_COST,
        rank_min_leaf=160,
        corr_lookback_bars=72,
    )


def load_parquet(symbol: str, tf: str, close_boundary: bool) -> pd.DataFrame:
    p = DATA_ROOT / tf / f"{symbol}.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    d = pd.read_parquet(p)
    d["open_time"] = pd.to_datetime(d["open_time"], unit="ms", utc=True)
    idx = d["open_time"]
    if close_boundary:
        idx = idx + pd.Timedelta(tf)
    d.index = pd.DatetimeIndex(idx, name="time")
    cols = ["open","high","low","close","volume","quote_volume"]
    q = d[cols].apply(pd.to_numeric, errors="coerce").sort_index()
    return q[~q.index.duplicated(keep="last")]


def load_universe(symbols):
    data15, data1, data4, skipped = {}, {}, {}, {}
    for s in symbols:
        try:
            data15[s] = load_parquet(s, "15m", close_boundary=False)
            data1[s] = load_parquet(s, "1h", close_boundary=True)
            data4[s] = load_parquet(s, "4h", close_boundary=True)
            print(f"DATA {s} 15m={len(data15[s])} 1h={len(data1[s])} 4h={len(data4[s])}", flush=True)
        except Exception as e:
            skipped[s] = f"{type(e).__name__}:{e}"
            print(f"SKIP {s} {skipped[s]}", flush=True)
    return data15, data1, data4, skipped


def add_atr15(d: pd.DataFrame) -> pd.DataFrame:
    q = d.copy()
    prev = q.close.shift(1)
    tr = pd.concat([(q.high-q.low), (q.high-prev).abs(), (q.low-prev).abs()], axis=1).max(axis=1)
    q["atr14"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    q["atr_pct_prev"] = (q.atr14 / q.close).shift(1)
    return q


def make_features(data1, data4, dev):
    c1 = cfg_1h()
    c4 = config_for_timeframe("4h")
    btc1, btc4 = data1["BTCUSDT"], data4["BTCUSDT"]

    print("Building 1h features...", flush=True)
    f1 = {s: build_features_tf(s, d, btc1, c1) for s, d in data1.items()}
    f1 = _add_market_context(f1, dev)
    f1 = _add_extra_ranks(f1, dev)

    print("Building 4h context...", flush=True)
    f4 = {s: build_features_tf(s, d, btc4, c4) for s, d in data4.items()}
    f4 = _add_market_context(f4, dev)
    f4 = _add_extra_ranks(f4, dev)

    out = {}
    for s in dev:
        a = f1[s].copy()
        b = f4[s].reindex(a.index, method="ffill")
        for col in CTX4_BASE:
            a[f"ctx4_{col}"] = b[col]
        out[s] = a
    return out


def attach_forward_labels(features, data15, dev):
    chunks = []
    for s in dev:
        g = features[s].copy()
        px = data15[s].open
        entry_idx = g.index + pd.Timedelta(minutes=15)
        exit_idx = entry_idx + pd.Timedelta(hours=TARGET_HOURS)
        entry = px.reindex(entry_idx).to_numpy(dtype=float)
        exitp = px.reindex(exit_idx).to_numpy(dtype=float)
        g["target_entry_time"] = entry_idx
        g["target_exit_time"] = exit_idx
        g["forward_return"] = exitp / entry - 1.0
        g["eligible"] = (
            (g.quote_volume_24h >= MIN_QUOTE_VOLUME_24H)
            & (g.move_to_cost >= MIN_MOVE_TO_COST)
        )
        g = g[g.eligible]
        chunks.append(g)

    x = pd.concat(chunks).sort_index()
    x = x.dropna(subset=FEATURES + ["forward_return"])

    counts = x.groupby(level=0).size()
    x = x[x.index.to_series().map(counts).fillna(0).to_numpy() >= MIN_GROUP_ASSETS].copy()
    med = x.groupby(level=0).forward_return.median()
    x["universe_median_return"] = x.index.to_series().map(med)
    x["relative_forward_return"] = x.forward_return - x.universe_median_return
    x["target_rank"] = x.groupby(level=0).relative_forward_return.rank(pct=True, method="average")
    x = x.dropna(subset=["target_rank"])
    print(f"RANK_DATASET rows={len(x)} times={x.index.nunique()} symbols={x.symbol.nunique()}", flush=True)
    return x


def model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.04,
        max_iter=180,
        max_leaf_nodes=15,
        min_samples_leaf=160,
        l2_regularization=8.0,
        random_state=73117,
    )


def prediction_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return hashlib.sha256(b"").hexdigest()
    q = df.reset_index()[["time","symbol","pred_rank","pred_pct","target_rank","forward_return"]]
    q["time"] = pd.to_datetime(q.time, utc=True).astype(str)
    q = q.sort_values(["time","symbol"])
    return hashlib.sha256(q.to_csv(index=False, float_format="%.12g").encode()).hexdigest()


def score_test(m, te: pd.DataFrame) -> pd.DataFrame:
    z = te[["symbol","target_rank","forward_return","relative_forward_return"]].copy()
    z["pred_rank"] = m.predict(te[FEATURES])
    parts = []
    for ts, g in z.groupby(level=0, sort=True):
        q = g.copy()
        q["pred_pct"] = q.pred_rank.rank(pct=True, method="average")
        parts.append(q)
    return pd.concat(parts).sort_index() if parts else pd.DataFrame()


def spearman_stats(pred: pd.DataFrame):
    vals = []
    for _, g in pred.groupby(level=0):
        if len(g) >= 3:
            c = g[["pred_rank","target_rank"]].corr(method="spearman").iloc[0,1]
            if np.isfinite(c):
                vals.append(float(c))
    return {
        "mean": float(np.mean(vals)) if vals else None,
        "median": float(np.median(vals)) if vals else None,
        "positive_share": float(np.mean(np.asarray(vals) > 0)) if vals else None,
        "n_timestamps": int(len(vals)),
    }


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
        return pd.DataFrame(), pd.DataFrame(), {"status":"NO_PREDICTIONS"}

    syms = sorted(pred.symbol.unique())
    bars = {s: add_atr15(data15[s].loc[
        (data15[s].index >= fold_start - pd.Timedelta(hours=1))
        & (data15[s].index < fold_end + pd.Timedelta(minutes=15))
    ].copy()) for s in syms}

    timeline = pd.date_range(fold_start, fold_end - pd.Timedelta(minutes=15), freq="15min", tz="UTC")
    signal_at = {}
    for ts, g in pred.groupby(level=0, sort=True):
        et = ts + pd.Timedelta(minutes=15)
        if et < fold_start or et >= fold_end:
            continue
        signal_at[et] = g.sort_values("pred_rank", ascending=False).copy()

    realized = INITIAL_EQUITY
    positions = {}
    trades = []
    curve = []
    peak = INITIAL_EQUITY

    def close_position(s, when, price, reason):
        nonlocal realized
        p = positions.pop(s)
        gross_ret = p["side"] * (price / p["entry_price"] - 1.0)
        pnl_gross = p["notional"] * gross_ret
        exit_cost = p["notional"] * one_way_cost
        realized += pnl_gross - exit_cost
        net_ret = gross_ret - 2.0 * one_way_cost
        trades.append({
            "symbol": s,
            "side": "LONG" if p["side"] > 0 else "SHORT",
            "entry_time": p["entry_time"],
            "exit_time": when,
            "entry_price": p["entry_price"],
            "exit_price": float(price),
            "notional": p["notional"],
            "gross_return": gross_ret,
            "net_return": net_ret,
            "pnl_cash": pnl_gross - p["entry_cost"] - exit_cost,
            "hold_hours": float((when - p["entry_time"]) / pd.Timedelta(hours=1)),
            "stop_frac": p["stop_frac"],
            "exit_reason": reason,
        })

    last_prices = {}
    for t in timeline:
        opens, highs, lows, closes, atrs = {}, {}, {}, {}, {}
        for s in syms:
            if t not in bars[s].index:
                continue
            r = bars[s].loc[t]
            opens[s] = float(r.open); highs[s] = float(r.high); lows[s] = float(r.low); closes[s] = float(r.close)
            atrs[s] = float(r.atr_pct_prev) if np.isfinite(r.atr_pct_prev) else np.nan
            last_prices[s] = float(r.close)

        # Scheduled hourly rebalance executes at the 15m open, after a conservative 15m signal delay.
        if t in signal_at:
            q = signal_at[t]
            pct = q.set_index("symbol").pred_pct.to_dict()
            n = len(q)
            k = max(MIN_SLOTS, int(math.floor(n * ENTRY_TAIL)))
            long_entry = list(q[q.pred_pct >= 1.0 - ENTRY_TAIL].sort_values("pred_rank", ascending=False).symbol)[:k]
            short_entry = list(q[q.pred_pct <= ENTRY_TAIL].sort_values("pred_rank", ascending=True).symbol)[:k]

            # Exits first: ranking deterioration, side inversion, or max holding window.
            for s in list(positions):
                if s not in opens:
                    continue
                p = positions[s]
                age = t - p["entry_time"]
                pr = pct.get(s)
                reason = None
                if age >= pd.Timedelta(hours=MAX_HOLD_HOURS):
                    reason = "MAX_HOLD"
                elif pr is None:
                    reason = "RANK_UNAVAILABLE"
                elif p["side"] > 0 and pr < 1.0 - HOLD_TAIL:
                    reason = "RANK_DROPOUT"
                elif p["side"] < 0 and pr > HOLD_TAIL:
                    reason = "RANK_DROPOUT"
                elif p["side"] > 0 and s in short_entry:
                    reason = "RANK_REVERSAL"
                elif p["side"] < 0 and s in long_entry:
                    reason = "RANK_REVERSAL"
                if reason:
                    close_position(s, t, opens[s], reason)

            # Mark current equity at open, then size new positions to preserve <=50% gross per side.
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
                new_syms = [s for s in candidates if s not in positions and s in opens and np.isfinite(atrs.get(s, np.nan))]
                if not new_syms or capacity <= 0:
                    continue
                target_each = 0.5 * open_equity / max(k, 1)
                for s in new_syms:
                    if capacity <= 1e-9:
                        break
                    notional = min(target_each, capacity)
                    if notional <= 1e-9:
                        continue
                    stop_frac = float(np.clip(STOP_ATR_MULT_15M * atrs[s], MIN_STOP_FRAC, MAX_STOP_FRAC))
                    entry_price = opens[s]
                    entry_cost = notional * one_way_cost
                    realized -= entry_cost
                    positions[s] = {
                        "symbol": s, "side": side, "entry_time": t, "entry_price": entry_price,
                        "notional": notional, "entry_cost": entry_cost, "stop_frac": stop_frac,
                        "stop_price": entry_price * (1.0 - stop_frac if side > 0 else 1.0 + stop_frac),
                    }
                    capacity -= notional

        # Intrabar stop checks after any open executions.
        for s in list(positions):
            if s not in opens:
                continue
            p = positions[s]
            sp = p["stop_price"]
            if p["side"] > 0:
                if opens[s] <= sp:
                    close_position(s, t, opens[s], "GAP_STOP")
                elif lows[s] <= sp:
                    close_position(s, t, sp, "STOP_15M")
            else:
                if opens[s] >= sp:
                    close_position(s, t, opens[s], "GAP_STOP")
                elif highs[s] >= sp:
                    close_position(s, t, sp, "STOP_15M")

        eq = mark_equity(realized, positions, closes)
        peak = max(peak, eq)
        dd = 1.0 - eq / peak if peak > 0 else 1.0
        curve.append({"time": t, "equity": eq, "realized_equity": realized, "drawdown": dd, "open_positions": len(positions)})
        if eq <= 0:
            break

    # Liquidate residual positions at last observed close inside the fold.
    final_t = timeline[-1] if len(timeline) else fold_end - pd.Timedelta(minutes=15)
    for s in list(positions):
        px = last_prices.get(s)
        if px is not None:
            close_position(s, final_t, px, "FOLD_END")

    td = pd.DataFrame(trades)
    cd = pd.DataFrame(curve)
    if td.empty:
        return td, cd, {"status":"NO_TRADES", "portfolio_return": float(realized / INITIAL_EQUITY - 1.0)}

    gross_win = float(td.loc[td.pnl_cash > 0, "pnl_cash"].sum())
    gross_loss = float(-td.loc[td.pnl_cash < 0, "pnl_cash"].sum())
    pf = math.inf if gross_loss <= 0 and gross_win > 0 else gross_win / gross_loss if gross_loss > 0 else None
    final_eq = float(realized)
    max_dd = float(cd.drawdown.max()) if not cd.empty else 0.0
    return td, cd, {
        "status":"OK",
        "trades": int(len(td)),
        "long_trades": int((td.side == "LONG").sum()),
        "short_trades": int((td.side == "SHORT").sum()),
        "win_rate": float((td.pnl_cash > 0).mean()),
        "avg_trade_net_return": float(td.net_return.mean()),
        "median_trade_net_return": float(td.net_return.median()),
        "profit_factor_cash": pf,
        "portfolio_return": float(final_eq / INITIAL_EQUITY - 1.0),
        "ending_equity": final_eq,
        "max_drawdown": max_dd,
        "avg_hold_hours": float(td.hold_hours.mean()),
        "stopped_share": float(td.exit_reason.isin(["STOP_15M","GAP_STOP"]).mean()),
        "exit_reasons": td.exit_reason.value_counts().to_dict(),
        "symbols": td.symbol.value_counts().to_dict(),
    }


def fold_schedule(ds):
    first = ds.index.min().floor("D")
    last = ds.index.max().ceil("D")
    cur = first + pd.Timedelta(days=TRAIN_DAYS) + pd.Timedelta(hours=PURGE_HOURS)
    folds = []
    while cur + pd.Timedelta(days=TEST_DAYS) <= last:
        folds.append((cur, cur + pd.Timedelta(days=TEST_DAYS)))
        cur += pd.Timedelta(days=TEST_DAYS)
    if os.environ.get("R13_SMOKE") == "1" and folds:
        folds = folds[-1:]
    return folds


def run(ds, data15, dev):
    fold_rows, pred_all, trades_all, curve_all = [], [], [], []
    stress_trades_all, stress_curve_all = [], []
    for fi, (t0, t1) in enumerate(fold_schedule(ds), start=1):
        tr0 = t0 - pd.Timedelta(hours=PURGE_HOURS) - pd.Timedelta(days=TRAIN_DAYS)
        tr1 = t0 - pd.Timedelta(hours=PURGE_HOURS)
        tr = ds[(ds.index >= tr0) & (ds.index < tr1)]
        te = ds[(ds.index >= t0) & (ds.index < t1)]

        base = {
            "fold": fi, "train_start": str(tr0), "train_end": str(tr1),
            "test_start": str(t0), "test_end": str(t1),
            "train_rows": int(len(tr)), "test_rows": int(len(te)),
        }
        if len(tr) < 40_000 or te.empty:
            fold_rows.append({**base, "status":"SKIP_INSUFFICIENT"})
            continue

        print(f"FOLD {fi} train={len(tr)} test={len(te)} {t0} -> {t1}", flush=True)
        m = model()
        m.fit(tr[FEATURES], tr.target_rank)
        pred = score_test(m, te)
        pred["fold"] = fi
        pred_all.append(pred)

        corr = spearman_stats(pred)
        trades, curve, port = simulate_fold(pred, data15, t0, t1, ONE_WAY_COST)
        strades, scurve, sport = simulate_fold(pred, data15, t0, t1, STRESS_ONE_WAY_COST)
        if not trades.empty:
            trades["fold"] = fi
            trades_all.append(trades)
        if not curve.empty:
            curve["fold"] = fi
            curve_all.append(curve)
        if not strades.empty:
            strades["fold"] = fi
            stress_trades_all.append(strades)
        if not scurve.empty:
            scurve["fold"] = fi
            stress_curve_all.append(scurve)

        fold_rows.append({
            **base, "status":"OOS", "predictions": int(len(pred)),
            "rank_corr_mean": corr["mean"], "rank_corr_median": corr["median"],
            "rank_corr_positive_share": corr["positive_share"],
            "portfolio_return": port.get("portfolio_return"),
            "trades": port.get("trades", 0),
            "pf": port.get("profit_factor_cash"),
            "win_rate": port.get("win_rate"),
            "max_drawdown": port.get("max_drawdown"),
            "stress_return": sport.get("portfolio_return"),
            "stress_pf": sport.get("profit_factor_cash"),
        })
        print("FOLD_RESULT " + json.dumps(fold_rows[-1], default=str, separators=(",",":")), flush=True)

    folds = pd.DataFrame(fold_rows)
    pred = pd.concat(pred_all).sort_index() if pred_all else pd.DataFrame()
    trades = pd.concat(trades_all, ignore_index=True) if trades_all else pd.DataFrame()
    curve = pd.concat(curve_all, ignore_index=True) if curve_all else pd.DataFrame()
    strades = pd.concat(stress_trades_all, ignore_index=True) if stress_trades_all else pd.DataFrame()
    scurve = pd.concat(stress_curve_all, ignore_index=True) if stress_curve_all else pd.DataFrame()
    return folds, pred, trades, curve, strades, scurve


def aggregate(folds, trades, stress_trades):
    valid = folds[folds.status == "OOS"].copy()
    if valid.empty:
        return {"status":"NO_VALID_FOLDS"}

    def compound(col):
        vals = pd.to_numeric(valid[col], errors="coerce").dropna()
        return float((1.0 + vals).prod() - 1.0) if len(vals) else None

    pf = None
    if not trades.empty:
        wins = float(trades.loc[trades.pnl_cash > 0, "pnl_cash"].sum())
        losses = float(-trades.loc[trades.pnl_cash < 0, "pnl_cash"].sum())
        pf = math.inf if losses <= 0 and wins > 0 else wins / losses if losses > 0 else None

    spf = None
    if not stress_trades.empty:
        wins = float(stress_trades.loc[stress_trades.pnl_cash > 0, "pnl_cash"].sum())
        losses = float(-stress_trades.loc[stress_trades.pnl_cash < 0, "pnl_cash"].sum())
        spf = math.inf if losses <= 0 and wins > 0 else wins / losses if losses > 0 else None

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
        "profit_factor_cash": pf,
        "max_fold_drawdown": float(valid.max_drawdown.max()),
        "stress_compounded_fold_return": compound("stress_return"),
        "stress_profit_factor_cash": spf,
        "symbols_traded": int(trades.symbol.nunique()) if not trades.empty else 0,
        "avg_hold_hours": float(trades.hold_hours.mean()) if not trades.empty else None,
        "exit_reasons": trades.exit_reason.value_counts().to_dict() if not trades.empty else {},
    }


def main():
    requested = [s for s in DEV_CANDIDATES if s != "MNTUSDT"]
    data15, data1, data4, skipped = load_universe(requested)
    dev = [s for s in requested if s in data15 and s in data1 and s in data4]
    if "BTCUSDT" not in dev or len(dev) < 30:
        raise RuntimeError(f"insufficient universe: {len(dev)}")

    features = make_features(data1, data4, dev)
    ds = attach_forward_labels(features, data15, dev)
    folds, pred, trades, curve, strades, scurve = run(ds, data15, dev)
    agg = aggregate(folds, trades, strades)

    result = {
        "version": VERSION,
        "data_root": str(DATA_ROOT),
        "period": [str(START), str(END_EXCLUSIVE)],
        "development_symbols": dev,
        "skipped": skipped,
        "outer_holdout_preregistered": OUTER_HOLDOUT,
        "outer_holdout_opened": False,
        "target_horizon_hours": TARGET_HOURS,
        "train_days": TRAIN_DAYS,
        "test_days": TEST_DAYS,
        "purge_hours": PURGE_HOURS,
        "ranking_timeframe": "1h",
        "context_timeframe": "4h",
        "execution_timeframe": "15m",
        "signal_to_execution_delay_minutes": 15,
        "entry_tail": ENTRY_TAIL,
        "hold_tail": HOLD_TAIL,
        "max_hold_hours": MAX_HOLD_HOURS,
        "stop_atr_mult_15m": STOP_ATR_MULT_15M,
        "stop_bounds": [MIN_STOP_FRAC, MAX_STOP_FRAC],
        "one_way_cost": ONE_WAY_COST,
        "stress_one_way_cost": STRESS_ONE_WAY_COST,
        "funding_modeled": False,
        "ranking_features_n": len(FEATURES),
        "dataset_rows": int(len(ds)),
        "dataset_timestamps": int(ds.index.nunique()),
        "prediction_hash": prediction_hash(pred),
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
        "outer_holdout_reason": "SHIB/OP/ARB remain unopened. R13.1 is development-only.",
        "methodology_note": "4h context is forward-filled only from completed 4h close-boundary bars. 1h ranking uses completed hourly bars. Execution waits 15 minutes after each hourly signal and manages positions on 15m OHLC.",
    }

    folds.to_csv("r13_1_folds.csv", index=False)
    if not pred.empty:
        pred.reset_index().to_parquet("r13_1_predictions.parquet", index=False, compression="zstd")
    if not trades.empty:
        trades.to_csv("r13_1_trades.csv", index=False)
    if not curve.empty:
        curve.to_parquet("r13_1_equity_curve.parquet", index=False, compression="zstd")
    if not strades.empty:
        strades.to_csv("r13_1_trades_stress.csv", index=False)
    if not scurve.empty:
        scurve.to_parquet("r13_1_equity_curve_stress.parquet", index=False, compression="zstd")
    Path("r13_1_result.json").write_text(json.dumps(result, indent=2, default=str))
    Path("r13_1_report.md").write_text(
        "# V10 R13.1 MTF Engine\n\n"
        "4h regime/context -> 1h cross-sectional ranking -> 15m execution.\n\n"
        + json.dumps(result, indent=2, default=str)
        + "\n"
    )
    print("===R13_1_RESULT_JSON===")
    print(json.dumps(result, separators=(",",":"), default=str))
    print("===END_R13_1_RESULT_JSON===")

if __name__ == "__main__":
    main()
