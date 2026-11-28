"""Offline normalized L2 capture validation. No exchange or order capability.

Input is a single-symbol JSONL recording, not raw exchange messages. Depth
events contain complete reconstructed books; adapters must verify venue-specific
snapshot/delta synchronization before emitting continuity_verified=true.
"""
import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path


class InvalidFeed(ValueError):
    pass


def integer(value, name):
    if type(value) is not int or value < 0:
        raise InvalidFeed(f'{name}: expected nonnegative integer')
    return value


def number(value, name, *, zero=False):
    # Decimal strings avoid binary-price rounding and reject JSON booleans.
    if not isinstance(value, str):
        raise InvalidFeed(f'{name}: expected decimal string')
    try:
        out = Decimal(value)
    except InvalidOperation as exc:
        raise InvalidFeed(f'{name}: invalid decimal') from exc
    if not out.is_finite() or out < 0 or (not zero and out == 0):
        raise InvalidFeed(f'{name}: invalid sign or nonfinite')
    return out


def levels(rows, side):
    if not isinstance(rows, list) or not rows:
        raise InvalidFeed(f'{side}: empty book')
    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise InvalidFeed('level must be [price, quantity]')
        parsed.append((number(row[0], 'price'), number(row[1], 'quantity')))
    prices = [p for p, _ in parsed]
    if len(set(prices)) != len(prices):
        raise InvalidFeed('duplicate level')
    if prices != sorted(prices, reverse=(side == 'bids')):
        raise InvalidFeed('unsorted levels')
    return parsed


def audit(events, *, max_book_age_ms=1000):
    integer(max_book_age_ms, 'max_book_age_ms')
    if max_book_age_ms == 0:
        raise InvalidFeed('max_book_age_ms must be positive')
    symbol = None
    previous_receive = -1
    sequence = None
    book_received = None
    seen_trades = set()
    counts = Counter()
    spreads = []
    max_delay = 0
    for event in events:
        if not isinstance(event, dict):
            raise InvalidFeed('event must be an object')
        if not isinstance(event.get('symbol'), str) or not event['symbol']:
            raise InvalidFeed('missing symbol')
        symbol = symbol or event['symbol']
        if event['symbol'] != symbol:
            raise InvalidFeed('mixed symbols: audit each stream separately')
        receive = integer(event.get('received_ms'), 'received_ms')
        exchange = integer(event.get('exchange_ms'), 'exchange_ms')
        if receive < previous_receive or exchange > receive:
            raise InvalidFeed('receive order or exchange clock violation')
        # Bounded exchange-to-local clock offset is a prerequisite of capture.
        if receive - exchange > max_book_age_ms:
            raise InvalidFeed('delayed event or unsynchronized capture clock')
        max_delay = max(max_delay, receive - exchange)
        previous_receive = receive
        kind = event.get('type')
        if kind == 'book':
            if event.get('continuity_verified') is not True:
                raise InvalidFeed('venue synchronization not verified')
            seq = integer(event.get('sequence'), 'sequence')
            if sequence is not None:
                if event.get('previous_sequence') != sequence or seq <= sequence:
                    raise InvalidFeed('book sequence gap or duplicate')
            elif event.get('previous_sequence') is not None:
                raise InvalidFeed('first book must start a verified segment')
            bids = levels(event.get('bids'), 'bids')
            asks = levels(event.get('asks'), 'asks')
            if bids[0][0] >= asks[0][0]:
                raise InvalidFeed('locked/crossed book')
            mid = (bids[0][0] + asks[0][0]) / 2
            spreads.append((asks[0][0] - bids[0][0]) / mid * 10000)
            sequence, book_received = seq, receive
        elif kind == 'trade':
            if book_received is None or receive - book_received > max_book_age_ms:
                raise InvalidFeed('trade without fresh prior book')
            trade_id = event.get('trade_id')
            if not isinstance(trade_id, str) or not trade_id or trade_id in seen_trades:
                raise InvalidFeed('missing or duplicate trade id')
            if event.get('aggressor') not in ('buy', 'sell'):
                raise InvalidFeed('unknown aggressor')
            number(event.get('price'), 'price')
            number(event.get('quantity'), 'quantity')
            seen_trades.add(trade_id)
        else:
            raise InvalidFeed('unsupported event type')
        counts[kind] += 1
    if not counts['book'] or not counts['trade']:
        raise InvalidFeed('both depth and trades are required')
    return dict(
        status='CAPTURE_SCHEMA_VALID_ONLY', symbol=symbol, counts=dict(counts),
        max_event_delay_ms=max_delay, max_book_age_ms=max_book_age_ms,
        mean_observed_spread_bps=str(sum(spreads) / len(spreads)),
        orders_sent=0, fills_estimated=0, profit_estimated=False,
        promotion='BLOCKED',
        limitations=[
            'Adapter continuity assertion requires independent venue validation.',
            'L2 does not identify exact queue position or hidden liquidity.',
            'Schema validity does not establish capture completeness or edge.',
            'No fee, funding, latency, adverse-selection or inventory PnL modeled.',
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--max-book-age-ms', type=int, default=1000)
    args = parser.parse_args()
    raw = args.recording.read_bytes()
    try:
        events = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
        result = audit(events, max_book_age_ms=args.max_book_age_ms)
    except (InvalidFeed, ValueError, TypeError, KeyError) as exc:
        result = dict(status='INVALID_CAPTURE', error=str(exc), promotion='BLOCKED', orders_sent=0)
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result['status'] == 'CAPTURE_SCHEMA_VALID_ONLY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
