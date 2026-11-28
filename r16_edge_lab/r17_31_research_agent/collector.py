"""Public, read-only research collection. No account credentials or order API."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT')
BASE = 'https://fapi.binance.com'
FEEDS = (
    'https://blog.ethereum.org/feed.xml',
    'https://www.federalreserve.gov/feeds/press_all.xml',
)
PATHS = {
    'hourly': '/fapi/v1/klines', 'four_hourly': '/fapi/v1/klines',
    'book': '/fapi/v1/depth', 'funding': '/fapi/v1/premiumIndex',
    'open_interest': '/fapi/v1/openInterest',
}
SUPPLEMENTAL = {
    'stablecoins': 'https://stablecoins.llama.fi/stablecoincharts/all',
    'chains': 'https://api.llama.fi/v2/chains',
    'supply': 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin,ethereum,solana,binancecoin,ripple,dogecoin',
}


def now_ms():
    return time.time_ns() // 1_000_000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def fetch(url, *, timeout=15, max_bytes=5_000_000):
    started = now_ms()
    request = urllib.request.Request(url, headers={'User-Agent': 'IGOR-Research/17.31', 'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError('response exceeds configured limit')
        return dict(url=url, requested_ms=started, received_ms=now_ms(),
                    sha256=hashlib.sha256(raw).hexdigest(), raw=raw.decode('utf-8'), error=None)
    except (OSError, ValueError, UnicodeError) as exc:
        # Do not print request headers, credentials or response bodies on failure.
        return dict(url=url, requested_ms=started, received_ms=now_ms(),
                    sha256=None, raw=None, error=type(exc).__name__)


def headlines(record):
    """Return primary-source headlines as untrusted content, never instructions."""
    if record['error']:
        return []
    root = ET.fromstring(record['raw'])
    out = []
    for item in root.findall('.//item')[:20]:
        title, link = item.findtext('title'), item.findtext('link')
        date = item.findtext('pubDate')
        try:
            stamp = int(parsedate_to_datetime(date).timestamp() * 1000)
        except (TypeError, ValueError, AttributeError):
            stamp = None
        if title and link and stamp is not None and stamp <= record['received_ms']:
            out.append(dict(title=title[:500], url=link, published_ms=stamp,
                            known_ms=record['received_ms'], source_url=record['url'],
                            source_sha256=record['sha256'], verification='publisher_feed_only'))
    return out


def collect(symbols=SYMBOLS):
    if not symbols or len(set(symbols)) != len(symbols) or any(s not in SYMBOLS for s in symbols):
        raise ValueError('use unique symbols from the frozen six-symbol universe')
    jobs = []
    for symbol in symbols:
        for kind, path in PATHS.items():
            query = dict(symbol=symbol)
            if kind in ('hourly', 'four_hourly'):
                query.update(interval='1h' if kind == 'hourly' else '4h', limit=200)
            elif kind == 'book':
                query['limit'] = 20
            jobs.append((symbol, kind, BASE + path + '?' + urllib.parse.urlencode(query)))
    jobs += [('GLOBAL', 'global', 'https://api.coingecko.com/api/v3/global')]
    jobs += [('CONTEXT', kind, url) for kind, url in SUPPLEMENTAL.items()]
    jobs += [('NEWS', f'feed_{i}', url) for i, url in enumerate(FEEDS)]
    started = now_ms()
    result = dict(version='17.31', started_ms=started, as_of_ms=None,
                  universe=list(symbols), market={s: {} for s in symbols}, sources=[], news=[], errors=[])
    # Bounded concurrency, one request per endpoint/cycle, no rate-limit retries.
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda job: fetch(job[2]), jobs))
    for (symbol, kind, _), record in zip(jobs, records):
        source_id = f'{symbol}:{kind}'
        source = dict(record, id=source_id)
        result['sources'].append(source)
        if record['error']:
            result['errors'].append(dict(source_id=source_id, error=record['error']))
            continue
        try:
            if symbol == 'NEWS':
                result['news'].extend(dict(item, source_id=source_id) for item in headlines(record))
            else:
                payload = json.loads(record['raw'])
                if isinstance(payload, dict) and isinstance(payload.get('code'), int) and payload['code'] < 0:
                    raise ValueError('exchange error response')
                if symbol in ('GLOBAL', 'CONTEXT'):
                    result[kind] = dict(data=payload, source_id=source_id, known_ms=record['received_ms'])
                else:
                    result['market'][symbol][kind] = dict(data=payload, source_id=source_id,
                                                         known_ms=record['received_ms'])
        except (ValueError, TypeError, ET.ParseError):
            result['errors'].append(dict(source_id=source_id, error='INVALID_PAYLOAD'))
    result['as_of_ms'] = now_ms()
    result['snapshot_sha256'] = digest(result)
    return result
