#!/usr/bin/env python3
"""R17-CSMOM-W1: causal weekly long/short signal generator, research only.

This script does not calculate returns, place orders or infer funding prices.
"""
import argparse
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

HOUR_MS = 3_600_000
BAR_MS = 4 * HOUR_MS
WEEK_MS = 7 * 24 * HOUR_MS
MIN_4H_BARS = 28 * 6
MEDIAN_MIN_USDT = 5_000_000
ROOT_HASH = 'a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041'


def parse_ms(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.utcoffset() != timedelta(0):
        raise ValueError('timestamp deve ser UTC')
    return int(dt.timestamp() * 1000)


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace('+00:00', 'Z')


def verified_history(root):
    root = Path(root)
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest['dataset_manifest_sha256'] != ROOT_HASH:
        raise ValueError('manifesto divergente do pré-registro')
    if len(manifest['files']) != 152:
        raise ValueError('conjunto de entrada incompleto')
    data = {}
    for entry in manifest['files']:
        rel = ('funding' if entry['kind'] == 'funding' else 'klines/' + entry['interval'])
        path = root / rel / f"{entry['symbol']}.csv.gz"
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f"sha256 divergente: {entry['symbol']} {rel}")
        if entry['kind'] != 'kline' or entry['interval'] != '4h':
            continue
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            df = pd.read_csv(stream, usecols=['open_time', 'open', 'high', 'low', 'close', 'quote_volume'])
        if not df['open_time'].is_monotonic_increasing or df['open_time'].duplicated().any():
            raise ValueError(f"velas desordenadas: {entry['symbol']}")
        if (df[['open', 'high', 'low', 'close']] <= 0).any().any() or (df['quote_volume'] < 0).any():
            raise ValueError(f"valores negativos: {entry['symbol']}")
        if (df['high'] < df[['open', 'close', 'low']].max(axis=1)).any() or (df['low'] > df[['open', 'close', 'high']].min(axis=1)).any():
            raise ValueError(f"OHLC incoerente: {entry['symbol']}")
        if pd.isna(df[['open_time', 'open', 'high', 'low', 'close', 'quote_volume']]).any().any():
            raise ValueError(f"NaN: {entry['symbol']}")
        data[entry['symbol']] = df.set_index('open_time')
    eligible = {x['symbol'] for x in manifest['symbols'] if x['eligible']}
    if len(eligible) != 38 or not eligible.issubset(data):
        raise ValueError('coorte de 38 símbolos inválida')
    return {k: data[k] for k in sorted(eligible)}


def rank_week(data, signal_ms):
    """Only completed bars ending <= signal_ms are read; fill is +4h."""
    if datetime.fromtimestamp(signal_ms / 1000, timezone.utc).weekday() != 0 or signal_ms % (24 * HOUR_MS):
        raise ValueError('o sinal deve cair segunda-feira às 00:00 UTC')
    last_open = signal_ms - BAR_MS
    required = [last_open - j * BAR_MS for j in range(MIN_4H_BARS - 1, -1, -1)]
    ranks = []
    for symbol, frame in data.items():
        lookback = frame.reindex(required)
        if lookback.isna().any().any():
            continue
        if lookback['quote_volume'].iloc[-42:].median() < MEDIAN_MIN_USDT:
            continue
        closes = lookback['close'].to_numpy()
        score = float(closes[-1] / closes[-43] - 1)
        ranks.append((symbol, score, float(lookback['quote_volume'].iloc[-42:].median())))
    if len(ranks) < 20:
        return {'signal_utc': iso(signal_ms), 'fill_open_utc': iso(signal_ms + BAR_MS),
                'eligible': len(ranks), 'status': 'SKIP_INSUFFICIENT_SYMBOLS', 'legs': []}
    # descending score, ascending symbol as a deterministic tie break
    ranks.sort(key=lambda x: (-x[1], x[0]))
    picks = [('BUY', row) for row in ranks[:2]] + [('SELL', row) for row in ranks[-2:]]
    return {'signal_utc': iso(signal_ms), 'fill_open_utc': iso(signal_ms + BAR_MS),
            'eligible': len(ranks), 'status': 'RESEARCH_SIGNAL',
            'legs': [{'side': side, 'symbol': symbol, 'ret_7d': score,
                      'median_4h_quote_usdt': median} for side, (symbol, score, median) in picks]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--start', default='2023-11-06T00:00:00Z')
    parser.add_argument('--end-exclusive', default='2026-07-01T00:00:00Z')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    data = verified_history(args.root)
    start = parse_ms(args.start)
    end = parse_ms(args.end_exclusive)
    if start >= end:
        raise ValueError('intervalo inválido')
    weeks = list(range(start, end, WEEK_MS))
    signals = [rank_week(data, ms) for ms in weeks]
    result = {'candidate': 'R17-CSMOM-W1', 'purpose': 'retrospective signal diagnostics; not PnL',
              'data_sha256': ROOT_HASH, 'research_window': [args.start, args.end_exclusive],
              'weeks': len(weeks), 'signal_weeks': sum(x['status'] == 'RESEARCH_SIGNAL' for x in signals),
              'skipped_weeks': sum(x['status'] != 'RESEARCH_SIGNAL' for x in signals),
              'signals': signals, 'oos_validated': False, 'live': False}
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(f"weeks={result['weeks']} signals={result['signal_weeks']} skips={result['skipped_weeks']}")


if __name__ == '__main__':
    main()
