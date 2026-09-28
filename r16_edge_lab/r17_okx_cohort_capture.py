#!/usr/bin/env python3
"""Read-only 35-symbol OKX USDT-swap observation; no account or trading code."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from r17_cloud_capture import next_window
from r17_forward_capture import (BAR_MS, ONE_MINUTE, START_PROSPECTIVE,
                                 CaptureError, number, save_snapshot, utc, valid_ts,
                                 verify_chain)
from r17_okx_public_capture import PublicOKX

MANIFEST_SHA = '6cbd8423bd4a5bb860aa9cd497720c28960540008efe237e8a9c95fc9daea5b9'
SOURCE_SHA = '87099ccc30eb68b3d18b5902accab599280f17a9b587fcacf8242ee142e83d53'


def fixed_universe(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if (hashlib.sha256(raw).hexdigest() != MANIFEST_SHA
            or value.get('schema') != 'IGOR_R17_03_OKX_FROZEN_UNIVERSE_V1'
            or value.get('source_binance_universe_sha256') != SOURCE_SHA):
        raise CaptureError('manifesto OKX congelado foi alterado')
    mapping = value['symbols']
    symbols = list(mapping.values())
    if len(symbols) != 35 or len(set(symbols)) != 35:
        raise CaptureError('coorte OKX inválida')
    return symbols


def capture(client, symbols, start_ms, end_ms, clock_ms=None, source_sha=None):
    if not symbols or len(set(symbols)) != len(symbols):
        raise CaptureError('coorte vazia ou repetida')
    local_start = int(time.time() * 1000) if clock_ms is None else clock_ms
    initial_time = client.get('/api/v5/public/time')
    server_start = valid_ts(initial_time[0]['ts'], 'OKX.time')
    if abs(server_start - local_start) > 5000:
        raise CaptureError('relógio local divergente')
    if start_ms % BAR_MS or end_ms % BAR_MS or start_ms >= end_ms or end_ms - start_ms > 24 * 60 * ONE_MINUTE:
        raise CaptureError('janela 4h inválida')
    if end_ms > (server_start - ONE_MINUTE) // BAR_MS * BAR_MS:
        raise CaptureError('vela ainda não fechou')
    expected = list(range(start_ms, end_ms, BAR_MS))
    instruments_raw = client.get('/api/v5/public/instruments', {'instType': 'SWAP'})
    instruments = {x['instId']: x for x in instruments_raw}
    data = {}
    for symbol in symbols:
        instrument = instruments.get(symbol)
        if instrument is None or instrument.get('state') != 'live' or instrument.get('ctType') != 'linear':
            data[symbol] = ([], [], instrument)
            continue
        candles = client.get('/api/v5/market/candles', {'instId': symbol, 'bar': '4H', 'limit': '100'})
        funding = client.get('/api/v5/public/funding-rate-history', {'instId': symbol, 'limit': '100'})
        data[symbol] = (candles, funding, instrument)
        # Stay below the documented public request budget across shared runners.
        if clock_ms is None:
            time.sleep(0.12)
    quote_started = time.monotonic_ns()
    quotes_raw = client.get('/api/v5/market/tickers', {'instType': 'SWAP'})
    quote_rtt_ms = (time.monotonic_ns() - quote_started) / 1_000_000
    final_time = client.get('/api/v5/public/time')
    server_end = valid_ts(final_time[0]['ts'], 'OKX.time final')
    local_end = int(time.time() * 1000) if clock_ms is None else clock_ms
    if server_end < server_start or abs(server_end - local_end) > 5000:
        raise CaptureError('relógio final divergente')
    if len(quotes_raw) != len({q['instId'] for q in quotes_raw}):
        raise CaptureError('tickers duplicados')
    quotes = {q['instId']: q for q in quotes_raw}
    problems, observations = [], {}
    for symbol in symbols:
        candles, funding, instrument = data[symbol]
        issues = []
        if instrument is None or instrument.get('state') != 'live' or instrument.get('ctType') != 'linear':
            issues.append('NOT_LIVE_LINEAR_SWAP')
        selected = sorted((r for r in candles if start_ms <= valid_ts(r[0], 'candle.ts') < end_ms),
                          key=lambda r: int(r[0]))
        if [int(row[0]) for row in selected] != expected:
            issues.append('CANDLE_GAP')
        for row in selected:
            if len(row) < 9 or row[8] != '1':
                issues.append('UNCONFIRMED_CANDLE')
                continue
            op, high, low, close = (number(x, 'OHLC') for x in row[1:5])
            if min(op, high, low, close) <= 0 or high < max(op, close) or low > min(op, close):
                issues.append('INVALID_OHLC')
        selected_funding = sorted((r for r in funding if start_ms <= valid_ts(r['fundingTime'], 'fundingTime') < end_ms),
                                  key=lambda r: int(r['fundingTime']))
        for row in selected_funding:
            if row.get('instId') != symbol:
                issues.append('FUNDING_SYMBOL_MISMATCH')
            number(row.get('realizedRate') or row['fundingRate'], 'fundingRate')
        if end_ms - start_ms >= 24 * 60 * ONE_MINUTE and not selected_funding and instrument is not None:
            issues.append('FUNDING_EMPTY_OVER_24H')
        quote = quotes.get(symbol)
        if quote is None:
            issues.append('QUOTE_MISSING')
        else:
            bid, ask = number(quote['bidPx'], 'bid'), number(quote['askPx'], 'ask')
            if bid <= 0 or ask < bid or number(quote['bidSz'], 'bidSz') <= 0 or number(quote['askSz'], 'askSz') <= 0:
                issues.append('INVALID_BOOK')
            quote_ms = valid_ts(quote['ts'], 'ticker.ts')
            if quote_ms > server_end or server_end - quote_ms > 5000:
                issues.append('STALE_BOOK')
        observations[symbol] = {'status': 'COMPLETE' if not issues else 'INVALID',
                                'problems': issues, 'instrument': instrument,
                                'klines': selected, 'funding': selected_funding, 'ticker': quote}
        problems.extend(f'{symbol}:{x}' for x in issues)
    timely = 0 <= server_end - end_ms <= 10 * ONE_MINUTE
    klass = ('TIMELY_OBSERVATION' if timely and start_ms >= START_PROSPECTIVE and len(expected) == 1
             else 'MIXED_BACKFILL_AND_TIMELY_QUOTE' if timely else 'RETROSPECTIVE_BACKFILL')
    return {'schema': 'IGOR_R17_03_OKX_COHORT_CAPTURE_V1', 'venue': 'OKX',
            'universe': list(symbols), 'manifest_sha256': MANIFEST_SHA,
            'source_sha256': source_sha, 'start_utc': utc(start_ms),
            'end_exclusive_utc': utc(end_ms), 'server_time_ms': server_end,
            'local_started_ms': local_start, 'local_received_ms': local_end,
            'quote_rtt_ms': quote_rtt_ms, 'snapshot_class': klass,
            'status': 'COMPLETE' if not problems else 'INCOMPLETE',
            'problems': problems, 'oos_validated': False, 'live': False,
            'observations': observations,
            'source_response': {'server_start': initial_time, 'server_end': final_time}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args()
    window = next_window(args.out_dir, int(time.time() * 1000))
    if window is None:
        print(json.dumps({'status': 'SKIPPED', 'reason': 'janela já capturada'}))
        return
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    value = capture(PublicOKX(), fixed_universe(args.manifest), *window, source_sha=source_sha)
    path = save_snapshot(args.out_dir, value)
    print(json.dumps({'path': str(path), 'status': value['status'],
                      'class': value['snapshot_class'], 'problems': value['problems']}))
    print(json.dumps(verify_chain(args.out_dir)))


if __name__ == '__main__':
    main()
