#!/usr/bin/env python3
"""R17-CSMOM-W1 retrospective diagnostics with exact archived funding marks.

Research only. Bars do not reveal the order of an intrabar stop and funding;
those ambiguous candles are counted and block technical validation.
"""
import argparse
from bisect import bisect_left
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import zipfile

from r17_candidate_signals import BAR_MS, WEEK_MS, iso, parse_ms, rank_week, verified_history

START = parse_ms('2023-11-01T00:00:00Z')
END = parse_ms('2026-07-01T00:00:00Z')
WEEK_ZERO = parse_ms('2023-11-06T00:00:00Z')
STOP_PCT = .04
LEG_WEIGHT = .15
SCENARIOS = {'BASE': (.0004, .0002), 'STRESS': (.0006, .0004)}


def marks_from_archive(archive, symbols):
    """Validate checksums, complete mark prices and archived rates for the window."""
    funding = {}
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read('manifest.json'))
        if manifest['source_dataset_sha256'] != 'a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041':
            raise ValueError('funding pertence a outro dataset')
        check = {x['symbol']: x for x in manifest['symbols']}
        for symbol in symbols:
            if check[symbol]['rate_mismatches'] or check[symbol]['received'] != check[symbol]['expected']:
                raise ValueError(f'arquivo de funding incompleto: {symbol}')
            raw = z.read(symbol + '.json.gz')
            if hashlib.sha256(raw).hexdigest() != check[symbol]['sha256']:
                raise ValueError(f'funding sha256 divergente: {symbol}')
            rows = json.loads(gzip.decompress(raw))
            selected = []
            previous = 0
            for r in rows:
                if r['symbol'] != symbol:
                    raise ValueError(f'funding símbolo divergente: {symbol}')
                when = int(r['fundingTime'])
                if when <= previous:
                    raise ValueError(f'funding não ordenado: {symbol}')
                previous = when
                if not START <= when < END:
                    continue
                if not r['markPrice']:
                    raise ValueError(f'markPrice ausente no recorte: {symbol} {when}')
                rate, mark = float(r['fundingRate']), float(r['markPrice'])
                if not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0:
                    raise ValueError(f'funding inválido: {symbol} {when}')
                selected.append((when, rate, mark))
            funding[symbol] = (tuple(x[0] for x in selected), selected)
    return funding


def close_at(position, reference, fee, slip, when, reason, cash, trades):
    side = position['side']
    execution = reference * (1 - side * slip)
    exit_fee = abs(position['qty'] * execution) * fee
    realized = side * position['qty'] * (execution - position['entry'])
    cash += realized - exit_fee
    trades.append({'symbol': position['symbol'], 'side': 'BUY' if side == 1 else 'SELL',
                   'entry_utc': iso(position['entry_time']), 'exit_utc': iso(when),
                   'exit_reason': reason, 'realized_usdt': realized,
                   'entry_fee_usdt': position['entry_fee'], 'exit_fee_usdt': exit_fee,
                   'funding_usdt': position['funding']})
    return cash, exit_fee


