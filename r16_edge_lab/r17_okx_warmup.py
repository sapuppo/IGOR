#!/usr/bin/env python3
"""Freeze 49 pre-observation 4h candles per OKX swap for causal indicator warmup."""
import argparse
import hashlib
import json
from pathlib import Path

from r17_forward_capture import BAR_MS, CaptureError, canonical_bytes, number, utc, valid_ts
from r17_okx_cohort_capture import fixed_universe
from r17_okx_public_capture import PublicOKX

FIRST_COHORT = 'capture-1790616886230-4a0ee7e0fe156993.json'
CUTOFF_MS = 1790596800000  # 2026-09-28T12:00:00Z; before the first 35-symbol candle.
LENGTH = 49


def build(client, symbols, first_capture):
    if (first_capture['schema'] != 'IGOR_R17_03_OKX_COHORT_CAPTURE_V1'
            or first_capture['start_utc'] != utc(CUTOFF_MS)
            or first_capture['universe'] != list(symbols)):
        raise CaptureError('primeira captura da coorte incompatível com warmup')
    expected = list(range(CUTOFF_MS-LENGTH*BAR_MS, CUTOFF_MS, BAR_MS))
    observations, problems = {}, []
    for symbol in symbols:
        raw = client.get('/api/v5/market/candles', {'instId': symbol, 'bar': '4H', 'limit': '100'})
        selected = sorted((row for row in raw if valid_ts(row[0], 'warmup.ts') in expected),
                          key=lambda row: int(row[0]))
        issues = []
        if [int(row[0]) for row in selected] != expected:
            issues.append('WARMUP_BAR_GAP')
        for row in selected:
            if len(row) < 9 or row[8] != '1':
                issues.append('WARMUP_UNCONFIRMED')
                continue
            op, high, low, close = (number(x, 'warmup.OHLC') for x in row[1:5])
            if min(op, high, low, close) <= 0 or high < max(op, close) or low > min(op, close):
                issues.append('WARMUP_INVALID_OHLC')
            if number(row[7], 'quote volume') < 0:
                issues.append('WARMUP_INVALID_VOLUME')
        observations[symbol] = {'status': 'COMPLETE' if not issues else 'INCOMPLETE',
                                'klines': selected, 'problems': issues}
        problems.extend(f'{symbol}:{error}' for error in issues)
    return {'schema':'IGOR_R17_04_OKX_WARMUP_ONLY_V1', 'purpose':'INDICATOR_WARMUP_ONLY',
            'cutoff_exclusive_utc':utc(CUTOFF_MS), 'universe':list(symbols),
            'first_capture_filename':FIRST_COHORT,
            'first_capture_file_sha256':hashlib.sha256(canonical_bytes(first_capture)).hexdigest(),
            'status':'COMPLETE' if not problems else 'INCOMPLETE',
            'problems':problems, 'observations':observations,
            'oos_validated':False, 'live':False, 'pnl':None}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--captures',required=True)
    parser.add_argument('--out-dir',required=True)
    args=parser.parse_args()
    source=Path(args.captures)/FIRST_COHORT
    first=json.loads(source.read_bytes())
    if canonical_bytes(first)!=source.read_bytes():
        raise CaptureError('primeira captura da coorte foi reserializada')
    value=build(PublicOKX(),fixed_universe(args.manifest),first)
    value['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    raw=canonical_bytes(value)
    digest=hashlib.sha256(raw).hexdigest()
    path=Path(args.out_dir)/f'warmup-20260928T120000Z-{digest[:16]}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as handle:
        handle.write(raw)
    print(json.dumps({'file':str(path),'sha256':digest,'status':value['status'],
                      'valid':sum(x['status']=='COMPLETE' for x in value['observations'].values()),
                      'problems':value['problems']}))
    if value['status']!='COMPLETE':
        raise CaptureError('warmup parcial arquivado; operar só com série causal completa')


if __name__=='__main__':
    main()
