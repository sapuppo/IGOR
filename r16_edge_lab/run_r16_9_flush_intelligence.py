#!/usr/bin/env python3
"""R16.9 - Flush Reversal Intelligence

Frozen primary engine remains untouched.

Second-alpha base event frozen from R16.8:
- 1h return over 6h <= -7%
- volume z-score >= 2.0
- RSI14 <= 32
- close position in candle >= 0.60
- stop 1.25 ATR
- target 2.5 ATR
- max hold 18 x 1h

This stage tests only PREDECLARED contextual gates on development data < 2026-07-01:
- BTC regime: ANY / BTC_ABOVE_4H_EMA200 / BTC_STRICT_UP
- coin 4h trend: ANY / ABOVE_EMA200
- market breadth floor: none / 35% / 45%
- flush depth: <= -7% / <= -9%
- recovery candle body position: >= .60 / >= .75

No ML. No leverage. July/August 2026 are not used.

A candidate advances only if:
- >= 150 trades
- base PF >= 1.20
- stress PF >= 1.15
- positive expectancy base/stress
- all years positive
- >= 70% positive quarters
- weekly block bootstrap P(mean>0) >= 90%
- no symbol > 30% of positive PnL
- |weekly correlation with CORE| <= 0.40

Portfolio comparison uses a protected separate sleeve so FLUSH cannot block CORE trades.
"""
from __future__ import annotations

import json
import heapq
from pathlib import Path

import numpy as np
import pandas as pd

ROOT1 = Path("r15_regime_lab/history/1h")
ROOT4 = Path("r15_regime_lab/history/4h")
OUT = Path("r16_edge_lab/r16_9_flush_intelligence")
OUT.mkdir(parents=True, exist_ok=True)

DEV_END = int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp() * 1000)
BASE_COST = .0016
STRESS_COST = .0021
SEED = 1690

FLUSH_STOP = 1.25
FLUSH_TARGET = 2.5
FLUSH_HOLD = 18

CORE_STOP = 2.0
CORE_TARGET = 6.0
CORE_HOLD = 30

START_CAP = 10_000.0
CORE_RISK = .0025
CORE_MAX = 5
FLUSH_RISK = .0010
FLUSH_MAX = 2
NOTIONAL_CAP = .25

SYMBOLS = [
    'BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT',
    'LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT',
    'SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT',
    'WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT',
    'FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT'
]

def rma(s, n):
    return s.ewm(alpha=1/n, adjust=False, min_periods=n).mean()

def add_indicators(x):
    h, l, c, v = x.high, x.low, x.close, x.volume
    pc = c.shift()
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    atr = rma(tr, 14)
    up = h.diff()
    dn = -l.diff()
    plus = 100 * rma(up.where((up > dn) & (up > 0), 0.0), 14) / atr.replace(0, np.nan)
    minus = 100 * rma(dn.where((dn > up) & (dn > 0), 0.0), 14) / atr.replace(0, np.nan)
    dx = 100 * (plus-minus).abs() / (plus+minus).replace(0, np.nan)

    x["atr"] = atr
    x["adx"] = rma(dx, 14)
    x["ema50"] = c.ewm(span=50, adjust=False, min_periods=50).mean()
    x["ema200"] = c.ewm(span=200, adjust=False, min_periods=200).mean()
    x["rsi14"] = 100 - (100 / (1 + rma(c.diff().clip(lower=0),14) /
                                  rma((-c.diff()).clip(lower=0),14).replace(0,np.nan)))
    x["ret1"] = c.pct_change()
    x["ret6"] = c.pct_change(6)
    x["ret24"] = c.pct_change(24)
    x["ret42"] = c.pct_change(42)
    x["volz48"] = (v-v.rolling(48,min_periods=36).mean()) / v.rolling(48,min_periods=36).std().replace(0,np.nan)
    x["body_pos"] = (c-l) / (h-l).replace(0,np.nan)
    return x

