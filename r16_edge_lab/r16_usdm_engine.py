"""Frozen alpha, causal USD-M event replay. No optimization or Spot dependency.

OHLC stop/target decisions become known at the 15m close. Gaps are evaluated
at the open. Historical funding uses the last observed price unless a separate,
verified funding mark-price supplement exists. That limitation blocks promotion.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math

import numpy as np
import pandas as pd

from r16_sim_core import PortfolioLedger

BAR = 900_000
DAY = 86_400_000
INTERVAL = {"15m": BAR, "1h": BAR * 4, "4h": BAR * 16}
CONFIG_PATH = Path(__file__).with_name("r16_29_frozen_config.json")
CONFIG = json.loads(CONFIG_PATH.read_text())
START = int(pd.Timestamp(CONFIG["start"]).timestamp() * 1000)
END = int(pd.Timestamp(CONFIG["end_exclusive"]).timestamp() * 1000)
ENGINE_PRIORITY = {"CORE": 0, "REV15M": 1, "REV1H": 2}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def verify_dataset(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    unsigned = {k: v for k, v in manifest.items() if k != "dataset_manifest_sha256"}
    assert fingerprint(unsigned) == CONFIG["dataset_manifest_sha256"]
    for entry in manifest["files"]:
        parts = Path(entry["path"]).parts
        i = next(i for i, p in enumerate(parts) if p in ("funding", "klines"))
        path = root.joinpath(*parts[i:])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], str(path)
    return manifest


class Dataset:
    def __init__(self, root, *, cutoff=None, perturb_after=None, verify=True):
        self.root = Path(root)
        self.manifest = verify_dataset(root) if verify else json.loads((self.root / "manifest.json").read_text())
        self.pit = {r["symbol"]: int(r["firstFundingTime"]) for r in self.manifest["symbols"] if r["eligible"]}
        self.frames = {}
        self.bars = {}
        self.funding = []
        self.cutoff = cutoff
        for symbol in sorted(self.pit):
            for interval in INTERVAL:
                frame = pd.read_csv(self.root / "klines" / interval / f"{symbol}.csv.gz",
                                    usecols=["open_time", "open", "high", "low", "close", "volume"])
                frame.open_time = frame.open_time.astype("int64")
                assert frame.open_time.is_monotonic_increasing and frame.open_time.is_unique
                assert (frame.open_time >= self.pit[symbol]).all()
                assert np.isfinite(frame.to_numpy()).all()
                assert (frame[["open", "high", "low", "close"]] > 0).all().all()
                assert ((frame.high >= frame[["open", "close", "low"]].max(axis=1)) &
                        (frame.low <= frame[["open", "close", "high"]].min(axis=1))).all()
                known = frame.open_time + INTERVAL[interval] - 1
                if cutoff is not None:
                    # A truncated replay contains only fully known observations.
                    frame = frame.loc[known <= cutoff].copy()
                    known = frame.open_time + INTERVAL[interval] - 1
                if perturb_after is not None:
                    mask = known > perturb_after
                    # Deterministic severe future-only price/volume perturbation.
                    frame.loc[mask, ["open", "high", "low", "close"]] *= 1.73
                    frame.loc[mask, "volume"] *= 3.11
                self.frames[(symbol, interval)] = frame.reset_index(drop=True)
                if interval == "15m":
                    self.bars[symbol] = (frame.open_time.to_numpy(), frame[["open", "high", "low", "close"]].to_numpy())
            funding = pd.read_csv(self.root / "funding" / f"{symbol}.csv.gz")
            assert funding.fundingTime.is_monotonic_increasing and funding.fundingTime.is_unique
            for row in funding.itertuples(index=False):
                timestamp = int(row.fundingTime)
                if cutoff is not None and timestamp > cutoff:
                    continue
                rate = float(row.fundingRate)
                if perturb_after is not None and timestamp > perturb_after:
                    rate = -rate * 7
                self.funding.append((timestamp, symbol, rate))
        self.funding.sort()

    def bar(self, symbol, timestamp):
        times, values = self.bars[symbol]
        i = int(np.searchsorted(times, timestamp))
        return values[i] if i < len(times) and times[i] == timestamp else None


def features(frame, interval):
    x = frame.copy()
    h, l, c, v = x.high, x.low, x.close, x.volume
    rma = lambda s, n: s.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = rma(tr, 14)
    x["rsi"] = 100 - 100 / (1 + rma(c.diff().clip(lower=0), 14) /
                            rma((-c.diff()).clip(lower=0), 14).replace(0, np.nan))
    x["body"] = (c-l) / (h-l).replace(0, np.nan)
    if interval == "4h":
        up, dn = h.diff(), -l.diff()
        plus = 100*rma(up.where((up > dn) & (up > 0), 0.), 14) / x.atr.replace(0, np.nan)
        minus = 100*rma(dn.where((dn > up) & (dn > 0), 0.), 14) / x.atr.replace(0, np.nan)
        x["adx"] = rma(100*(plus-minus).abs()/(plus+minus).replace(0, np.nan), 14)
        x["ema50"] = c.ewm(span=50, adjust=False, min_periods=50).mean()
        x["ema200"] = c.ewm(span=200, adjust=False, min_periods=200).mean()
        x["ret42"] = c.pct_change(42, fill_method=None)
        x["hi55"] = h.shift().rolling(55, min_periods=55).max()
    else:
        n, minimum, horizon = (48, 36, 6) if interval == "1h" else (96, 72, 16)
        x["volz"] = (v-v.rolling(n, min_periods=minimum).mean())/v.rolling(n, min_periods=minimum).std().replace(0, np.nan)
        x["move"] = c.pct_change(horizon, fill_method=None)
    x["knowledge_ts"] = x.open_time + INTERVAL[interval] - 1
    return x


def generate_signals(data):
    """Pure causal feature computation; no entry/exit outcome is read here."""
    signals = []
    f4 = {s: features(data.frames[(s, "4h")], "4h") for s in sorted(data.pit)}
    breadth_parts = []
    for symbol, x in f4.items():
        breadth_parts.append(pd.Series(np.where(x.ema200.notna(), (x.close > x.ema200).astype(float), np.nan),
                                       index=x.knowledge_ts, name=symbol))
    breadth = pd.concat(breadth_parts, axis=1).mean(axis=1)
    btc = f4["BTCUSDT"].set_index("knowledge_ts")
    strict = ((btc.close > btc.ema200) & (btc.ema50 > btc.ema200) & (btc.ret42 > 0))
    for engine, cfg in CONFIG["engines"].items():
        interval = cfg["interval"]
        for symbol in sorted(data.pit):
            x = f4[symbol] if engine == "CORE" else features(data.frames[(symbol, interval)], interval)
            if engine == "CORE":
                context = strict.reindex(x.knowledge_ts).fillna(False).to_numpy() & (breadth.reindex(x.knowledge_ts).to_numpy() >= cfg["breadth"])
                mask = ((x.close > x.hi55) & (x.close.shift() <= x.hi55.shift()) &
                        (x.ema50 > x.ema200) & (x.adx >= cfg["adx"]) & context)
            else:
                mask = ((x.move <= -cfg["move"]) & (x.volz >= cfg["volz"]) &
                        (x.rsi <= cfg["rsi_max"]) & (x.body >= cfg["body"]))
            for i in np.flatnonzero(mask.fillna(False).to_numpy()):
                row = x.iloc[i]
                if not np.isfinite(row.atr) or row.atr <= 0:
                    continue
                t = int(row.knowledge_ts)
                signals.append({"id": f"{engine}:{symbol}:{t}", "engine": engine, "symbol": symbol,
                                "timestamp": t, "knowledge_ts": t, "source_open_ts": int(row.open_time),
                                "atr": float(row.atr)})
    return sorted(signals, key=lambda x: (x["timestamp"], ENGINE_PRIORITY[x["engine"]], x["symbol"]))


def exit_reference(position, bar, timestamp, *, at_open=False):
    """Same production function used by gap/collision fixtures and replay."""
    op, high, low, close = map(float, bar)
    stop, target = position["stop"], position["target"]
    if at_open:
        if op <= stop:
            return op, "STOP_GAP"
        if op >= target:
            return target, "TARGET_GAP"
        return None
    hit_stop, hit_target = low <= stop, high >= target
    if hit_stop:
        return min(op, stop), "STOP_AMBIGUOUS" if hit_target else "STOP"
    if hit_target:
        return target, "TARGET"
    if timestamp >= position["deadline"]:
        return close, "TIME"
    return None


@dataclass
class Replay:
    ledger: PortfolioLedger
    trades: list
    daily: list
    shadow_closes: list
    diagnostics: dict


def replay(data, signals=None, *, scenario="BASE", until=END-1, trade_start=START, liquidate_end=True):
    signals = generate_signals(data) if signals is None else signals
    model = CONFIG["scenarios"][scenario]
    fee, slip = model["fee"], model["slip"]
    ledger = PortfolioLedger(CONFIG["capital"], CONFIG["leverage"], CONFIG["max_stop_risk"])
    pending, shadow, actual = {}, {}, {}
    shadow_closed, trades, daily = [], [], []
    histories = {e: deque() for e in CONFIG["engines"]}
    clusters, rejected = Counter(), Counter()
    coexposure = Counter()
    si = fi = 0
    peak = CONFIG["capital"]
    minimum_isolated = math.inf
    max_risk = 0.
    max_gross = 0.
    data_gaps = set()

    def record(t, event, **payload):
        ledger._check_time(t)
        ledger._record(t, event, payload)

    def close_position(key, t, ref, reason):
        s = shadow.pop(key)
        fill = ref*(1-slip)
        net = (fill-s["fill"]) - fee*(s["fill"]+fill) + s["funding"]
        result = {"id": key, "engine": s["engine"], "symbol": s["symbol"], "exit_ts": t,
                  "entry_ts": s["entry_ts"], "net_pct": net/s["fill"], "reason": reason}
        histories[s["engine"]].append(result)
        shadow_closed.append(result)
        record(t, "SHADOW_CLOSE", **result)
        if key in actual:
            a = actual.pop(key)
            p = ledger.positions[key]
            funding_cash = p.funding_cashflow
            qty = p.qty
            ledger.close(t, key, fill, fee, reason, ref)
            trades.append({**a, "exit_ts": t, "exit_reference": ref, "exit_fill": fill, "reason": reason,
                           "gross": qty*(ref-a["entry_reference"]),
                           "commissions": qty*(a["entry_fill"]+fill)*fee,
                           "slippage": qty*((a["entry_fill"]-a["entry_reference"])+(ref-fill)),
                           "funding": funding_cash,
                           "net": qty*(fill-a["entry_fill"])-qty*(a["entry_fill"]+fill)*fee+funding_cash})

    def mark_symbols(t, bars, field, exits=None):
        prices = {}
        for symbol in sorted({p.symbol for p in ledger.positions.values()}):
            b = bars.get(symbol)
            if b is not None:
                prices[symbol] = float(b[field])
        for key, result in (exits or {}).items():
            if key in ledger.positions:
                prices[ledger.positions[key].symbol] = result[0]
        if prices:
            ledger.mark_many(t, prices)

    def fund(t, symbol, rate):
        for p in shadow.values():
            if p["symbol"] == symbol:
                p["funding"] -= p["mark"]*rate
        if any(p.symbol == symbol for p in ledger.positions.values()):
            ledger.funding_event(t, symbol, rate)

    # All features before trade_start remain available for warmup. No outcome
    # ending after trade_start is imported into the initial regime/portfolio.
    while si < len(signals) and signals[si]["timestamp"] < trade_start:
        si += 1
    while fi < len(data.funding) and data.funding[fi][0] < trade_start:
        fi += 1
    begin = trade_start//BAR*BAR
    for t in range(begin, until+1, BAR):
        close_ts = t+BAR-1
        names = {p["symbol"] for p in shadow.values()} | {p["symbol"] for p in pending.values()}
        bars = {s: data.bar(s, t) for s in names}
        for s in names:
            if bars[s] is None and any(p["symbol"] == s for p in shadow.values()):
                data_gaps.add((s, t))
        gap_exits = {key: result for key, p in shadow.items()
                     if bars.get(p["symbol"]) is not None
                     and (result := exit_reference(p, bars[p["symbol"]], t, at_open=True))}
        mark_symbols(t, bars, 0)
        for p in shadow.values():
            if bars[p["symbol"]] is not None:
                p["mark"] = float(bars[p["symbol"]][0])
        # Existing wallets pay exact-boundary funding before closes/new fills.
        while fi < len(data.funding) and data.funding[fi][0] == t:
            fund(*data.funding[fi]); fi += 1
        for key, result in gap_exits.items():
            close_position(key, t, *result)
        for key, order in list(pending.items()):
            if t < order["earliest_fill_ts"] or bars.get(order["symbol"]) is None:
                continue
            del pending[key]
            e, s = order["engine"], order["symbol"]
            cfg = CONFIG["engines"][e]
            ref = float(bars[s][0]); fill = ref*(1+slip)
            stop, target = fill-cfg["stop_atr"]*order["atr"], fill+cfg["target_atr"]*order["atr"]
            if stop <= 0:
                rejected["invalid_stop"] += 1
                record(t, "REJECT", position_id=key, reason="invalid_stop")
                continue
            shadow[key] = {"engine": e, "symbol": s, "entry_ts": t, "fill": fill, "mark": ref,
                           "stop": stop, "target": target, "funding": 0.,
                           "deadline": t+cfg["hold_bars"]*INTERVAL[cfg["interval"]]-1}
            month = pd.Timestamp(t, unit="ms", tz="UTC").tz_localize(None).to_period("M")
            cutoff = int((month-CONFIG["regime_months"]).start_time.tz_localize("UTC").timestamp()*1000)
            scores, last_exits = {}, {}
            for engine, h in histories.items():
                while h and h[0]["exit_ts"] < cutoff:
                    h.popleft()
                scores[engine] = sum(r["net_pct"] for r in h)/len(h) if h else 0.
                last_exits[engine] = h[-1]["exit_ts"] if h else None
            hot = sum(scores.values()) > 0 and sum(v > 0 for v in scores.values()) >= 2
            mult = CONFIG["regime_hot_multiplier" if hot else "regime_cold_multiplier"]
            record(t, "ALLOCATION", position_id=key, scores=scores, regime_last_exit=last_exits,
                   regime="HOT" if hot else "COLD", knowledge_ts=order["knowledge_ts"])
            reason = None
            if scores[e] < 0 and not (e == "CORE" and not hot):
                reason = "regime"
            elif sum(p.engine == e for p in ledger.positions.values()) >= cfg["max_positions"]:
                reason = "engine_maxpos"
            elif any(p.symbol == s for p in ledger.positions.values()):
                reason = "symbol_held"
            equity = ledger.equity()
            desired = min(equity*CONFIG["per_position_cap"], equity*cfg["risk"]*mult/((fill-stop)/fill))
            # Entry fees/slippage must fit in cash in addition to reserved margin.
            collateral_cap = max(0., ledger.available_collateral())/(1+fee+slip/(1+slip))
            # Gross/equity at entry <=1 including already marked positions/costs.
            gross_cap = max(0., equity-ledger.gross_notional())/(1+fee+slip/(1+slip))
            notional = min(desired, collateral_cap, gross_cap)
            if reason is None and notional < equity*CONFIG["minimum_position"]:
                reason = "collateral_or_min_size"
            if reason:
                rejected[reason] += 1
                record(t, "REJECT", position_id=key, engine=e, symbol=s, reason=reason)
                continue
            qty = notional/fill
            ok, reason = ledger.open(t, key, e, s, 1, qty, fill, stop, fee, fee, ref, slip)
            if not ok:
                rejected[reason] += 1
                continue
            actual[key] = {"id": key, "engine": e, "symbol": s, "regime": "HOT" if hot else "COLD",
                           "signal_ts": order["timestamp"], "knowledge_ts": order["knowledge_ts"],
                           "order_ts": order["timestamp"], "entry_ts": t, "qty": qty,
                           "entry_fill": fill, "entry_reference": ref, "stop": stop, "target": target}
        # Funding inside the bar cannot see its high/low/close.
        while fi < len(data.funding) and data.funding[fi][0] <= min(close_ts, until):
            fund(*data.funding[fi]); fi += 1
        if close_ts > until:
            break
        bar_exits = {key: result for key, p in shadow.items()
                     if bars.get(p["symbol"]) is not None
                     and (result := exit_reference(p, bars[p["symbol"]], close_ts))}
        # A position stopped earlier in this OHLC bar is not marked to the later
        # close and then resurrected at its stop. Use its execution reference.
        mark_symbols(close_ts, bars, 3, bar_exits)
        for p in shadow.values():
            if bars[p["symbol"]] is not None:
                p["mark"] = float(bars[p["symbol"]][3])
        for key, result in bar_exits.items():
            close_position(key, close_ts, *result)
        if liquidate_end and close_ts == END-1:
            for key, p in list(shadow.items()):
                close_position(key, close_ts, p["mark"], "DECLARED_END")
        while si < len(signals) and signals[si]["timestamp"] <= close_ts:
            sig = signals[si]; si += 1
            if sig["timestamp"] < t:
                raise AssertionError("signal skipped by event clock")
            e, s, key = sig["engine"], sig["symbol"], sig["id"]
            record(close_ts, "SIGNAL", **{k: v for k, v in sig.items() if k != "timestamp"}, signal_ts=sig["timestamp"])
            cfg = CONFIG["engines"][e]
            cluster = (e, sig["source_open_ts"]//(3*3_600_000))
            occupied = any(p["engine"] == e and p["symbol"] == s for p in list(shadow.values())+list(pending.values()))
            if occupied or (e != "CORE" and clusters[cluster] >= 3):
                rejected["shadow_occupied" if occupied else "cluster_limit"] += 1
                continue
            if e != "CORE":
                clusters[cluster] += 1
            order = {**sig, "earliest_fill_ts": close_ts+1+model["latency_bars_15m"]*BAR}
            pending[key] = order
            record(close_ts, "ORDER", **{k: v for k, v in order.items() if k != "timestamp"}, order_ts=close_ts)
        snapshot = ledger._snapshot()
        peak = max(peak, snapshot["equity"])
        max_risk = max(max_risk, snapshot["open_stop_risk"]/snapshot["equity"])
        max_gross = max(max_gross, snapshot["gross_to_equity"])
        if ledger.positions:
            minimum_isolated = min(minimum_isolated, snapshot["minimum_isolated_equity"])
        symbols = sorted(p.symbol for p in ledger.positions.values())
        for i, a in enumerate(symbols):
            for b in symbols[i+1:]:
                coexposure[f"{a}/{b}"] += 1
        if (close_ts+1) % DAY == 0 or close_ts == until:
            record(close_ts, "DAILY")
            daily.append({"timestamp": close_ts, **ledger._snapshot()})
    ledger.assert_reconciles()
    return Replay(ledger, trades, daily, shadow_closed,
                  {"scenario": scenario, "rejections": dict(rejected), "signals": len([s for s in signals if trade_start <= s["timestamp"] <= until]),
                   "open_positions": len(ledger.positions), "pending_orders": len(pending),
                   "missing_active_bars": len(data_gaps), "missing_active_bar_examples": sorted(data_gaps)[:20],
                   "max_bar_close_stop_risk_fraction": max_risk, "max_bar_close_gross_equity": max_gross,
                   "minimum_isolated_equity": None if minimum_isolated == math.inf else minimum_isolated,
                   "coexposure_15m_bars": dict(coexposure.most_common()),
                   "price_model": "last traded 15m OHLC; not exchange mark-price series"})
