"""Deterministic evidence and features; optional LLM can discuss, never size orders."""
import math
from datetime import datetime
from collector import SYMBOLS, digest

HOUR = 3_600_000
UNKNOWN = ('supply_and_unlocks', 'revenue_and_fees', 'tvl_and_users',
           'holder_concentration', 'token_value_accrual', 'verified_token_catalysts')
COINS = dict(zip(SYMBOLS, ('bitcoin','ethereum','solana','binancecoin','ripple','dogecoin')))
CHAINS = {'ETHUSDT':'Ethereum','SOLUSDT':'Solana','BNBUSDT':'BSC','BTCUSDT':'Bitcoin','XRPUSDT':'XRPL'}


def fundamentals(snapshot, symbol):
    result = dict(circulating_supply=None,total_supply=None,max_supply=None,market_cap_usd=None,
                  fully_diluted_valuation_usd=None,chain_tvl_usd=None,source_ids=[],
                  unlocks=None,revenue=None,fees=None,active_users=None,holder_concentration=None,
                  token_value_accrual=None)
    try:
        w=snapshot['supply']
        row=next(x for x in w['data'] if x['id']==COINS[symbol])
        updated=int(datetime.fromisoformat(row['last_updated'].replace('Z','+00:00')).timestamp()*1000)
        if not 0<=snapshot['as_of_ms']-updated<=HOUR or w['known_ms']>snapshot['as_of_ms']:
            raise ValueError('stale supply')
        for target, source in (('circulating_supply','circulating_supply'),('total_supply','total_supply'),
                               ('max_supply','max_supply'),('market_cap_usd','market_cap'),
                               ('fully_diluted_valuation_usd','fully_diluted_valuation')):
            value=row.get(source)
            result[target]=None if value is None else finite(value)
        result['source_ids'].append(w['source_id'])
    except (KeyError,StopIteration,TypeError,ValueError):
        pass
    try:
        w=snapshot['chains']
        row=next(x for x in w['data'] if x['name']==CHAINS.get(symbol))
        if w['known_ms']>snapshot['as_of_ms']:
            raise ValueError('future chain observation')
        result.update(chain_tvl_usd=finite(row['tvl']),chain_tvl_scope='chain, not token cashflow',
                      chain_tvl_provider_timestamp='not supplied; observed at collection')
        result['source_ids'].append(w['source_id'])
    except (KeyError,StopIteration,TypeError,ValueError):
        pass
    return result


def stablecoin_context(snapshot):
    try:
        w=snapshot['stablecoins'];as_of=snapshot['as_of_ms']
        if w['known_ms']>as_of:
            raise ValueError('future observation')
        rows=[x for x in w['data'] if 0<=as_of-int(x['date'])*1000<=10*24*HOUR]
        rows.sort(key=lambda x:int(x['date']))
        last=rows[-1];t=int(last['date'])*1000
        if as_of-t>48*HOUR:
            raise ValueError('stale stablecoin chart')
        old=[x for x in rows if int(x['date'])*1000<=t-7*24*HOUR]
        current=finite(last['totalCirculatingUSD']['peggedUSD'])
        prior=finite(old[-1]['totalCirculatingUSD']['peggedUSD']) if old else None
        return dict(usd_pegged_supply_usd=current,change_7d_fraction=current/prior-1 if prior else None,
                    source_id=w['source_id'],provider_timestamp_ms=t,
                    scope='USD-pegged supply proxy; not executable order-book liquidity')
    except (KeyError,IndexError,TypeError,ValueError,ZeroDivisionError):
        return None


def finite(value):
    if isinstance(value, bool):
        raise ValueError('boolean is not a number')
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite number')
    return number


