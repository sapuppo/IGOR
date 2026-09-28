#!/usr/bin/env python3
"""R17-OKX-DB24-BTC48-CV1 paper candidates from completed 4h bars only."""
from decimal import Decimal
from datetime import datetime
import statistics

from r17_forward_capture import BAR_MS, CaptureError, number

LOOKBACK = 24
REGIME = 48
MIN_QUOTE_USDT_4H = Decimal('1000000')
MAX_SPREAD = Decimal('0.002')


def signal(history, current, portfolio_equity='10000', open_symbols=(), blocked_symbols=()):
    """Return ranked candidates; never place orders or imply fills/profit."""
    if current.get('schema') != 'IGOR_R17_03_OKX_COHORT_CAPTURE_V1':
        raise CaptureError('snapshot de coorte OKX inválido')
    if current['snapshot_class'] != 'TIMELY_OBSERVATION':
        return {'status': 'SKIP_NOT_TIMELY', 'candidates': []}
    end_ms = int(current['server_time_ms'])
    positions = set(open_symbols)
    blocked = set(blocked_symbols)
    if (len(positions) > 4 or any(s not in current['universe'] for s in positions | blocked)):
        raise CaptureError('estado de carteira inválido')
    bars = {}
    for snap in history:
        if snap.get('universe') != current['universe']:
            raise CaptureError('universo mudou')
        if int(snap['server_time_ms']) > end_ms:
            raise CaptureError('captura futura usada no sinal')
        for symbol, row in snap['observations'].items():
            series = bars.setdefault(symbol, {})
            for candle in row['klines']:
                opened = int(candle[0])
                if opened in series and series[opened] != candle:
                    raise CaptureError('vela duplicada divergente')
                series[opened] = candle
    target = int(datetime.fromisoformat(current['end_exclusive_utc'].replace('Z', '+00:00')).timestamp() * 1000)

    def complete(symbol, length):
        series = bars.get(symbol, {})
        keys = range(target - length * BAR_MS, target, BAR_MS)
        rows = [series.get(k) for k in keys]
        return rows if all(r is not None and len(r) >= 9 and r[8] == '1' for r in rows) else None

    btc = complete('BTC-USDT-SWAP', REGIME)
    if not btc:
        return {'status': 'WARMUP_BTC', 'candidates': []}
    btc_close = number(btc[-1][4], 'BTC.close')
    btc_ma = sum((number(x[4], 'BTC.close') for x in btc), Decimal(0)) / REGIME
    direction = 'BUY' if btc_close > btc_ma else 'SELL' if btc_close < btc_ma else None
    if direction is None:
        return {'status': 'NO_BTC_REGIME', 'candidates': []}
    equity = number(portfolio_equity, 'equity')
    if equity <= 0:
        raise CaptureError('equidade inválida')
    candidates = []
    for symbol in current['universe']:
        if symbol in positions or symbol in blocked:
            continue
        observation = current['observations'][symbol]
        if observation['status'] != 'COMPLETE':
            continue
        rows = complete(symbol, REGIME + 1)
        if not rows:
            continue
        close = number(rows[-1][4], 'close')
        ceiling = max(number(x[2], 'high') for x in rows[-LOOKBACK-1:-1])
        floor = min(number(x[3], 'low') for x in rows[-LOOKBACK-1:-1])
        if ((direction == 'BUY' and close <= ceiling)
                or (direction == 'SELL' and close >= floor)):
            continue
        volume = statistics.median(number(x[7], 'quoteVolume') for x in rows[-6:])
        if volume < MIN_QUOTE_USDT_4H:
            continue
        quote = observation['ticker']
        bid, ask = number(quote['bidPx'], 'bid'), number(quote['askPx'], 'ask')
        mid = (bid + ask) / 2
        if (ask - bid) / mid > MAX_SPREAD or end_ms - int(quote['ts']) > 5000:
            continue
        executable_price = ask if direction == 'BUY' else bid
        top_size = number(quote['askSz'] if direction == 'BUY' else quote['bidSz'], 'topQty')
        instrument = observation['instrument']
        base, quote_ccy, _ = symbol.split('-')
        unit = instrument.get('ctValCcy')
        face = number(instrument['ctVal'], 'ctVal') * number(instrument['ctMult'], 'ctMult')
        if face <= 0 or unit not in (base, quote_ccy):
            continue
        contract_usdt = face * executable_price if unit == base else face
        lot = number(instrument['lotSz'], 'lotSz')
        min_size = number(instrument['minSz'], 'minSz')
        if lot <= 0 or min_size <= 0:
            continue
        # Size at the adverse entry fill, never above the 10% notional cap.
        contracts = (equity * Decimal('0.10') / (contract_usdt * Decimal('1.001')) // lot) * lot
        if contracts < min_size or top_size * contract_usdt < 2 * contracts * contract_usdt:
            continue
        distance = close / ceiling - 1 if direction == 'BUY' else 1 - close / floor
        candidates.append({'symbol': symbol, 'side': direction, 'distance': str(distance),
                           'close': str(close), 'bid': str(bid), 'ask': str(ask),
                           'quote_time_ms': int(quote['ts']), 'signal_time_ms': target,
                           'observed_at_ms': end_ms, 'contracts': str(contracts),
                           'contract_notional_usdt': str(contract_usdt),
                           'entry_notional_usdt': str(contracts * contract_usdt)})
    candidates.sort(key=lambda x: (-Decimal(x['distance']), x['symbol']))
    return {'status': 'PAPER_CANDIDATES_ONLY', 'candidates': candidates[:min(2, 4-len(positions))],
            'funding_net_verified': False, 'live': False}
