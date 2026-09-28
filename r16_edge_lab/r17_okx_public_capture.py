#!/usr/bin/env python3
"""Independent read-only OKX BTC-USDT-SWAP market-data pilot; no trading."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from r17_forward_capture import (BAR_MS, ONE_MINUTE, START_PROSPECTIVE,
                                 CaptureError, number, save_snapshot, utc, valid_ts,
                                 verify_chain)
from r17_cloud_capture import next_window

SYMBOL = 'BTC-USDT-SWAP'
PATHS = frozenset({'/api/v5/public/time', '/api/v5/public/instruments',
                   '/api/v5/market/candles', '/api/v5/public/funding-rate-history',
                   '/api/v5/market/ticker', '/api/v5/market/tickers',
                   '/api/v5/market/history-mark-price-candles'})


class PublicOKX:
    def get(self, path, params=None):
        if path not in PATHS:
            raise CaptureError('rota fora da lista pública')
        url = 'https://www.okx.com' + path + ('?' + urlencode(params) if params else '')
        request = Request(url, headers={'User-Agent': 'IGOR-R17-public-pilot/1.0'}, method='GET')
        for attempt in range(3):
            try:
                with urlopen(request, timeout=12) as response:
                    value = json.load(response)
                if value.get('code') != '0' or not isinstance(value.get('data'), list):
                    raise CaptureError(f'OKX rejeitou {path}: {value.get("code")}')
                return value['data']
            except HTTPError as exc:
                if attempt == 2 or exc.code not in (429, 500, 502, 503, 504):
                    raise CaptureError(f'OKX HTTP {exc.code} em {path}') from exc
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise CaptureError(f'OKX indisponível em {path}') from exc
            time.sleep(attempt + 1)
        raise AssertionError('limite de tentativas')


def capture(client, start_ms, end_ms, clock_ms=None, source_sha=None):
    local_start = int(time.time() * 1000) if clock_ms is None else clock_ms
    start_time = client.get('/api/v5/public/time')
    server_start = valid_ts(start_time[0]['ts'], 'OKX.time')
    if abs(server_start - local_start) > 5000:
        raise CaptureError('relógio local divergente')
    if start_ms % BAR_MS or end_ms % BAR_MS or start_ms >= end_ms:
        raise CaptureError('janela 4h inválida')
    if end_ms > (server_start - ONE_MINUTE) // BAR_MS * BAR_MS:
        raise CaptureError('vela ainda não fechou')
    info = client.get('/api/v5/public/instruments', {'instType': 'SWAP'})
    instruments = [s for s in info if s.get('instId') == SYMBOL]
    if len(instruments) != 1:
        raise CaptureError('contrato piloto ausente ou duplicado')
    instrument = instruments[0]
    candles = client.get('/api/v5/market/candles', {'instId': SYMBOL, 'bar': '4H', 'limit': '100'})
    funding = client.get('/api/v5/public/funding-rate-history', {'instId': SYMBOL, 'limit': '100'})
    quote = client.get('/api/v5/market/ticker', {'instId': SYMBOL})
    end_time = client.get('/api/v5/public/time')
    server_end = valid_ts(end_time[0]['ts'], 'OKX.time final')
    local_end = int(time.time() * 1000) if clock_ms is None else clock_ms
    if server_end < server_start or abs(server_end - local_end) > 5000:
        raise CaptureError('relógio final divergente')
    problems = []
    if instrument.get('state') != 'live' or instrument.get('ctType') != 'linear':
        problems.append('NOT_LIVE_LINEAR_SWAP')
    selected = sorted((row for row in candles if start_ms <= valid_ts(row[0], 'candle.ts') < end_ms),
                      key=lambda row: int(row[0]))
    if [int(row[0]) for row in selected] != list(range(start_ms, end_ms, BAR_MS)):
        problems.append('CANDLE_GAP')
    for row in selected:
        if len(row) < 9 or row[8] != '1':
            problems.append('UNCONFIRMED_CANDLE')
            continue
        opening, high, low, close = (number(x, 'OHLC') for x in row[1:5])
        if min(opening, high, low, close) <= 0 or high < max(opening, close) or low > min(opening, close):
            problems.append('INVALID_OHLC')
    selected_funding = sorted((row for row in funding if start_ms <= valid_ts(row['fundingTime'], 'fundingTime') < end_ms),
                              key=lambda row: int(row['fundingTime']))
    for row in selected_funding:
        if row.get('instId') != SYMBOL:
            problems.append('FUNDING_SYMBOL_MISMATCH')
        number(row.get('realizedRate') or row['fundingRate'], 'fundingRate')
    if end_ms - start_ms >= 24 * 60 * ONE_MINUTE and not selected_funding:
        problems.append('FUNDING_EMPTY_OVER_24H')
    if len(quote) != 1 or quote[0].get('instId') != SYMBOL:
        raise CaptureError('ticker ausente ou divergente')
    q = quote[0]
    bid, ask = number(q['bidPx'], 'bid'), number(q['askPx'], 'ask')
    if bid <= 0 or ask < bid or number(q['bidSz'], 'bidSz') <= 0 or number(q['askSz'], 'askSz') <= 0:
        problems.append('INVALID_BOOK')
    quote_ms = valid_ts(q['ts'], 'ticker.ts')
    if quote_ms > server_end or server_end - quote_ms > 5000:
        problems.append('STALE_BOOK')
    timely = 0 <= server_end - end_ms <= 10 * ONE_MINUTE
    klass = ('TIMELY_OBSERVATION' if timely and start_ms >= START_PROSPECTIVE and end_ms-start_ms == BAR_MS
             else 'MIXED_BACKFILL_AND_TIMELY_QUOTE' if timely else 'RETROSPECTIVE_BACKFILL')
    return {'schema': 'IGOR_R17_02_OKX_SOURCE_PILOT_V1', 'venue': 'OKX',
            'universe': [SYMBOL], 'source_sha256': source_sha,
            'start_utc': utc(start_ms), 'end_exclusive_utc': utc(end_ms),
            'server_time_ms': server_end, 'local_started_ms': local_start,
            'local_received_ms': local_end, 'snapshot_class': klass,
            'status': 'COMPLETE' if not problems else 'INCOMPLETE',
            'problems': problems, 'oos_validated': False, 'live': False,
            'observations': {SYMBOL: {'instrument': instrument, 'klines': selected,
                                      'funding': selected_funding, 'ticker': q}},
            'source_response': {'server_start': start_time, 'server_end': end_time}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args()
    window = next_window(args.out_dir, int(time.time() * 1000))
    if window is None:
        print('OKX pilot window already captured')
        return
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    value = capture(PublicOKX(), *window, source_sha=source_sha)
    path = save_snapshot(args.out_dir, value)
    print(json.dumps({'path': str(path), 'status': value['status'],
                      'class': value['snapshot_class'], 'problems': value['problems']}))
    print(json.dumps(verify_chain(args.out_dir)))


if __name__ == '__main__':
    main()