def candles(wrapper, as_of, interval):
    if type(wrapper['known_ms']) is not int or wrapper['known_ms'] > as_of:
        raise ValueError('future observation')
    rows = wrapper['data']
    if not isinstance(rows, list):
        raise ValueError('invalid candles')
    closed = []
    previous = None
    for row in rows:
        start, end = row[0], row[6]
        if type(start) is not int or type(end) is not int or end != start + interval - 1:
            raise ValueError('invalid candle timestamps')
        if previous is not None and start != previous + interval:
            raise ValueError('candle gap or duplicate')
        previous = start
        if end >= wrapper['known_ms'] or end >= as_of:
            continue
        op, hi, lo, cl, vol = map(finite, [row[1], row[2], row[3], row[4], row[7]])
        if min(op, hi, lo, cl) <= 0 or vol < 0 or lo > min(op, cl) or hi < max(op, cl):
            raise ValueError('invalid OHLC or volume')
        closed.append(dict(start=start, end=end, open=op, high=hi, low=lo, close=cl, quote_volume=vol))
    if len(closed) < 60 or as_of - closed[-1]['end'] > interval + 300_000:
        raise ValueError('insufficient or stale closed candles')
    return closed


def ema(values, period):
    out = values[0]
    for value in values[1:]:
        out += 2 / (period + 1) * (value - out)
    return out


def features(item, as_of):
    hour = candles(item['hourly'], as_of, HOUR)
    four = candles(item['four_hourly'], as_of, 4 * HOUR)
    close = [r['close'] for r in hour]
    last = close[-1]
    ranges = [max(hour[i]['high'] - hour[i]['low'], abs(hour[i]['high'] - hour[i-1]['close']),
                  abs(hour[i]['low'] - hour[i-1]['close'])) for i in range(len(hour)-14, len(hour))]
    atr = sum(ranges) / len(ranges)
    book = item['book']
    if book['known_ms'] > as_of or as_of - book['known_ms'] > 120_000:
        raise ValueError('stale or future book observation')
    data = book['data']
    stamp = data.get('E', data.get('T'))
    if type(stamp) is not int or stamp > book['known_ms'] + 1000 or book['known_ms'] - stamp > 120_000:
        raise ValueError('stale/future exchange book timestamp or clock skew')
    def levels(rows, reverse):
        result = [(finite(p), finite(q)) for p, q in rows]
        prices = [p for p, q in result]
        if not result or min(min(p, q) for p, q in result) <= 0:
            raise ValueError('invalid depth')
        if len(set(prices)) != len(prices) or prices != sorted(prices, reverse=reverse):
            raise ValueError('duplicate or unsorted depth')
        return result
    bids, asks = levels(data['bids'], True), levels(data['asks'], False)
    bid, ask = bids[0][0], asks[0][0]
    if bid >= ask:
        raise ValueError('crossed book')
    mid = (bid + ask) / 2
    funding, oi = item['funding'], item['open_interest']
    for wrapper in (funding, oi):
        stamp = wrapper['data']['time']
        if wrapper['known_ms'] > as_of or as_of - wrapper['known_ms'] > 120_000:
            raise ValueError('stale observation')
        if stamp > wrapper['known_ms'] + 1000 or wrapper['known_ms'] - stamp > 120_000:
            raise ValueError('stale/future derivative data')
    interest = finite(oi['data']['openInterest'])
    if interest < 0:
        raise ValueError('negative open interest')
    fourclose = [r['close'] for r in four]
    trend = ema(fourclose, 20) / ema(fourclose, 50) - 1
    ret = last / close[-25] - 1
    returns = [close[i] / close[i-1] - 1 for i in range(len(close)-24, len(close))]
    mean = sum(returns) / len(returns)
    vol = math.sqrt(sum((r-mean)**2 for r in returns) / len(returns))
    regime = 'high_vol' if atr/last > .04 else 'trending' if abs(trend) > .01 else 'mean_reverting'
    return dict(last_closed_ms=hour[-1]['end'], available_at_ms=max(w['known_ms'] for w in item.values()),
                last_closed_price=last, bid=bid, ask=ask, mid=mid, spread_bps=(ask-bid)/mid*10000,
                bid_depth_notional=sum(p*q for p,q in bids), ask_depth_notional=sum(p*q for p,q in asks),
                return_24h=ret, realized_hourly_volatility=vol, atr_fraction=atr/last,
                trend_4h=trend, regime=regime, quote_volume_24h=sum(r['quote_volume'] for r in hour[-24:]),
                funding_rate_observed=finite(funding['data']['lastFundingRate']),
                next_funding_ms=funding['data']['nextFundingTime'], open_interest_units=interest)


