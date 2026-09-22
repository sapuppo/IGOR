from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

START = pd.Timestamp("2024-01-01T00:00:00Z")
END_EXCLUSIVE = pd.Timestamp("2026-09-21T00:00:00Z")
INTERVAL = "15m"
BAR_MS = 15 * 60 * 1000
OUT = Path("r13_1_dataset")
RAW15 = OUT / "15m"
TF1H = OUT / "1h"
TF4H = OUT / "4h"

SYMBOLS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","XRPUSDT","SOLUSDT","TRXUSDT","ZECUSDT",
    "DOGEUSDT","LINKUSDT","ADAUSDT","XLMUSDT","UNIUSDT","BCHUSDT","NEARUSDT",
    "AVAXUSDT","LTCUSDT","SUIUSDT","HBARUSDT","TAOUSDT","AAVEUSDT","ENAUSDT",
    "ONDOUSDT","DOTUSDT","ICPUSDT","WLDUSDT","ETCUSDT","POLUSDT","TONUSDT",
    "FILUSDT","ATOMUSDT","INJUSDT","APTUSDT","FETUSDT","RENDERUSDT","PEPEUSDT",
    "ALGOUSDT","VETUSDT","GRTUSDT","RUNEUSDT"
]

COLS = [
    "open_time","open","high","low","close","volume","close_time",
    "quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"
]
KEEP = COLS[:-1]
NUMERIC_FLOAT = [
    "open","high","low","close","volume","quote_volume","taker_buy_base","taker_buy_quote"
]

ARCHIVE_BASE = "https://data.binance.vision/data/spot/monthly/klines"
DAILY_BASE = "https://data.binance.vision/data/spot/daily/klines"
API = "https://api.binance.com/api/v3/klines"

def ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)

def normalize_timestamp(v) -> int:
    x = int(float(v))
    # Binance spot archive switched to microseconds from 2025-01-01.
    if x > 10**14:
        x //= 1000
    return x

def request_bytes(url: str, timeout=45, retries=4) -> bytes | None:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed {url}: {last}")

def zip_to_df(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            return pd.DataFrame(columns=KEEP)
        with z.open(names[0]) as f:
            d = pd.read_csv(f, header=None, names=COLS)
    if d.empty:
        return pd.DataFrame(columns=KEEP)
    d["open_time"] = d["open_time"].map(normalize_timestamp).astype("int64")
    d["close_time"] = d["close_time"].map(normalize_timestamp).astype("int64")
    for c in NUMERIC_FLOAT:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["trades"] = pd.to_numeric(d["trades"], errors="coerce").fillna(0).astype("int64")
    return d[KEEP]

def month_starts(start: pd.Timestamp, end_exclusive: pd.Timestamp):
    first = start.to_period("M").start_time.tz_localize("UTC")
    last_complete = (end_exclusive - pd.Timedelta(days=1)).to_period("M").start_time.tz_localize("UTC")
    cur = first
    while cur < last_complete:
        yield cur
        cur = (cur + pd.offsets.MonthBegin(1)).normalize()

def fetch_archive_month(symbol: str, month: pd.Timestamp) -> pd.DataFrame:
    ym = month.strftime("%Y-%m")
    url = f"{ARCHIVE_BASE}/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{ym}.zip"
    blob = request_bytes(url)
    if blob is None:
        return pd.DataFrame(columns=KEEP)
    return zip_to_df(blob)

def fetch_api_range(symbol: str, start_ms: int, end_ms_exclusive: int) -> pd.DataFrame:
    rows = []
    t = start_ms
    sess = requests.Session()
    while t < end_ms_exclusive:
        params = {
            "symbol": symbol,
            "interval": INTERVAL,
            "startTime": t,
            "endTime": end_ms_exclusive - 1,
            "limit": 1000,
        }
        last = None
        for attempt in range(5):
            try:
                r = sess.get(API, params=params, timeout=30)
                r.raise_for_status()
                a = r.json()
                break
            except Exception as e:
                last = e
                a = None
                time.sleep(1.5 * (attempt + 1))
        if a is None:
            raise RuntimeError(f"REST failed {symbol}: {last}")
        if not a:
            break
        rows.extend(a)
        nxt = int(a[-1][0]) + BAR_MS
        if nxt <= t:
            break
        t = nxt
        if len(a) < 1000:
            break
    if not rows:
        return pd.DataFrame(columns=KEEP)
    d = pd.DataFrame(rows, columns=COLS)
    d["open_time"] = d["open_time"].map(normalize_timestamp).astype("int64")
    d["close_time"] = d["close_time"].map(normalize_timestamp).astype("int64")
    for c in NUMERIC_FLOAT:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["trades"] = pd.to_numeric(d["trades"], errors="coerce").fillna(0).astype("int64")
    return d[KEEP]

def fetch_daily_fallback(symbol: str, start: pd.Timestamp, end_exclusive: pd.Timestamp) -> pd.DataFrame:
    frames = []
    cur = start.normalize()
    while cur < end_exclusive:
        ymd = cur.strftime("%Y-%m-%d")
        url = f"{DAILY_BASE}/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{ymd}.zip"
        blob = request_bytes(url)
        if blob is not None:
            frames.append(zip_to_df(blob))
        cur += pd.Timedelta(days=1)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=KEEP)