def load(root, sym):
    x = pd.read_csv(root / f"{sym}.csv.gz")
    for c in ["open_time","open","high","low","close","volume"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna().sort_values("open_time").drop_duplicates("open_time")
    x = x[x.open_time < DEV_END].reset_index(drop=True)
    return add_indicators(x)

print("Loading 1h and 4h data...", flush=True)
F1 = {s: load(ROOT1, s) for s in SYMBOLS}
F4 = {s: load(ROOT4, s) for s in SYMBOLS}

# ---------- 4h market context ----------
parts = []
for sym, z in F4.items():
    ser = pd.Series(
        np.where(z.ema200.notna(), (z.close > z.ema200).astype(float), np.nan),
        index=z.open_time.astype("int64"),
        name=sym
    )
    parts.append(ser[~ser.index.duplicated()])

breadth4 = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
btc4 = F4["BTCUSDT"].set_index("open_time")
ctx4 = pd.DataFrame(index=breadth4.index)
ctx4["breadth"] = breadth4
ctx4["btc_above200"] = (btc4.close > btc4.ema200).reindex(ctx4.index).fillna(False)
ctx4["btc_strict"] = (
    (btc4.close > btc4.ema200) &
    (btc4.ema50 > btc4.ema200) &
    (btc4.ret42 > 0)
).reindex(ctx4.index).fillna(False)

def floor4h(ts):
    return (int(ts) // (4 * 3600_000)) * (4 * 3600_000)

# ---------- core benchmark ----------
def simulate_long(z, signal_idxs, stop_atr, target_atr, hold, cost, sym, extra=None):
    rows = []
    last_exit = -1
    for i in signal_idxs:
        if i <= last_exit or i >= len(z)-1:
            continue
        atr = float(z.atr.iloc[i])
        if not np.isfinite(atr) or atr <= 0:
            continue
        ei = i + 1
        entry = float(z.open.iloc[ei])
        stop = entry - stop_atr * atr
        target = entry + target_atr * atr
        end = min(ei + hold - 1, len(z)-1)
        px = float(z.close.iloc[end])
        xi = end
        reason = "TIME"
        for j in range(ei, end+1):
            hi = float(z.high.iloc[j])
            lo = float(z.low.iloc[j])
            hs = lo <= stop
            ht = hi >= target
            if hs and ht:
                px = stop
                xi = j
                reason = "STOP_AMBIGUOUS"
                break
            if hs:
                px = stop
                xi = j
                reason = "STOP"
                break
            if ht:
                px = target
                xi = j
                reason = "TARGET"
                break
        gross = (px-entry)/entry
        row = {
            "symbol": sym,
            "entry_time": int(z.open_time.iloc[ei]),
            "exit_time": int(z.open_time.iloc[xi]) + int((z.open_time.iloc[min(xi+1,len(z)-1)] - z.open_time.iloc[xi]) if xi+1 < len(z) else 0),
            "stop_pct": stop_atr * atr / entry,
            "net_pct": gross - 2 * cost,
            "reason": reason
        }
        if extra:
            row.update(extra(i))
        rows.append(row)
        last_exit = xi
    return rows

def core_trades(cost):
    rows = []
    for sym, z in F4.items():
        hi55 = z.high.shift(1).rolling(55, min_periods=55).max()
        c = z.close
        prev = c.shift()
        sig = (c > hi55) & (prev <= hi55.shift()) & (z.ema50 > z.ema200) & (z.adx >= 30)
        idxs = []
        for i in np.flatnonzero(np.asarray(sig.fillna(False))):
            ts = int(z.open_time.iloc[i])
            if ts in ctx4.index and bool(ctx4.loc[ts,"btc_strict"]) and float(ctx4.loc[ts,"breadth"]) >= .55:
                idxs.append(i)
        rows.extend(simulate_long(z, idxs, CORE_STOP, CORE_TARGET, CORE_HOLD, cost, sym))
    return pd.DataFrame(rows)

CORE_BASE = core_trades(BASE_COST)
CORE_STRESS = core_trades(STRESS_COST)

# ---------- frozen FLUSH base events with causal context ----------
def build_flush_events(cost):
    rows = []
    for sym, z in F1.items():
        base = (
            (z.ret6 <= -.07) &
            (z.volz48 >= 2.0) &
            (z.rsi14 <= 32) &
            (z.body_pos >= .60)
        )
        idxs = np.flatnonzero(np.asarray(base.fillna(False)))

        # simulate each raw event independently first; filtering occurs later
        # Re-entry suppression is applied after contextual filtering.
        for i in idxs:
            if i >= len(z)-1:
                continue
            ts = int(z.open_time.iloc[i])
            t4 = floor4h(ts)
            if t4 not in ctx4.index:
                continue
            # coin 4h context at or before event
            z4 = F4[sym]
            arr = z4.open_time.to_numpy()
            j4 = np.searchsorted(arr, t4, side="right") - 1
            if j4 < 0:
                continue
            atr = float(z.atr.iloc[i])
            if not np.isfinite(atr) or atr <= 0:
                continue

            ei = i + 1
            entry = float(z.open.iloc[ei])
            stop = entry - FLUSH_STOP * atr
            target = entry + FLUSH_TARGET * atr
            end = min(ei + FLUSH_HOLD - 1, len(z)-1)
            px = float(z.close.iloc[end])
            xi = end
            reason = "TIME"
            for k in range(ei, end+1):
                hi = float(z.high.iloc[k])
                lo = float(z.low.iloc[k])
                hs = lo <= stop
                ht = hi >= target
                if hs and ht:
                    px = stop; xi = k; reason = "STOP_AMBIGUOUS"; break
                if hs:
                    px = stop; xi = k; reason = "STOP"; break
                if ht:
                    px = target; xi = k; reason = "TARGET"; break

            gross = (px-entry)/entry
            rows.append({
                "symbol": sym,
                "signal_idx": int(i),
                "signal_time": ts,
                "entry_time": int(z.open_time.iloc[ei]),
                "exit_time": int(z.open_time.iloc[xi]) + 3600_000,
                "stop_pct": FLUSH_STOP * atr / entry,
                "net_pct": gross - 2 * cost,
                "reason": reason,
                "ret6": float(z.ret6.iloc[i]),
                "body_pos": float(z.body_pos.iloc[i]),
                "volz48": float(z.volz48.iloc[i]),
                "rsi14": float(z.rsi14.iloc[i]),
                "breadth": float(ctx4.loc[t4,"breadth"]),
                "btc_above200": bool(ctx4.loc[t4,"btc_above200"]),
                "btc_strict": bool(ctx4.loc[t4,"btc_strict"]),
                "coin_above200_4h": bool(z4.close.iloc[j4] > z4.ema200.iloc[j4]) if np.isfinite(z4.ema200.iloc[j4]) else False,
            })
    return pd.DataFrame(rows)

RAW_BASE = build_flush_events(BASE_COST)
RAW_STRESS = build_flush_events(STRESS_COST)

def filter_and_dedupe(df, btc_mode, coin_mode, breadth_floor, depth, body):
    m = (df.ret6 <= depth) & (df.body_pos >= body)
    if btc_mode == "ABOVE200":
        m &= df.btc_above200
    elif btc_mode == "STRICT":
        m &= df.btc_strict
    if coin_mode == "ABOVE200":
        m &= df.coin_above200_4h
    if breadth_floor is not None:
        m &= df.breadth >= breadth_floor

    x = df[m].sort_values(["symbol","entry_time"]).copy()
    # causal same-symbol re-entry suppression only after contextual gate
    keep = []
    last_exit = {}
    for idx, r in x.iterrows():
        le = last_exit.get(r.symbol, -1)
        if int(r.entry_time) <= le:
            continue
        keep.append(idx)
        last_exit[r.symbol] = int(r.exit_time)
    return x.loc[keep].sort_values("entry_time").reset_index(drop=True)

def pf(a):
    a = np.asarray(a, float)
    gp = a[a > 0].sum()
    gl = -a[a < 0].sum()
    return float(gp/gl) if gl > 0 else None

def weekly_series(d):
    if d.empty:
        return pd.Series(dtype=float)
    x = d.copy()
    dt = pd.to_datetime(x.entry_time, unit="ms", utc=True)
    x["week"] = (dt - dt.dt.weekday.astype("timedelta64[D]")).dt.floor("D")
    return x.groupby("week").net_pct.sum()

CORE_W = weekly_series(CORE_BASE)

def block_prob(d, n=1500):
    w = weekly_series(d).to_numpy(float)
    if len(w) < 15:
        return 0.0
    rng = np.random.default_rng(SEED)
    vals = np.empty(n)
    for i in range(n):
        vals[i] = rng.choice(w, len(w), replace=True).mean()
    return float((vals > 0).mean())

def stats(d):
    if d.empty:
        return {"trades": 0}
    r = d.net_pct.to_numpy(float)
    dt = pd.to_datetime(d.entry_time, unit="ms", utc=True)
    q = d.assign(q=dt.dt.to_period("Q").astype(str)).groupby("q").net_pct.sum()
    y = d.assign(y=dt.dt.year).groupby("y").net_pct.sum()
    mo = d.assign(m=dt.dt.to_period("M").astype(str)).groupby("m").net_pct.sum()
    sy = d.groupby("symbol").net_pct.sum()
    pos = sy.clip(lower=0)
    w = weekly_series(d)
    common = CORE_W.index.intersection(w.index)
    corr = float(CORE_W.loc[common].corr(w.loc[common])) if len(common) >= 10 else None
    return {
        "trades": int(len(d)),
        "avg": float(r.mean()),
        "pf": pf(r),
        "win_rate": float((r > 0).mean()),
        "positive_quarter_rate": float((q > 0).mean()),
        "all_years_positive": bool((y > 0).all()),
        "weekly_prob_positive": block_prob(d),
        "active_months": int(len(mo)),
        "positive_month_rate": float((mo > 0).mean()),
        "median_month_sum": float(mo.median()),
        "best_month_sum": float(mo.max()),
        "worst_month_sum": float(mo.min()),
        "max_positive_symbol_share": float(pos.max()/pos.sum()) if pos.sum() > 0 else 1.0,
        "weekly_corr_core": corr
    }

# Predeclared grid: 3 * 2 * 3 * 2 * 2 = 72 candidates.
BTC_MODES = ["ANY","ABOVE200","STRICT"]
COIN_MODES = ["ANY","ABOVE200"]
BREADTHS = [None,.35,.45]
DEPTHS = [-.07,-.09]
BODIES = [.60,.75]

rows = []
cand_cache = {}
for btc_mode in BTC_MODES:
    for coin_mode in COIN_MODES:
        for br in BREADTHS:
            for dep in DEPTHS:
                for body in BODIES:
                    name = f"BTC{btc_mode}_COIN{coin_mode}_B{('N' if br is None else int(br*100))}_D{int(abs(dep)*100)}_R{int(body*100)}"
                    b = filter_and_dedupe(RAW_BASE, btc_mode, coin_mode, br, dep, body)
                    s = filter_and_dedupe(RAW_STRESS, btc_mode, coin_mode, br, dep, body)
                    mb = stats(b)
                    ms = stats(s)
                    corr = mb.get("weekly_corr_core")
                    passed = bool(
                        mb.get("trades",0) >= 150 and
                        mb.get("avg",0) > 0 and ms.get("avg",0) > 0 and
                        mb.get("pf",0) >= 1.20 and ms.get("pf",0) >= 1.15 and
                        mb.get("all_years_positive",False) and
                        mb.get("positive_quarter_rate",0) >= .70 and
                        mb.get("weekly_prob_positive",0) >= .90 and
                        mb.get("max_positive_symbol_share",1) <= .30 and
                        (corr is None or abs(corr) <= .40)
                    )
                    rows.append({
                        "name": name,
                        "btc_mode": btc_mode,
                        "coin_mode": coin_mode,
                        "breadth_floor": br,
                        "depth": dep,
                        "body": body,
                        **{f"base_{k}":v for k,v in mb.items()},
                        **{f"stress_{k}":v for k,v in ms.items()},
                        "passes_gate": passed
                    })
                    cand_cache[name] = (b, s)

R = pd.DataFrame(rows)
R["score"] = (
    R["passes_gate"].astype(int) * 1000 +
    R["base_weekly_prob_positive"].fillna(0) * 100 +
    R["stress_pf"].fillna(0) * 10 +
    R["base_positive_month_rate"].fillna(0)
)
R = R.sort_values(["passes_gate","score","base_pf"], ascending=[False,False,False])
R.to_csv(OUT/"flush_context_grid.csv", index=False)

# Protected CORE + FLUSH sleeve simulator.
def combined_portfolio(core, flush, flush_risk=FLUSH_RISK, flush_max=FLUSH_MAX):
    events = []
    for r in core.itertuples(index=False):
        events.append(("CORE", int(r.entry_time), int(r.exit_time), r.symbol, float(r.stop_pct), float(r.net_pct)))
    for r in flush.itertuples(index=False):
        events.append(("FLUSH", int(r.entry_time), int(r.exit_time), r.symbol, float(r.stop_pct), float(r.net_pct)))
    events.sort(key=lambda x: (x[1], 0 if x[0] == "CORE" else 1, x[3]))

    eq = START_CAP
    curve = [eq]
    core_heap, flush_heap = [], []
    core_syms, flush_syms = set(), set()
    uid = 0
    core_acc = flush_acc = rejected = 0

    def settle(heap, syms, until):
        nonlocal eq
        while heap and heap[0][0] <= until:
            ex, _, pnl, sym = heapq.heappop(heap)
            eq += pnl
            syms.discard(sym)
            curve.append(eq)

    for kind, et, xt, sym, stop_pct, net_pct in events:
        settle(core_heap, core_syms, et)
        settle(flush_heap, flush_syms, et)
        if kind == "CORE":
            if len(core_heap) >= CORE_MAX or sym in core_syms or sym in flush_syms:
                rejected += 1
                continue
            risk = CORE_RISK
            notional = min(eq*NOTIONAL_CAP, eq*risk/max(stop_pct,1e-6))
            pnl = notional * net_pct
            heapq.heappush(core_heap, (xt, uid, pnl, sym))
            core_syms.add(sym)
            core_acc += 1
            uid += 1
        else:
            if len(flush_heap) >= flush_max or sym in core_syms or sym in flush_syms:
                rejected += 1
                continue
            notional = min(eq*NOTIONAL_CAP, eq*flush_risk/max(stop_pct,1e-6))
            pnl = notional * net_pct
            heapq.heappush(flush_heap, (xt, uid, pnl, sym))
            flush_syms.add(sym)
            flush_acc += 1
            uid += 1

    settle(core_heap, core_syms, 10**30)
    settle(flush_heap, flush_syms, 10**30)

    a = np.asarray(curve, float)
    peak = np.maximum.accumulate(a)
    dd = a/peak - 1
    return {
        "end": float(eq),
        "return": float(eq/START_CAP - 1),
        "max_dd": float(-dd.min()),
        "core_accepted": core_acc,
        "flush_accepted": flush_acc,
        "rejected": rejected
    }

# Core-only equivalent through same combined simulator.
core_only_base = combined_portfolio(CORE_BASE, pd.DataFrame(columns=CORE_BASE.columns), flush_risk=0, flush_max=0)
core_only_stress = combined_portfolio(CORE_STRESS, pd.DataFrame(columns=CORE_STRESS.columns), flush_risk=0, flush_max=0)

passing = R[R.passes_gate].copy()
portfolio_rows = []
for rr in passing.itertuples(index=False):
    b, s = cand_cache[rr.name]
    for risk in [.0005,.0010,.0015,.0020]:
        for mx in [1,2,3]:
            pb = combined_portfolio(CORE_BASE, b, risk, mx)
            ps = combined_portfolio(CORE_STRESS, s, risk, mx)
            improves = bool(
                pb["return"] > core_only_base["return"] and
                ps["return"] > core_only_stress["return"] and
                pb["max_dd"] <= core_only_base["max_dd"] + .05 and
                ps["max_dd"] <= core_only_stress["max_dd"] + .06
            )
            portfolio_rows.append({
                "candidate": rr.name,
                "flush_risk": risk,
                "flush_max": mx,
                "base_return": pb["return"],
                "base_dd": pb["max_dd"],
                "stress_return": ps["return"],
                "stress_dd": ps["max_dd"],
                "base_flush_accepted": pb["flush_accepted"],
                "stress_flush_accepted": ps["flush_accepted"],
                "improves_core": improves
            })

P = pd.DataFrame(portfolio_rows)
if len(P):
    P = P.sort_values(["improves_core","base_return","base_dd"], ascending=[False,False,True])
    P.to_csv(OUT/"core_plus_flush_portfolio_grid.csv", index=False)

selected_rule = passing.iloc[0].to_dict() if len(passing) else None
selected_port = P.iloc[0].to_dict() if len(P) and bool(P.iloc[0].improves_core) else None

summary = {
    "version":"R16.9",
    "project_target_monthly_return":.20,
    "base_flush_event":"ret6<=-7%, volz48>=2, RSI14<=32, body_pos>=.60, S1.25/T2.5/H18",
    "candidate_count": int(len(R)),
    "strict_pass_count": int(R.passes_gate.sum()),
    "selected_rule": selected_rule,
    "top10_rules": R.head(10).to_dict("records"),
    "core_only": {
        "base": core_only_base,
        "stress": core_only_stress
    },
    "selected_core_plus_flush": selected_port,
    "development_cutoff":"2026-07-01",
    "july_august_used":False,
    "notes":[
        "No leverage.",
        "No ML.",
        "CORE remains unchanged and protected.",
        "20% monthly remains a project objective, not a forced selection threshold."
    ]
}
(OUT/"summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
print(json.dumps(summary, indent=2, default=float), flush=True)