def build_research(snapshot):
    as_of = snapshot['as_of_ms']
    if type(as_of) is not int or not snapshot['universe'] or any(s not in SYMBOLS for s in snapshot['universe']):
        raise ValueError('invalid snapshot contract')
    candidates, invalid = [], []
    for symbol in snapshot['universe']:
        try:
            f = features(snapshot['market'][symbol], as_of)
            direction = 'long' if f['trend_4h'] > .01 and f['return_24h'] > 0 else 'short' if f['trend_4h'] < -.01 and f['return_24h'] < 0 else 'neutral'
            candidates.append(dict(
                symbol=symbol, direction=direction, setup_quality=0 if direction=='neutral' else 1,
                confidence=None, confidence_calibrated=False, decision='WATCH_ONLY',
                features=f, evidence_ids=[snapshot['market'][symbol][k]['source_id'] for k in ('hourly','four_hourly','book','funding','open_interest')],
                thesis=f'Contexto 4h {f["regime"]}; variação 24h {f["return_24h"]:.2%}. Hipótese técnica exploratória.',
                catalysts=[], bear_case='Custos, reversão e ausência de catalisador fundamental podem eliminar a vantagem.',
                invalidation='Invalidar com dados obsoletos, reversão do contexto 4h ou falha da validação líquida fora da amostra.',
                fundamentals=fundamentals(snapshot,symbol), missing_evidence=list(UNKNOWN), edge_validated=False))
        except (ValueError, KeyError, TypeError, IndexError, ZeroDivisionError) as exc:
            invalid.append(dict(symbol=symbol, reason=str(exc)))
    # Ordering is descriptive technical strength, not expected return or probability.
    candidates.sort(key=lambda c: (-abs(c['features']['trend_4h']), c['symbol']))
    for rank, c in enumerate(candidates, 1):
        c['research_rank'] = rank
    market = {c['symbol']:c['features']['regime'] for c in candidates if c['symbol'] in ('BTCUSDT','ETHUSDT')}
    global_context = dict(btc_dominance=None, stablecoin_liquidity=stablecoin_context(snapshot), narrative_rotation=None,
                          macro='primary headlines only; no causal macro model')
    try:
        wrapper = snapshot['global']
        data = wrapper['data']['data']
        if wrapper['known_ms'] > as_of or not 0<=as_of - int(data['updated_at'])*1000<=HOUR:
            raise ValueError('stale global observation')
        global_context.update(btc_dominance=finite(data['market_cap_percentage']['btc']), source_id=wrapper['source_id'])
    except (KeyError, TypeError, ValueError):
        pass
    for candidate in candidates:
        candidate['evidence_ids'].extend(candidate['fundamentals']['source_ids'])
    news = [n for n in snapshot.get('news', []) if n['known_ms'] <= as_of and 0 <= as_of-n['published_ms'] <= 7*24*HOUR]
    result = dict(version='17.31', mode='research_only', brain='deterministic_baseline', as_of_ms=as_of,
                  snapshot_sha256=snapshot.get('snapshot_sha256', digest(snapshot)), market_regimes=market,
                  global_context=global_context, primary_headlines=news, candidates=candidates,
                  invalid_symbols=invalid, collection_errors=snapshot.get('errors', []),
                  orders_sent=0, promotion='BLOCKED_UNVALIDATED_EDGE')
    result['research_sha256'] = digest(result)
    return result
