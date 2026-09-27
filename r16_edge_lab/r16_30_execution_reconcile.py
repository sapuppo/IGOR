#!/usr/bin/env python3
"""Read-only USD-M execution reconciliation. No network, credentials or order placement.

Inputs: prospective order intent CSV, Binance /fapi/v1/userTrades JSON, and
/fapi/v1/income JSON (all income types, including FUNDING_FEE). Output is a
sample-scoped JSON audit, never a strategy approval or historical funding fix.
"""
import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

D = Decimal
ZERO = D('0')
TOL = D('0.00000001')
MONEY_TOL = D('0.0001')
REQUIRED = {'position_id', 'leg', 'symbol', 'side', 'exchange_order_id',
            'submit_ts_ms', 'reference_price', 'planned_qty', 'sim_fee_usdt'}


def dec(value, name, positive=False):
    try:
        v = D(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{name}: invalid decimal') from None
    if not v.is_finite() or (positive and v <= 0):
        raise ValueError(f'{name}: invalid sign or nonfinite number')
    return v


def millis(value, name):
    try:
        n = int(str(value))
    except ValueError:
        raise ValueError(f'{name}: use UTC Unix milliseconds') from None
    if n < 1_500_000_000_000 or n > 4_100_000_000_000:
        raise ValueError(f'{name}: out of UTC millisecond range')
    return n


def read_json(path):
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, list):
        raise ValueError(f'{path.name}: expected full JSON array, not an API page wrapper')
    return obj


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconcile(plans_path, trades_path, income_path, start, end,
              complete_trades, complete_income, isolated_account,
              expected_funding=None):
    problems = []
    warnings = []
    def issue(code, detail):
        problems.append({'code': code, 'detail': detail})

    with plans_path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError(f'plan CSV needs columns: {", ".join(sorted(REQUIRED))}')
        rows = list(reader)
    trades = read_json(trades_path)
    incomes = read_json(income_path)
    start, end = millis(start, 'start'), millis(end, 'end')
    if end <= start:
        raise ValueError('end must follow start (UTC milliseconds)')
    if not rows:
        issue('NO_PLANS', 'No submitted prospective orders to check')

    orders = {}
    positions = defaultdict(dict)
    for i, row in enumerate(rows, 2):
        oid = row['exchange_order_id'].strip()
        pid, leg = row['position_id'].strip(), row['leg'].strip().upper()
        sym, side = row['symbol'].strip().upper(), row['side'].strip().upper()
        if not oid or not pid or leg not in ('ENTRY', 'EXIT') or side not in ('BUY', 'SELL') or not sym.endswith('USDT'):
            raise ValueError(f'plan line {i}: invalid order id, position, leg, symbol or side')
        submit = millis(row['submit_ts_ms'], f'plan line {i} submit_ts_ms')
        ref = dec(row['reference_price'], f'plan line {i} reference_price', True)
        qty = dec(row['planned_qty'], f'plan line {i} planned_qty', True)
        sim_fee = dec(row['sim_fee_usdt'], f'plan line {i} sim_fee_usdt')
        if sim_fee < 0 or not start <= submit < end:
            raise ValueError(f'plan line {i}: invalid fee or outside observation window')
        if oid in orders or leg in positions[pid]:
            issue('DUPLICATE_PLAN', f'order {oid} / position {pid} {leg}')
        orders[oid] = dict(position=pid, leg=leg, symbol=sym, side=side,
                           submit=submit, reference=ref, qty=qty, sim_fee=sim_fee)
        positions[pid][leg] = oid

    fills = defaultdict(list)
    seen_trades = set()
    for t in trades:
        sym = str(t['symbol']).upper()
        key = (sym, str(t['id']))
        if key in seen_trades:
            issue('DUPLICATE_TRADE', f'{sym} trade {t["id"]}')
            continue
        seen_trades.add(key)
        when = millis(t['time'], 'trade.time')
        if not start <= when < end:
            issue('TRADE_OUTSIDE_WINDOW', f'{key}')
        oid = str(t['orderId'])
        if oid not in orders:
            issue('UNMATCHED_TRADE', f'{key} order {oid}')
            continue
        p = orders[oid]
        if sym != p['symbol'] or str(t['side']).upper() != p['side']:
            issue('SYMBOL_OR_SIDE_MISMATCH', f'{key} order {oid}')
        if when < p['submit']:
            issue('FILL_BEFORE_SUBMIT', f'{key} order {oid}')
        asset = str(t['commissionAsset']).upper()
        if asset != 'USDT':
            issue('FEE_CONVERSION_REQUIRED', f'{key} asset {asset}; provide documented USDT conversion before evaluating')
        qty = dec(t['qty'], 'trade.qty', True)
        price = dec(t['price'], 'trade.price', True)
        fee = dec(t['commission'], 'trade.commission')
        pnl = dec(t['realizedPnl'], 'trade.realizedPnl')
        if fee < 0:
            issue('NEGATIVE_COMMISSION', f'{key}; rebates need separate accounting')
        fills[oid].append((qty, price, fee, pnl, when))

    order_details = []
    for oid, p in sorted(orders.items()):
        fs = fills[oid]
        qty = sum((f[0] for f in fs), ZERO)
        fee = sum((f[2] for f in fs), ZERO)
        if not fs:
            issue('UNFILLED_ORDER', f'order {oid}')
        elif abs(qty - p['qty']) > TOL:
            issue('PARTIAL_OR_OVERFILL', f'order {oid}: planned {p["qty"]}, filled {qty}')
        vwap = sum((f[0] * f[1] for f in fs), ZERO) / qty if qty else None
        # Positive = adverse execution relative to decision-time reference.
        adverse = ((vwap - p['reference']) if p['side'] == 'BUY' else
                   (p['reference'] - vwap)) * qty if vwap is not None else None
        order_details.append(dict(order_id=oid, position_id=p['position'], leg=p['leg'],
                                  fills=len(fs), planned_qty=str(p['qty']), filled_qty=str(qty),
                                  vwap=str(vwap) if vwap is not None else None,
                                  adverse_execution_usdt=str(adverse) if adverse is not None else None,
                                  actual_commission=str(fee), simulated_commission=str(p['sim_fee'])))

    pnl = ZERO
    for pid, legs in sorted(positions.items()):
        if set(legs) != {'ENTRY', 'EXIT'}:
            issue('OPEN_POSITION', f'{pid}: requires entry and exit')
            continue
        entry, ex = orders[legs['ENTRY']], orders[legs['EXIT']]
        if entry['symbol'] != ex['symbol'] or entry['side'] == ex['side']:
            issue('INVALID_POSITION', f'{pid}: symbol/side mismatch')
            continue
        qin = sum((x[0] for x in fills[legs['ENTRY']]), ZERO)
        qout = sum((x[0] for x in fills[legs['EXIT']]), ZERO)
        if qin == 0 or qout == 0 or abs(qin - qout) > TOL:
            issue('UNBALANCED_POSITION', f'{pid}: entry {qin}, exit {qout}')
            continue
        cash = ZERO
        for leg in ('ENTRY', 'EXIT'):
            p = orders[legs[leg]]
            sign = D('-1') if p['side'] == 'BUY' else D('1')
            cash += sum((sign * q * price for q, price, _, _, _ in fills[legs[leg]]), ZERO)
        pnl += cash

    seen_income = set()
    funding = ZERO
    commission_income = ZERO
    realized_income = ZERO
    other_income = []
    for t in incomes:
        typ = str(t['incomeType']).upper()
        key = (typ, str(t['tranId']))
        if key in seen_income:
            issue('DUPLICATE_INCOME', f'{key}')
            continue
        seen_income.add(key)
        when = millis(t['time'], 'income.time')
        if not start <= when < end:
            issue('INCOME_OUTSIDE_WINDOW', f'{key}')
        asset = str(t['asset']).upper()
        amount = dec(t['income'], 'income.income')
        if asset != 'USDT':
            issue('INCOME_CONVERSION_REQUIRED', f'{key} asset {asset}')
        if typ == 'FUNDING_FEE':
            funding += amount
        elif typ == 'COMMISSION':
            commission_income += amount
        elif typ == 'REALIZED_PNL':
            realized_income += amount
        elif amount != 0:
            other_income.append(dict(type=typ, amount=str(amount), symbol=str(t.get('symbol', ''))))
    fees = sum((f[2] for fs in fills.values() for f in fs), ZERO)
    simulated_fees = sum((p['sim_fee'] for p in orders.values()), ZERO)
    reference_cash_pnl = sum(((D('-1') if p['side'] == 'BUY' else D('1')) * p['qty'] * p['reference']
                              for p in orders.values()), ZERO)
    exchange_pnl = sum((f[3] for fs in fills.values() for f in fs), ZERO)
    if any(str(t['incomeType']).upper() == 'COMMISSION' for t in incomes) and abs(commission_income + fees) > MONEY_TOL:
        issue('COMMISSION_LEDGER_MISMATCH', f'fills {fees}, income {commission_income}')
    if any(str(t['incomeType']).upper() == 'REALIZED_PNL' for t in incomes) and abs(realized_income - exchange_pnl) > MONEY_TOL:
        issue('REALIZED_LEDGER_MISMATCH', f'trades {exchange_pnl}, income {realized_income}')
    if abs(pnl - exchange_pnl) > MONEY_TOL and not any(x['code'] in ('OPEN_POSITION', 'UNBALANCED_POSITION') for x in problems):
        issue('REALIZED_PNL_MISMATCH', f'cash from paired orders {pnl}, exchange trade fields {exchange_pnl}')
    if other_income:
        issue('OTHER_ACCOUNT_CASHFLOWS', f'{len(other_income)} nonzero rows require separate attribution')
    if expected_funding is not None and abs(funding - dec(expected_funding, 'expected_funding')) > MONEY_TOL:
        issue('FUNDING_MODEL_MISMATCH', f'model {expected_funding}, account {funding}')
    if not complete_trades or not complete_income or not isolated_account:
        issue('COVERAGE_UNPROVEN', 'Confirm full paginated exports of all trades and all income types; use isolated strategy account')
    if not trades:
        issue('NO_REAL_TRADES', 'No real or paper exchange fills supplied')
    if not incomes:
        issue('NO_INCOME_LEDGER', 'Full income ledger including funding or proof of zero events required')
    if not any(str(t['incomeType']).upper() == 'FUNDING_FEE' for t in incomes):
        warnings.append('No funding event in supplied window; completeness must be proved outside this program')
    return {
        'status': 'SAMPLE_RECONCILED' if not problems else 'BLOCKED',
        'scope': 'prospective execution sample only; NOT historical markPrice validation, OOS validation or live-trading authorization',
        'utc_window_ms': [start, end],
        'source_sha256': {str(p.name): sha(p) for p in (plans_path, trades_path, income_path)},
        'coverage_assertions': {'all_trades': complete_trades, 'all_income_types': complete_income,
                                'isolated_account': isolated_account},
        'counts': {'planned_orders': len(rows), 'exchange_trades': len(trades),
                   'income_rows': len(incomes), 'funding_rows': sum(1 for t in incomes if str(t['incomeType']).upper() == 'FUNDING_FEE')},
        'totals_usdt': {'cash_price_pnl': str(pnl), 'trade_realized_pnl': str(exchange_pnl),
                        'fees': str(fees), 'funding': str(funding),
                        'reference_price_pnl': str(reference_cash_pnl),
                        'simulated_fees': str(simulated_fees),
                        'execution_price_delta_vs_reference': str(pnl - reference_cash_pnl),
                        'fee_delta_actual_minus_model': str(fees - simulated_fees),
                        'net_trade_fields_and_funding': str(exchange_pnl - fees + funding),
                        'net_paired_cash_and_funding': str(pnl - fees + funding)},
        'orders': order_details, 'problems': problems, 'warnings': warnings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plans', type=Path, required=True)
    parser.add_argument('--trades', type=Path, required=True)
    parser.add_argument('--income', type=Path, required=True)
    parser.add_argument('--start-ms', required=True)
    parser.add_argument('--end-ms', required=True)
    parser.add_argument('--complete-trades', action='store_true')
    parser.add_argument('--complete-income', action='store_true')
    parser.add_argument('--isolated-account', action='store_true')
    parser.add_argument('--expected-funding-usdt', help='Optional independently recorded prospective funding estimate')
    parser.add_argument('--out', type=Path)
    a = parser.parse_args()
    try:
        result = reconcile(a.plans, a.trades, a.income, a.start_ms, a.end_ms,
                           a.complete_trades, a.complete_income, a.isolated_account,
                           a.expected_funding_usdt)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as e:
        result = {'status': 'BLOCKED', 'problems': [{'code': 'INVALID_INPUT', 'detail': str(e)}]}
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    if a.out:
        a.out.write_text(output, encoding='utf-8')
    else:
        sys.stdout.write(output)
    return 0 if result['status'] == 'SAMPLE_RECONCILED' else 2


if __name__ == '__main__':
    sys.exit(main())
