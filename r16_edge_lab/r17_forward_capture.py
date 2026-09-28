#!/usr/bin/env python3
"""Read-only USD-M market observation with tamper-evident local snapshots.

No account credentials, signed requests, order endpoints or trade execution.
Run `collect` in a networked environment; `verify` checks the local hash chain.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BAR_MS = 14_400_000
ONE_MINUTE = 60_000
QUOTE_MAX_AGE_MS = 5_000
START_PROSPECTIVE = 1790640000000  # 2026-09-29 00:00 UTC
MANIFEST_SHA = 'a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041'
UNIVERSE_FILE_SHA = '87099ccc30eb68b3d18b5902accab599280f17a9b587fcacf8242ee142e83d53'
PATHS = frozenset({'/fapi/v1/time', '/fapi/v1/klines', '/fapi/v1/fundingRate',
                   '/fapi/v1/ticker/bookTicker', '/fapi/v1/exchangeInfo'})


class CaptureError(ValueError):
    pass


def number(value, name):
    try:
        v = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise CaptureError(f'{name}: número inválido') from exc
    if not v.is_finite():
        raise CaptureError(f'{name}: número não finito')
    return v


def valid_ts(value, name):
    if isinstance(value, bool) or not str(value).isdigit():
        raise CaptureError(f'{name}: timestamp inválido')
    return int(value)


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace('+00:00', 'Z')


class PublicUSDm:
    """Strict GET-only endpoint allowlist; transport injectable for offline tests."""

    def __init__(self, timeout=12):
        self.timeout = timeout

    def get(self, path, params=None):
        if path not in PATHS:
            raise CaptureError(f'endpoint não permitido: {path}')
        query = '?' + urlencode(params) if params else ''
        req = Request('https://fapi.binance.com' + path + query,
                      headers={'User-Agent': 'IGOR-R17-readonly/1.0'}, method='GET')
        for attempt in range(3):
            try:
                with urlopen(req, timeout=self.timeout) as stream:
                    return json.load(stream)
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise CaptureError(f'HTTP {exc.code} em {path}') from exc
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise CaptureError(f'API pública indisponível: {path}') from exc
            time.sleep(min(2 ** attempt, 2))
        raise AssertionError('limite de tentativas')


def fixed_universe(manifest_path):
    raw = Path(manifest_path).read_bytes()
    manifest = json.loads(raw)
    if manifest.get('schema') == 'IGOR_R17_01_FROZEN_UNIVERSE_V1':
        if hashlib.sha256(raw).hexdigest() != UNIVERSE_FILE_SHA or manifest.get('source_manifest_sha256') != MANIFEST_SHA:
            raise CaptureError('lista congelada foi modificada')
        universe = manifest['symbols']
    else:
        if manifest.get('dataset_manifest_sha256') != MANIFEST_SHA:
            raise CaptureError('manifesto histórico divergente')
        universe = sorted(s['symbol'] for s in manifest['symbols'] if s['eligible'])
    if len(universe) != 38 or len(set(universe)) != 38:
        raise CaptureError('coorte de observação incompleta')
    return universe


def capture_batch(client, symbols, start_ms, end_ms, clock_ms=None, source_sha=None):
    if not symbols or len(set(symbols)) != len(symbols):
        raise CaptureError('universo vazio ou repetido')
    started_at_ms = int(time.time() * 1000) if clock_ms is None else clock_ms
    server = client.get('/fapi/v1/time')
    first_server_ms = valid_ts(server['serverTime'], 'serverTime')
    if abs(first_server_ms - started_at_ms) > QUOTE_MAX_AGE_MS:
        raise CaptureError('diferença entre relógio local e servidor >5 s')
    if start_ms is None:
        start_ms = (first_server_ms - 32 * 24 * 60 * ONE_MINUTE) // BAR_MS * BAR_MS
    if end_ms is None:
        end_ms = (first_server_ms - ONE_MINUTE) // BAR_MS * BAR_MS
    if start_ms % BAR_MS or end_ms % BAR_MS or start_ms >= end_ms:
        raise CaptureError('intervalo 4h inválido')
    if end_ms > (first_server_ms - ONE_MINUTE) // BAR_MS * BAR_MS:
        raise CaptureError('candle ainda em formação ou buffer de 60 s ausente')
    expected = list(range(start_ms, end_ms, BAR_MS))
    if len(expected) > 1500:
        raise CaptureError('intervalo maior que uma página; dividir em janelas')
    exchange = client.get('/fapi/v1/exchangeInfo')
    exchange_symbols = {s['symbol']: s for s in exchange['symbols']}
    statuses = {symbol: info.get('status') for symbol, info in exchange_symbols.items()}
    raw = {}
    for symbol in symbols:
        klines = client.get('/fapi/v1/klines', {
            'symbol': symbol, 'interval': '4h', 'startTime': start_ms,
            'endTime': end_ms - 1, 'limit': 1500})
        funding = client.get('/fapi/v1/fundingRate', {
            'symbol': symbol, 'startTime': start_ms, 'endTime': end_ms - 1, 'limit': 1000})
        raw[symbol] = (klines, funding)
    # Collect the book only after the slower historical requests. A final server
    # timestamp lets us reject quotes already stale at observation time.
    quote_started = time.monotonic_ns()
    quotes_raw = client.get('/fapi/v1/ticker/bookTicker')
    quote_rtt_ms = (time.monotonic_ns() - quote_started) / 1_000_000
    final_server_ms = valid_ts(client.get('/fapi/v1/time')['serverTime'], 'serverTime final')
    received_at_ms = int(time.time() * 1000) if clock_ms is None else clock_ms
    if final_server_ms < first_server_ms or abs(final_server_ms - received_at_ms) > QUOTE_MAX_AGE_MS:
        raise CaptureError('relógio final divergente ou regressivo')
    if not isinstance(quotes_raw, list):
        raise CaptureError('bookTicker de universo inteiro deve ser array')
    quotes = {q['symbol']: q for q in quotes_raw}
    if len(quotes) != len(quotes_raw):
        raise CaptureError('bookTicker repetido')
    result = {}
    problems = []
    for symbol in symbols:
        raw_klines, raw_funding = raw[symbol]
        if not isinstance(raw_klines, list) or not isinstance(raw_funding, list):
            raise CaptureError(f'resposta de mercado inválida: {symbol}')
        symbol_errors = []
        if statuses.get(symbol) != 'TRADING':
            symbol_errors.append('NOT_TRADING')
        seen_bars = []
        for row in raw_klines:
            if not isinstance(row, list) or len(row) < 11:
                raise CaptureError(f'kline truncada: {symbol}')
            opened, closed = valid_ts(row[0], 'openTime'), valid_ts(row[6], 'closeTime')
            seen_bars.append(opened)
            if closed != opened + BAR_MS - 1 or closed >= first_server_ms - ONE_MINUTE:
                raise CaptureError(f'candle não consolidado: {symbol} {opened}')
            price = [number(row[j], f'{symbol} OHLC') for j in (1, 2, 3, 4)]
            if min(price) <= 0 or price[1] < max(price) or price[2] > min(price):
                raise CaptureError(f'OHLC inválido: {symbol} {opened}')
            if number(row[7], 'quoteVolume') < 0:
                raise CaptureError(f'volume inválido: {symbol} {opened}')
        if seen_bars != expected:
            symbol_errors.append('CANDLE_GAP_OR_PAGE_MISMATCH')
        funding_times = []
        for row in raw_funding:
            when = valid_ts(row['fundingTime'], 'fundingTime')
            funding_times.append(when)
            if row['symbol'] != symbol or not start_ms <= when < end_ms or when >= first_server_ms - ONE_MINUTE:
                raise CaptureError(f'funding fora da janela: {symbol}')
            if row.get('markPrice') in ('', None) or number(row['markPrice'], 'markPrice') <= 0:
                symbol_errors.append('FUNDING_MARK_MISSING')
            number(row['fundingRate'], 'fundingRate')
        if funding_times != sorted(set(funding_times)):
            raise CaptureError(f'funding repetido ou desordenado: {symbol}')
        if len(raw_funding) == 1000:
            symbol_errors.append('FUNDING_PAGE_LIMIT')
        # A four-hour capture can legitimately have no funding settlement.
        # An empty full-day window is an actionable data-quality gap.
        if not raw_funding and statuses.get(symbol) == 'TRADING' and end_ms - start_ms >= 24 * 60 * ONE_MINUTE:
            symbol_errors.append('FUNDING_EMPTY')
        if raw_funding and statuses.get(symbol) == 'TRADING':
            intervals = [funding_times[0] - start_ms,
                         *(b - a for a, b in zip(funding_times, funding_times[1:])),
                         end_ms - funding_times[-1]]
            if max(intervals) > 24 * 60 * ONE_MINUTE:
                symbol_errors.append('FUNDING_GAP_OVER_24H')
        q = quotes.get(symbol)
        if q is None:
            symbol_errors.append('QUOTE_MISSING')
        else:
            bid, ask = number(q['bidPrice'], 'bidPrice'), number(q['askPrice'], 'askPrice')
            if bid <= 0 or ask < bid or number(q['bidQty'], 'bidQty') <= 0 or number(q['askQty'], 'askQty') <= 0:
                symbol_errors.append('QUOTE_INVALID')
            quote_ms = valid_ts(q['time'], 'bookTicker.time')
            if quote_ms > final_server_ms or final_server_ms - quote_ms > QUOTE_MAX_AGE_MS:
                symbol_errors.append('QUOTE_STALE_OR_FUTURE')
        result[symbol] = {'status': 'COMPLETE' if not symbol_errors else 'INVALID',
                          'problems': symbol_errors, 'klines': raw_klines,
                          'funding': raw_funding, 'book_ticker': q,
                          'exchange_symbol': exchange_symbols.get(symbol)}
        problems.extend(f'{symbol}:{name}' for name in symbol_errors)
    last_candle_end = end_ms
    timely = (first_server_ms >= START_PROSPECTIVE and 0 <= final_server_ms - last_candle_end <= 10 * ONE_MINUTE)
    capture_class = ('TIMELY_OBSERVATION' if timely and start_ms >= START_PROSPECTIVE and end_ms - start_ms == BAR_MS
                     else 'MIXED_BACKFILL_AND_TIMELY_QUOTE' if timely
                     else 'RETROSPECTIVE_BACKFILL')
    return {'schema': 'IGOR_R17_01_MARKET_CAPTURE_V1', 'start_utc': utc(start_ms),
            'end_exclusive_utc': utc(end_ms), 'server_time_ms': final_server_ms,
            'server_start_ms': first_server_ms, 'local_started_ms': started_at_ms,
            'local_received_ms': received_at_ms, 'book_ticker_rtt_ms': quote_rtt_ms,
            'source_sha256': source_sha, 'universe': list(symbols),
            'snapshot_class': capture_class, 'oos_validated': False, 'live': False,
            'status': 'COMPLETE' if not problems else 'INCOMPLETE',
            'problems': problems, 'observations': result}


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def verify_chain(directory):
    files = sorted(Path(directory).glob('capture-*.json'))
    previous = None
    last_time = 0
    source_sha = None
    universe_sha = None
    for path in files:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw)
        stamp = valid_ts(value['server_time_ms'], 'serverTime')
        if path.name != f'capture-{stamp}-{digest[:16]}.json':
            raise CaptureError(f'hash do arquivo divergente: {path.name}')
        if value.get('previous_file_sha256') != previous or stamp <= last_time:
            raise CaptureError('cadeia de hashes ou ordem temporal inválida')
        if raw != canonical_bytes(value):
            raise CaptureError('captura fora da serialização canônica')
        code = value.get('source_sha256')
        cohort = hashlib.sha256(canonical_bytes(value['universe'])).hexdigest()
        if source_sha is not None and code != source_sha:
            raise CaptureError('código do coletor mudou durante a cadeia')
        if universe_sha is not None and cohort != universe_sha:
            raise CaptureError('universo mudou durante a cadeia')
        source_sha, universe_sha = code, cohort
        previous = digest
        last_time = stamp
    return {'snapshots': len(files), 'last_sha256': previous, 'last_server_time_ms': last_time,
            'source_sha256': source_sha, 'universe_sha256': universe_sha}


def save_snapshot(directory, snapshot):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / 'capture.lock'
    try:
        with lock.open('xb'):
            pass
    except FileExistsError as exc:
        raise CaptureError('outra captura está em andamento; sem escrita concorrente') from exc
    try:
        state = verify_chain(root)
        stamp = snapshot['server_time_ms']
        if stamp <= state['last_server_time_ms']:
            raise CaptureError('carimbo anterior à última captura; sem sobrescrita')
        if state['snapshots']:
            if snapshot.get('source_sha256') != state['source_sha256']:
                raise CaptureError('código alterado; iniciar nova cadeia de pesquisa')
            if hashlib.sha256(canonical_bytes(snapshot['universe'])).hexdigest() != state['universe_sha256']:
                raise CaptureError('universo alterado; iniciar nova cadeia de pesquisa')
        value = dict(snapshot, previous_file_sha256=state['last_sha256'])
        raw = canonical_bytes(value)
        digest = hashlib.sha256(raw).hexdigest()
        path = root / f'capture-{stamp}-{digest[:16]}.json'
        tmp = root / (path.name + '.tmp')
        try:
            with tmp.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                raise CaptureError('arquivo repetido')
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        verify_chain(root)
        return path
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['collect', 'verify'])
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--manifest', help='R17_01_UNIVERSE.json ou manifest.json R16.29.2')
    parser.add_argument('--start-ms', type=int)
    parser.add_argument('--end-ms', type=int)
    args = parser.parse_args()
    if args.action == 'verify':
        print(json.dumps(verify_chain(args.out_dir), ensure_ascii=False))
        return
    if not args.manifest:
        parser.error('--manifest necessário para collect')
    symbols = fixed_universe(args.manifest)
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    snapshot = capture_batch(PublicUSDm(), symbols, args.start_ms, args.end_ms, source_sha=code_sha)
    path = save_snapshot(args.out_dir, snapshot)
    print(json.dumps({'path': str(path), 'status': snapshot['status'],
                      'class': snapshot['snapshot_class'], 'problems': snapshot['problems']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
