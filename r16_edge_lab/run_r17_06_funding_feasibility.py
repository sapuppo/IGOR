#!/usr/bin/env python3
"""Descriptive funding economics; no spot/perp fills or strategy PnL inferred."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_SHA = 'a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041'
END = pd.Timestamp('2026-07-01', tz='UTC')
NOTIONAL_CAPITAL = 0.5
MAX_GAP_MS = 86400000


def month_statistics(frame, symbol, start, end):
    lo,hi=int(start.timestamp()*1000),int(end.timestamp()*1000)
    rows=frame.loc[(frame.fundingTime>=lo)&(frame.fundingTime<hi)]
    if rows.empty:
        return None
    stamps=rows.fundingTime.to_numpy(dtype=np.int64)
    gaps=np.diff(np.concatenate(([lo],stamps,[hi])))
    full_listing=int(frame.fundingTime.iloc[0])<=lo+60000
    coverage=full_listing and int(gaps.max())<=MAX_GAP_MS
    rate_sum=float(rows.fundingRate.sum())
    return {'symbol':symbol,'month':start.strftime('%Y-%m'),'events':len(rows),
            'funding_rate_sum':rate_sum,'inventory_normalized_component':NOTIONAL_CAPITAL*rate_sum,
            'full_month_coverage':bool(coverage),'max_event_gap_hours':float(gaps.max()/3600000),
            'positive_rate_event_fraction':float((rows.fundingRate>0).mean())}


def analyze(root):
    root=Path(root)
    manifest=json.loads((root/'manifest.json').read_text())
    if manifest['dataset_manifest_sha256']!=ROOT_SHA:
        raise ValueError('manifesto histórico divergente')
    symbols=sorted(x['symbol'] for x in manifest['symbols'] if x['eligible'])
    if len(symbols)!=38:
        raise ValueError('coorte divergente')
    entries={x['symbol']:x for x in manifest['files'] if x['kind']=='funding'}
    records=[]
    months=pd.date_range(pd.Timestamp('2021-01-01',tz='UTC'),END,freq='MS')
    for symbol in symbols:
        path=root/'funding'/f'{symbol}.csv.gz'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entries[symbol]['sha256']:
            raise ValueError('funding hash alterado '+symbol)
        frame=pd.read_csv(path)
        if (frame.symbol!=symbol).any() or not frame.fundingTime.is_monotonic_increasing or frame.fundingTime.duplicated().any():
            raise ValueError('funding inválido '+symbol)
        if not np.isfinite(frame.fundingRate).all():
            raise ValueError('taxa não finita '+symbol)
        for begin,end in zip(months[:-1],months[1:]):
            item=month_statistics(frame,symbol,begin,end)
            if item:
                records.append(item)
    valid=[x for x in records if x['full_month_coverage']]
    components=[x['inventory_normalized_component'] for x in valid]
    summary={}
    for symbol in symbols:
        items=[x for x in valid if x['symbol']==symbol]
        values=[x['inventory_normalized_component'] for x in items]
        if values:
            summary[symbol]={'months':len(values),'median_component':float(np.median(values)),
                             'min_component':min(values),'max_component':max(values),
                             'months_component_ge_20pct':sum(x>=.2 for x in values)}
    hindsight=[]
    for month in sorted({x['month'] for x in valid}):
        items=[x for x in valid if x['month']==month]
        winner=max(items,key=lambda x:(x['inventory_normalized_component'],x['symbol']))
        hindsight.append({'month':month,'symbol':winner['symbol'],
                          'component':winner['inventory_normalized_component']})
    result={'schema':'R17_06_FUNDING_COMPONENT_DIAGNOSTIC_V1',
            'purpose':'DESCRIPTIVE_NOT_STRATEGY_PNL','live':False,'oos_validated':False,
            'data_sha256':ROOT_SHA,'source_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'window':['2021-01-01','2026-07-01 exclusive'],'cohort_survivorship_free':False,
            'assumption':'Constant reference notional/equity = 0.5; no price changes, basis, costs, liquidation or reinvestment modeled.',
            'coverage_assumption':'No funding-event gap over 24h; first-listing partial months excluded. This does not independently prove all settlements present.',
            'records':records,'symbols':summary,
            'summary':{'full_symbol_months':len(valid),'partial_or_gap_symbol_months':len(records)-len(valid),
                       'median_component':float(np.median(components)),
                       'max_component':max(components),'min_component':min(components),
                       'months_component_ge_20pct':sum(x>=.2 for x in components)},
            'hindsight_best_each_month':hindsight,
            'hindsight_label':'Uses future monthly outcomes to choose pair; cannot be traded or claimed as alpha.'}
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True)
    p.add_argument('--out',required=True)
    args=p.parse_args()
    result=analyze(args.root)
    Path(args.out).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'summary':result['summary'],
                      'btc':result['symbols']['BTCUSDT'],'eth':result['symbols']['ETHUSDT']}))


if __name__=='__main__':
    main()