def run_scenario(bars, funding, signals, scenario):
    fee, slip = SCENARIOS[scenario]
    schedule = {parse_ms(x['fill_open_utc']): x for x in signals if x['status'] == 'RESEARCH_SIGNAL'}
    positions = {}
    trades = []
    daily = [{'utc': iso(START), 'equity': 10000.0}]
    cash = 10000.0
    total_fee = 0.0
    funding_cash = 0.0
    missing_active_bars = 0
    ambiguous_stop_funding = 0
    ambiguous_funding_abs = 0.0
    funding_events = 0
    peak_exposure = 0.0
    stop_count = 0
    for t in range(START, END, BAR_MS):
        selected = schedule.get(t)
        if selected:
            for symbol, pos in list(positions.items()):
                if t not in bars[symbol].index:
                    missing_active_bars += 1
                    raise ValueError(f'bar ativo ausente na saída: {symbol} {iso(t)}')
                cash, cost = close_at(pos, float(bars[symbol].loc[t, 'open']), fee, slip, t, 'REBALANCE', cash, trades)
                total_fee += cost
                del positions[symbol]
            # Each leg remains <=15% of the equity after entry fees.
            if cash <= 0:
                raise ValueError('equidade esgotada')
            budget = cash * LEG_WEIGHT / (1 + 4 * LEG_WEIGHT * fee)
            for leg in selected['legs']:
                symbol = leg['symbol']
                if t not in bars[symbol].index:
                    missing_active_bars += 1
                    raise ValueError(f'bar ativo ausente na entrada: {symbol} {iso(t)}')
                side = 1 if leg['side'] == 'BUY' else -1
                execution = float(bars[symbol].loc[t, 'open']) * (1 + side * slip)
                qty = budget / execution
                cost = budget * fee
                cash -= cost
                total_fee += cost
                positions[symbol] = {'symbol': symbol, 'side': side, 'qty': qty,
                                     'entry': execution, 'entry_time': t,
                                     'stop': execution * (1 - side * STOP_PCT),
                                     'entry_fee': cost, 'funding': 0.0}
            if len(positions) != 4 or sum(x['side'] for x in positions.values()) != 0:
                raise AssertionError('exposição assinada ou nº de posições divergiu')
            peak_exposure = max(peak_exposure, 4 * budget / cash)
        for symbol, pos in list(positions.items()):
            if t not in bars[symbol].index:
                missing_active_bars += 1
                raise ValueError(f'bar ativo ausente: {symbol} {iso(t)}')
            bar = bars[symbol].loc[t]
            opened = float(bar['open'])
            stop = pos['stop']
            gap_hit = (opened <= stop) if pos['side'] == 1 else (opened >= stop)
            if gap_hit:
                cash, cost = close_at(pos, opened, fee, slip, t, 'STOP_GAP', cash, trades)
                total_fee += cost
                stop_count += 1
                del positions[symbol]
                continue
            times, events = funding[symbol]
            lo = bisect_left(times, t)
            hi = bisect_left(times, t + BAR_MS)
            hit = (float(bar['low']) <= stop) if pos['side'] == 1 else (float(bar['high']) >= stop)
            if hit and hi > lo:
                ambiguous_stop_funding += 1
            for _, rate, mark in events[lo:hi]:
                payment = -pos['side'] * pos['qty'] * mark * rate
                funding_events += 1
                if hit:
                    ambiguous_funding_abs += abs(payment)
                pos['funding'] += payment
                cash += payment
                funding_cash += payment
            if hit:
                cash, cost = close_at(pos, stop, fee, slip, t + BAR_MS, 'STOP_INTRABAR', cash, trades)
                total_fee += cost
                stop_count += 1
                del positions[symbol]
        if (t + BAR_MS - START) % (24 * 60 * 60 * 1000) == 0:
            value = cash
            for symbol, pos in positions.items():
                value += pos['side'] * pos['qty'] * (float(bars[symbol].loc[t, 'close']) - pos['entry'])
            daily.append({'utc': iso(t + BAR_MS), 'equity': value})

    # Last candle ends at END; exits are valued at its close, with exit costs.
    for symbol, pos in list(positions.items()):
        last_open = END - BAR_MS
        cash, cost = close_at(pos, float(bars[symbol].loc[last_open, 'close']), fee, slip, END, 'WINDOW_END', cash, trades)
        total_fee += cost
        del positions[symbol]
    daily[-1]['equity'] = cash
    if missing_active_bars:
        raise ValueError('missing active bars')
    peak = daily[0]['equity']
    drawdown = 0.0
    for item in daily:
        peak = max(peak, item['equity'])
        drawdown = max(drawdown, 1 - item['equity'] / peak)
    month_ends = {}
    for d in daily[1:]:
        # The 00:00 mark belongs to the preceding UTC calendar day.
        month = datetime.fromtimestamp((parse_ms(d['utc']) - 1) / 1000, timezone.utc).strftime('%Y-%m')
        month_ends[month] = d['equity']
    month_returns = {}
    last = 10000.0
    for name, value in month_ends.items():
        month_returns[name] = 100 * (value / last - 1)
        last = value
    half_start = month_ends['2025-12']
    return {'scenario': scenario, 'start_usdt': 10000.0, 'end_usdt': cash,
            'return_pct': 100 * (cash / 10000 - 1),
            'monthly_compound_pct': 100 * ((cash / 10000) ** (1 / 32) - 1),
            'max_daily_mtm_drawdown_pct': 100 * drawdown,
            'jan_jun_2026_pct': 100 * (cash / half_start - 1),
            'months_ge_20pct': sum(v >= 20 for v in month_returns.values()),
            'monthly_pct': month_returns, 'closed_trades': len(trades), 'stops': stop_count,
            'fees_usdt': total_fee, 'funding_usdt': funding_cash,
            'missing_active_bars': missing_active_bars,
            'ambiguous_stop_funding_bars': ambiguous_stop_funding,
            'ambiguous_funding_absolute_usdt': ambiguous_funding_abs,
            'optimistic_funding_order_return_upper_bound_pct': 100 * ((cash + ambiguous_funding_abs) / 10000 - 1),
            'funding_events_applied': funding_events,
            'peak_entry_gross_fraction': peak_exposure,
            'oos_validated': False, 'live': False, 'cost_model': 'assumed, not account-reconciled',
            'trades': trades}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--marks-zip', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    bars = verified_history(args.root)
    funding = marks_from_archive(args.marks_zip, bars)
    signals = [rank_week(bars, t) for t in range(WEEK_ZERO, END, WEEK_MS)]
    report = {'candidate': 'R17-CSMOM-W1', 'scope': 'RETROSPECTIVE_DEVELOPMENT',
              'funding': 'official fundingRate and markPrice, sha256 checked',
              'start_utc': iso(START), 'end_exclusive_utc': iso(END),
              'signals_weeks': len(signals),
              'provenance_sha256': {
                  'replay_code': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'signals_code': hashlib.sha256(Path(__file__).with_name('r17_candidate_signals.py').read_bytes()).hexdigest(),
                  'frozen_protocol': hashlib.sha256(Path(__file__).with_name('R17_00_PROTOCOL_PT.md').read_bytes()).hexdigest(),
                  'funding_archive': hashlib.sha256(Path(args.marks_zip).read_bytes()).hexdigest(),
              },
              'result': {}}
    for scenario in SCENARIOS:
        report['result'][scenario] = run_scenario(bars, funding, signals, scenario)
    Path(args.out).write_text(json.dumps(report, indent=2, allow_nan=False, ensure_ascii=False) + '\n')
    for k, v in report['result'].items():
        print(k, 'return_pct', round(v['return_pct'], 3), 'dd', round(v['max_daily_mtm_drawdown_pct'], 3),
              'ambiguous', v['ambiguous_stop_funding_bars'], 'trades', v['closed_trades'])


if __name__ == '__main__':
    main()