def clean_symbol(d: pd.DataFrame) -> pd.DataFrame:
    if d.empty:
        return d
    d = d.copy()
    lo, hi = ms(START), ms(END_EXCLUSIVE)
    d = d[(d.open_time >= lo) & (d.open_time < hi)]
    d = d.drop_duplicates("open_time", keep="last").sort_values("open_time")
    d = d.dropna(subset=["open","high","low","close"])
    return d.reset_index(drop=True)

def audit_15m(d: pd.DataFrame):
    if d.empty:
        return {
            "rows_15m": 0, "first_open": None, "last_open": None, "duplicates": 0,
            "missing_bars_internal": None, "completeness_internal": 0.0,
            "bad_alignment": None, "ohlc_invalid": None
        }
    t = d.open_time.to_numpy(np.int64)
    dif = np.diff(t)
    missing = int(np.maximum(dif // BAR_MS - 1, 0).sum())
    expected = int((t[-1] - t[0]) // BAR_MS + 1)
    bad_align = int(np.sum(t % BAR_MS != 0))
    bad_ohlc = int(((d.high < d[["open","close","low"]].max(axis=1)) |
                    (d.low > d[["open","close","high"]].min(axis=1))).sum())
    return {
        "rows_15m": int(len(d)),
        "first_open": pd.to_datetime(int(t[0]), unit="ms", utc=True).isoformat(),
        "last_open": pd.to_datetime(int(t[-1]), unit="ms", utc=True).isoformat(),
        "duplicates": int(d.open_time.duplicated().sum()),
        "missing_bars_internal": missing,
        "completeness_internal": float(len(d) / expected) if expected else 0.0,
        "bad_alignment": bad_align,
        "ohlc_invalid": bad_ohlc,
    }

def resample_ohlcv(d: pd.DataFrame, tf_ms: int, expected_bars: int) -> pd.DataFrame:
    x = d.copy()
    x["bucket"] = (x.open_time // tf_ms) * tf_ms
    g = x.groupby("bucket", sort=True)
    out = g.agg(
        open=("open","first"),
        high=("high","max"),
        low=("low","min"),
        close=("close","last"),
        volume=("volume","sum"),
        quote_volume=("quote_volume","sum"),
        trades=("trades","sum"),
        taker_buy_base=("taker_buy_base","sum"),
        taker_buy_quote=("taker_buy_quote","sum"),
        source_bars=("open_time","count"),
    ).reset_index().rename(columns={"bucket":"open_time"})
    out = out[out.source_bars == expected_bars].copy()
    out["close_time"] = out.open_time + tf_ms - 1
    return out[[
        "open_time","open","high","low","close","volume","close_time","quote_volume",
        "trades","taker_buy_base","taker_buy_quote","source_bars"
    ]]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def fetch_symbol(symbol: str):
    frames = []
    monthly_count = 0
    for month in month_starts(START, END_EXCLUSIVE):
        q = fetch_archive_month(symbol, month)
        if not q.empty:
            frames.append(q)
            monthly_count += 1

    # Current partial month: 2026-09-01 through 2026-09-20 inclusive.
    partial_start = END_EXCLUSIVE.to_period("M").start_time.tz_localize("UTC")
    try:
        q = fetch_api_range(symbol, ms(partial_start), ms(END_EXCLUSIVE))
        partial_source = "REST"
    except Exception:
        q = fetch_daily_fallback(symbol, partial_start, END_EXCLUSIVE)
        partial_source = "DAILY_ARCHIVE_FALLBACK"
    if not q.empty:
        frames.append(q)

    d = clean_symbol(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=KEEP))
    audit = audit_15m(d)
    audit.update({
        "symbol": symbol,
        "archive_months_found": monthly_count,
        "partial_month_source": partial_source,
    })

    if d.empty:
        audit["status"] = "NO_DATA"
        return audit

    p15 = RAW15 / f"{symbol}.parquet"
    p1 = TF1H / f"{symbol}.parquet"
    p4 = TF4H / f"{symbol}.parquet"
    d.to_parquet(p15, index=False, compression="zstd")
    d1 = resample_ohlcv(d, 60*60*1000, 4)
    d4 = resample_ohlcv(d, 4*60*60*1000, 16)
    d1.to_parquet(p1, index=False, compression="zstd")
    d4.to_parquet(p4, index=False, compression="zstd")

    audit.update({
        "rows_1h": int(len(d1)),
        "rows_4h": int(len(d4)),
        "sha256_15m": sha256(p15),
        "sha256_1h": sha256(p1),
        "sha256_4h": sha256(p4),
        "status": "OK" if audit["missing_bars_internal"] == 0 and audit["duplicates"] == 0 and audit["bad_alignment"] == 0 and audit["ohlc_invalid"] == 0 else "AUDIT_WARNING",
    })
    print(json.dumps(audit, separators=(",",":")), flush=True)
    return audit

def main():
    for p in (OUT, RAW15, TF1H, TF4H):
        p.mkdir(parents=True, exist_ok=True)

    results = []
    # Keep concurrency moderate to avoid hammering Binance's public archive.
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch_symbol, s): s for s in SYMBOLS}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                rec = {"symbol": s, "status": "ERROR", "error": repr(e)}
                print(json.dumps(rec), flush=True)
                results.append(rec)

    coverage = pd.DataFrame(results).sort_values("symbol")
    coverage.to_csv(OUT / "coverage.csv", index=False)

    ok = coverage[coverage.status == "OK"] if "status" in coverage else pd.DataFrame()
    manifest = {
        "version": "V10-R13.1-MTF-DATASET-1",
        "source": "Binance Spot public historical data",
        "base_interval": "15m",
        "derived_intervals": ["1h","4h"],
        "period_start_utc": str(START),
        "period_end_exclusive_utc": str(END_EXCLUSIVE),
        "symbols_requested": SYMBOLS,
        "symbols_requested_n": len(SYMBOLS),
        "symbols_ok_n": int(len(ok)),
        "total_rows_15m_ok": int(ok.rows_15m.sum()) if not ok.empty else 0,
        "total_rows_1h_ok": int(ok.rows_1h.sum()) if not ok.empty else 0,
        "total_rows_4h_ok": int(ok.rows_4h.sum()) if not ok.empty else 0,
        "audit_rule": "No internal missing 15m bars, duplicates, alignment errors, or OHLC invariant violations.",
        "timestamp_note": "Binance archive microsecond timestamps are normalized to milliseconds.",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Inventory hashes for reproducibility.
    inventory = []
    for tf in ("15m","1h","4h"):
        for p in sorted((OUT/tf).glob("*.parquet")):
            inventory.append({"timeframe":tf,"file":str(p.relative_to(OUT)),"bytes":p.stat().st_size,"sha256":sha256(p)})
    pd.DataFrame(inventory).to_csv(OUT/"inventory.csv",index=False)

    with tarfile.open("V10_R13_1_BINANCE_SPOT_MTF_DATASET.tar.gz","w:gz",compresslevel=6) as tar:
        tar.add(OUT, arcname="V10_R13_1_BINANCE_SPOT_MTF_DATASET")

    print("===MANIFEST===")
    print(json.dumps(manifest, separators=(",",":")))
    print("===END_MANIFEST===")

    bad = coverage[coverage.status != "OK"]
    if len(ok) < 35 or not bad.empty:
        # We want the workflow to flag audit failures, but artifacts are still bundled by always().
        raise SystemExit(f"Dataset audit not clean. OK={len(ok)} bad={len(bad)}")

if __name__ == "__main__":
    main()
