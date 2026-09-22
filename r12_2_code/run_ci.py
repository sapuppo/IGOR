from pathlib import Path
import pandas as pd
import numpy as np

import run_r12_2_extended_calibration as r

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "r12_2_data"

def load_4h_universe(symbols, workers=8):
    data = {}
    skipped = {}
    for symbol in symbols:
        p = DATA / f"{symbol}.csv"
        if not p.exists():
            skipped[symbol] = "NO_SPOT_DATA_FILE"
            continue
        d = pd.read_csv(p)
        if d.empty:
            skipped[symbol] = "EMPTY_RANGE"
            continue
        d["open_time"] = pd.to_datetime(d["open_time"], unit="ms", utc=True)
        # Binance 4h klines are labeled by open time. The original R12 pipeline
        # resampled 1h bars with label='right', so shift to the 4h close boundary.
        d.index = d["open_time"] + pd.Timedelta(hours=4)
        d = d[["open","high","low","close","volume","quote_volume"]].apply(pd.to_numeric, errors="coerce")
        d = d.dropna(subset=["open","high","low","close"]).sort_index()
        d = d[~d.index.duplicated(keep="last")]
        if d.empty:
            skipped[symbol] = "EMPTY_AFTER_PARSE"
            continue
        span = (d.index.max() - d.index.min()).total_seconds() / 86400.0
        expected = int((d.index.max() - d.index.min()) / pd.Timedelta(hours=4)) + 1
        completeness = len(d) / expected if expected > 0 else 0.0
        if span < 300:
            skipped[symbol] = f"INSUFFICIENT_HISTORY_{span:.0f}d"
            continue
        if completeness < 0.999:
            skipped[symbol] = f"4H_COMPLETENESS_{completeness:.5f}"
            continue
        data[symbol] = d
        print(f"DATA4H {symbol} rows={len(d)} from={d.index.min()} to={d.index.max()} completeness={completeness:.6f}", flush=True)
    return data, skipped

def identity_resample(data, tf):
    if tf != "4h":
        raise RuntimeError(f"R12.2 CI bridge only supports frozen timeframe 4h, got {tf}")
    return data

r.download_universe = load_4h_universe
r.resample_universe = identity_resample

if __name__ == "__main__":
    r.main()
