#!/usr/bin/env python3
"""Offline USD-M fill/income reconciliation; never accesses an account or sends orders.

Inputs are JSON arrays of /fapi/v1/userTrades, /fapi/v1/income and optionally
local decision logs {symbol,orderId,decisionTime,referencePrice}. Output is
aggregated only. Missing sources fail closed; no assumed execution quality.
"""
import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

ZERO = Decimal('0')
TOL = Decimal('0.01')


class AuditError(ValueError):
    pass


def dec(value, field):
    try:
        num = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise AuditError(f'{field}: decimal inválido') from exc
    if not num.is_finite():
        raise AuditError(f'{field}: número não finito')
    return num


def rows(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise AuditError(f'{path}: exige array JSON de objetos')
    return value


def as_int(value, field):
    if isinstance(value, bool) or not str(value).isdigit():
        raise AuditError(f'{field}: inteiro positivo inválido')
    return int(value)


def percentile(values, percentage):
    if not values:
        return None
    ordered = sorted(values)
    rank = ((len(ordered) - 1) * percentage + 99) // 100
    return ordered[rank]


def fmt(value):
    return str(value) if value is not None else None


def audit(trades, income, decisions=None):
    if not isinstance(trades, list) or not isinstance(income, list):
        raise AuditError('trades e income devem ser arrays')
    if not trades or not income:
        raise AuditError('faltam fills ou income; não inferir custo zero')
    if decisions is not None and not isinstance(decisions, list):
        raise AuditError('decisions deve ser array')

    decisions_map = {}
    for d in decisions or []:
        key = (str(d['symbol']), as_int(d['orderId'], 'orderId'))
        if key in decisions_map:
            raise AuditError('duplicata de decisão por símbolo e ordem')
        price = dec(d['referencePrice'], 'referencePrice')
        when = as_int(d['decisionTime'], 'decisionTime')
        if price <= 0:
            raise AuditError('referencePrice <= 0')
        decisions_map[key] = (price, when)

    fill_ids = set()
    total_fee = ZERO
    total_realized = ZERO
    total_notional = ZERO
    fee_rates = {'maker': [], 'taker': []}
    slip_rates = []
    latency_ms = []
    missing_reference = 0
    dates = []
    orders = set()
    for t in trades:
        try:
            symbol = str(t['symbol'])
            key = (symbol, as_int(t['id'], 'trade id'))
            order = (symbol, as_int(t['orderId'], 'orderId'))
            when = as_int(t['time'], 'fill time')
            side = t['side']
            asset = t['commissionAsset']
            maker = t['maker']
            fee = dec(t['commission'], 'commission')
            realized = dec(t['realizedPnl'], 'realizedPnl')
            price = dec(t['price'], 'price')
            quantity = dec(t['qty'], 'qty')
        except (KeyError, TypeError) as exc:
            raise AuditError(f'fill com campo ausente ou inválido: {exc}') from exc
        if key in fill_ids:
            raise AuditError('fill repetido: símbolo/id')
        fill_ids.add(key)
        orders.add(order)
        if asset != 'USDT':
            raise AuditError('comissão em outra moeda: exigir conversão datada antes de somar')
        if side not in ('BUY', 'SELL') or type(maker) is not bool:
            raise AuditError('side/maker inválido')
        notional = price * quantity
        if notional <= 0 or fee < 0:
            raise AuditError('notional ou comissão inválida')
        if 'quoteQty' in t and abs(dec(t['quoteQty'], 'quoteQty') - notional) > max(TOL, notional * Decimal('0.000001')):
            raise AuditError('quoteQty não confere com preço × quantidade')
        total_fee += fee
        total_realized += realized
        total_notional += notional
        fee_rates['maker' if maker else 'taker'].append(fee / notional)
        dates.append(when)
        if order not in decisions_map:
            missing_reference += 1
        else:
            reference, decision_time = decisions_map[order]
            if decision_time > when:
                raise AuditError('decisão depois do fill; possível antecipação temporal')
            signed_slippage = (price / reference - 1) * (1 if side == 'BUY' else -1)
            slip_rates.append(signed_slippage)
            latency_ms.append(when - decision_time)

    ids = set()
    income_totals = defaultdict(lambda: ZERO)
    income_count = defaultdict(int)
    for i in income:
        try:
            kind = i['incomeType']
            asset = i['asset']
            value = dec(i['income'], 'income')
            key = (kind, str(i['tranId']))
            when = as_int(i['time'], 'income time')
        except (KeyError, TypeError) as exc:
            raise AuditError(f'income com campo ausente ou inválido: {exc}') from exc
        if key in ids:
            raise AuditError('income repetido: tipo/tranId')
        ids.add(key)
        if asset != 'USDT':
            raise AuditError('income em outra moeda: exigir conversão datada')
        income_totals[kind] += value
        income_count[kind] += 1
        dates.append(when)

    problems = []
    if not income_count['COMMISSION']:
        problems.append('MISSING_COMMISSION_INCOME')
    elif abs(income_totals['COMMISSION'] + total_fee) > TOL:
        problems.append('COMMISSION_MISMATCH')
    if not income_count['REALIZED_PNL']:
        problems.append('MISSING_REALIZED_PNL_INCOME')
    elif abs(income_totals['REALIZED_PNL'] - total_realized) > TOL:
        problems.append('REALIZED_PNL_MISMATCH')
    if not income_count['FUNDING_FEE']:
        problems.append('FUNDING_COVERAGE_UNCONFIRMED')
    if missing_reference:
        problems.append('MISSING_DECISION_PRICE')
    # Exports may be partial despite matching sums. External coverage attestation
    # and a start/end equity statement are required for account-level validation.
    problems.extend(['EXPORT_COVERAGE_UNVERIFIED', 'ACCOUNT_EQUITY_UNVERIFIED'])

    return {
        'status': 'NOT_READY', 'blocking_reasons': problems,
        'scope': 'soma dos fills realizados, não retorno da conta nem simulação aprovada',
        'fill_count': len(trades), 'order_count': len(orders),
        'income_count': len(income), 'decision_matches': len(slip_rates),
        'earliest_event_ms': min(dates), 'latest_event_ms': max(dates),
        'totals_usdt': {
            'realized_pnl': fmt(total_realized), 'commission_paid': fmt(total_fee),
            'funding_net': fmt(income_totals['FUNDING_FEE']),
            'realized_after_commission_and_funding': fmt(total_realized - total_fee + income_totals['FUNDING_FEE']),
            'fill_notional': fmt(total_notional),
        },
        'fees_rate': {k: {'count': len(v), 'p95': fmt(percentile(v, 95))} for k, v in fee_rates.items()},
        'adverse_signed_slippage_rate_p95': fmt(percentile(slip_rates, 95)),
        'latency_ms_p95': percentile(latency_ms, 95),
        'note': 'funding ausente pode ser zero ou export incompleto; saída não atesta completude',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trades', required=True, help='array JSON exportado de userTrades')
    parser.add_argument('--income', required=True, help='array JSON exportado de income')
    parser.add_argument('--decisions', help='array JSON local com referencePrice/decisionTime por orderId')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = audit(rows(args.trades), rows(args.income), rows(args.decisions) if args.decisions else None)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(result['status'], ','.join(result['blocking_reasons']))


if __name__ == '__main__':
    main()
