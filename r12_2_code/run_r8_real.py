from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, math, zipfile
import pandas as pd
import requests

from r8_setup_experts_engine import (
    Config, make_dataset, walk_forward_cross_asset, selection_report,
    simulate_portfolio, stress_extra_roundtrip,
)

START=pd.Timestamp('2024-01-01T00:00:00Z')
END=pd.Timestamp('2026-09-20T23:00:00Z')
BASE='https://data.binance.vision/data/spot'
CACHE=Path('data_cache_r8'); CACHE.mkdir(exist_ok=True)

# Large/mid-cap liquid universe. Starts from current top-market-cap names that have/likely have
# Binance Spot USDT markets, then extends into the next liquid majors because the raw top 40
# contains stablecoins, tokenized dollars and exchange-specific assets not useful for this bot.
DEV_CANDIDATES=[
'BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT',
'XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT',
'ENAUSDT','ONDOUSDT','MNTUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT',
'ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT'
]
# Preserve the previously preregistered untouched outer holdout.
OUTER_HOLDOUT=['SHIBUSDT','OPUSDT','ARBUSDT']

AUDIT_FIXES=[
'R8.1 structural fix: global 180d training floor aligned to event-sampled density (1200 rows); setup floor and profitability gates unchanged.',
'R8: true separate classifier per setup (TREND_PULLBACK / BREAKOUT / RANGE).',
'R8: nested calibration: threshold selection and later verification are chronologically separated before OOS test.',
'R8: cross-sectional asset ranks and market-regime features are calculated against development universe only.',
'R6 selected signals were heavily serially duplicated; R7 event-samples/cools down persistent setups.',
'R6 calibration gated mainly on classification precision; R7 requires net expectancy, PF, symbol breadth and temporal block stability.',
'R6 sparse symbols could be excluded from calibration aggregate; R7 evaluates all selected calibration signals and uses coverage separately.',
'R6 risk-engine fields were configuration-only; R7 simulates sizing, concurrency, same-symbol exclusion, correlation, daily-loss and drawdown stops.',
'R6 stress test retrained under doubled slippage; R7 freezes OOS selections and only reprices their execution costs.',
'R6 labels assumed signal-close entry; R7 enters at the next bar open with gap-aware barriers.',
'R6 used fixed TP/SL/horizon across regimes; R7 uses ATR-normalized setup-specific barriers and horizons.',
'R6 setup rules were broad (including range entries anywhere in a range); R7 routes exclusive breakout/range/trend events and range buys near the lower range.',
'R6 breadth covered only six development assets; R7 breadth uses the available 30-40-asset development universe.',
]


def _read_zip_csv(content:bytes)->pd.DataFrame:
    with zipfile.ZipFile(BytesIO(content)) as zf:
        names=[n for n in zf.namelist() if n.endswith('.csv')]
        if not names: raise ValueError('zip has no csv')
        with zf.open(names[0]) as f: raw=pd.read_csv(f,header=None)
    raw=raw.iloc[:,:12]; raw.columns=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_base','taker_quote','ignore']
    ts=pd.to_numeric(raw.open_time,errors='coerce'); med=float(ts.dropna().median()); unit='us' if med>=1e14 else 'ms'
    raw['time']=pd.to_datetime(ts,unit=unit,utc=True); raw=raw.set_index('time')
    for c in ['open','high','low','close','volume','quote_volume']: raw[c]=pd.to_numeric(raw[c],errors='coerce')
    return raw[['open','high','low','close','volume','quote_volume']].dropna()


def _get(url:str)->bytes|None:
    for attempt in range(3):
        r=requests.get(url,timeout=45)
        if r.status_code==200:return r.content
        if r.status_code==404:return None
        if attempt==2:r.raise_for_status()
    return None


def download_symbol(symbol:str)->tuple[str,pd.DataFrame|None,str|None]:
    cache=CACHE/f'{symbol}_{START.date()}_{END.date()}_1h.parquet'
    try:
        if cache.exists():
            d=pd.read_parquet(cache); d.index=pd.to_datetime(d.index,utc=True)
        else:
            parts=[]
            for dt in pd.date_range(START.normalize(),pd.Timestamp('2026-08-01',tz='UTC'),freq='MS'):
                ym=dt.strftime('%Y-%m'); b=_get(f'{BASE}/monthly/klines/{symbol}/1h/{symbol}-1h-{ym}.zip')
                if b is not None: parts.append(_read_zip_csv(b))
            for dt in pd.date_range(pd.Timestamp('2026-09-01',tz='UTC'),END.normalize(),freq='D'):
                ymd=dt.strftime('%Y-%m-%d'); b=_get(f'{BASE}/daily/klines/{symbol}/1h/{symbol}-1h-{ymd}.zip')
                if b is not None: parts.append(_read_zip_csv(b))
            if not parts:return symbol,None,'NO_ARCHIVE_DATA'
            d=pd.concat(parts).sort_index(); d=d[~d.index.duplicated(keep='last')]; d=d.loc[(d.index>=START)&(d.index<=END)]
            if d.empty:return symbol,None,'EMPTY_RANGE'
            d.to_parquet(cache)
        # Accept later listings, but require at least 300 days and near-continuous hourly data while listed.
        span=(d.index.max()-d.index.min()).total_seconds()/86400
        if span<300:return symbol,None,f'INSUFFICIENT_HISTORY_{span:.0f}d'
        expected=int((d.index.max()-d.index.min())/pd.Timedelta(hours=1))+1
        completeness=len(d)/expected if expected>0 else 0
        if completeness<0.999:return symbol,None,f'HOURLY_COMPLETENESS_{completeness:.5f}'
        return symbol,d,None
    except Exception as e:
        return symbol,None,f'ERROR_{type(e).__name__}:{e}'


def download_universe(symbols:list[str],workers:int=8):
    data={}; skipped={}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs={ex.submit(download_symbol,s):s for s in symbols}
        for fut in as_completed(futs):
            s,d,err=fut.result()
            if d is None:
                skipped[s]=err; print(f'SKIP {s} {err}',flush=True)
            else:
                data[s]=d; print(f'DATA {s} rows={len(d)} from={d.index.min()} to={d.index.max()}',flush=True)
    return data,skipped


def fold_summary(f:pd.DataFrame):
    if f.empty:return {'folds':0}
    return {
        'folds':int(len(f)),
        'gate_open_folds':int((f.status=='TRADE_GATE_OPEN').sum()),
        'no_trade_calibration_folds':int(f.status.isin(['NO_TRADE_ROBUST_CALIBRATION','NO_TRADE_NESTED_CALIBRATION']).sum()),
        'no_trade_test_folds':int((f.status=='NO_TRADE_TEST').sum()),
        'insufficient_folds':int(f.status.str.contains('INSUFFICIENT',na=False).sum()),
    }


def dev_gate(port:dict,stress:dict):
    pf=port.get('profit_factor_cash'); spf=stress.get('profit_factor_cash')
    return {
        'trades_ok':port.get('trades',0)>=80,
        'portfolio_return_positive':port.get('portfolio_return',-1)>0,
        'pf_ok':pf is not None and (math.isinf(pf) or pf>=1.15),
        'dd_ok':port.get('max_drawdown',1)<0.08,
        'precision_ok':port.get('precision',0)>=0.48,
        'symbol_coverage_ok':len(port.get('symbols',{}))>=10,
        'stress_return_positive':stress.get('portfolio_return',-1)>0,
        'stress_pf_ok':spf is not None and (math.isinf(spf) or spf>=1.0),
        'no_dd_stop':not port.get('drawdown_stop_triggered',True),
    }


def main():
    cfg=Config()
    print('Downloading expanded development universe...',flush=True)
    data,skipped=download_universe(DEV_CANDIDATES)
    if 'BTCUSDT' not in data: raise RuntimeError('BTC reference unavailable')
    dev=[s for s in DEV_CANDIDATES if s in data]
    if len(dev)<25: raise RuntimeError(f'Only {len(dev)} development symbols survived integrity filters')
    print(f'DEV_UNIVERSE_COUNT={len(dev)} symbols={dev}',flush=True)
    print('Building R8 nested-expert dataset...',flush=True)
    ds=make_dataset(data,'BTCUSDT',cfg,breadth_symbols=dev)
    print(f'DATASET candidates={len(ds)} setups={ds.setup_type.value_counts().to_dict()} symbols={ds.symbol.nunique()}',flush=True)
    pred,folds=walk_forward_cross_asset(ds,cfg,development_symbols=dev)
    sel_report=selection_report(pred)
    accepted,port=simulate_portfolio(pred,data,cfg)
    extra=stress_extra_roundtrip(cfg,2.0)
    accepted_stress,stress=simulate_portfolio(pred,data,cfg,extra_roundtrip_cost=extra)
    gate=dev_gate(port,stress); dev_pass=all(gate.values())

    result={
        'version':'V10-R8.1-NESTED-SETUP-EXPERTS',
        'data_source':'Binance Spot public archive data.binance.vision',
        'period':[str(START),str(END)],
        'audit_fixes':AUDIT_FIXES,
        'requested_dev_candidates':DEV_CANDIDATES,
        'development_symbols':dev,
        'skipped_symbols':skipped,
        'outer_holdout_preregistered':OUTER_HOLDOUT,
        'outer_holdout_opened':False,
        'config':asdict(cfg),
        'dataset_candidates':int(len(ds)),
        'dataset_setups':ds.setup_type.value_counts().to_dict(),
        'fold_summary':fold_summary(folds),
        'raw_selected_report':sel_report,
        'portfolio_report':port,
        'frozen_double_slippage_report':stress,
        'development_gate_checks':gate,
        'development_pass_for_outer_holdout':dev_pass,
    }
    folds.to_csv('r8_dev_folds.csv',index=False)
    if not pred.empty: pred[pred.selected].to_csv('r8_dev_selected_signals.csv')
    if not accepted.empty: accepted.to_csv('r8_dev_accepted_trades.csv',index=False)
    if not accepted_stress.empty: accepted_stress.to_csv('r8_dev_accepted_trades_double_slippage.csv',index=False)

    if dev_pass:
        print('Development passed. Opening frozen outer holdout.',flush=True)
        hdata,hskip=download_universe(OUTER_HOLDOUT,workers=3); result['outer_holdout_skipped']=hskip
        if len(hdata)==len(OUTER_HOLDOUT):
            all_data={**data,**hdata}
            ds_h=make_dataset(all_data,'BTCUSDT',cfg,breadth_symbols=dev)
            pred_h,folds_h=walk_forward_cross_asset(ds_h,cfg,development_symbols=dev,test_symbols=OUTER_HOLDOUT)
            acc_h,port_h=simulate_portfolio(pred_h,all_data,cfg)
            _,stress_h=simulate_portfolio(pred_h,all_data,cfg,extra_roundtrip_cost=extra)
            result['outer_holdout_opened']=True; result['outer_holdout_fold_summary']=fold_summary(folds_h); result['outer_holdout_portfolio_report']=port_h; result['outer_holdout_double_slippage_report']=stress_h
            folds_h.to_csv('r8_outer_holdout_folds.csv',index=False)
            if not pred_h.empty: pred_h[pred_h.selected].to_csv('r8_outer_holdout_selected_signals.csv')
            if not acc_h.empty: acc_h.to_csv('r8_outer_holdout_accepted_trades.csv',index=False)
        else:
            result['outer_holdout_reason']='Holdout not opened because one or more preregistered assets failed data-integrity availability.'
    else:
        result['outer_holdout_reason']='Preserved unopened because R8 development did not pass all frozen gates.'

    Path('r8_real_result.json').write_text(json.dumps(result,indent=2,default=str))
    md=['# V10 R8 — Nested Setup Experts Validation','',f'- Development universe: {len(dev)} symbols',f'- Dataset candidates: {len(ds)}',f'- Holdout opened: {result["outer_holdout_opened"]}','','## Audit fixes']+[f'- {x}' for x in AUDIT_FIXES]+['','## Portfolio','```json',json.dumps(port,indent=2,default=str),'```','','## Frozen 2x slippage','```json',json.dumps(stress,indent=2,default=str),'```','','## Development gate','```json',json.dumps(gate,indent=2,default=str),'```','','## Fold summary','```json',json.dumps(result['fold_summary'],indent=2),'```']
    if result['outer_holdout_opened']: md += ['','## Outer holdout','```json',json.dumps(result['outer_holdout_portfolio_report'],indent=2,default=str),'```']
    else: md += ['','## Outer holdout',result['outer_holdout_reason']]
    Path('r8_real_report.md').write_text('\n'.join(md))
    print('===R8_RESULT_JSON==='); print(json.dumps(result,separators=(',',':'),default=str)); print('===END_R8_RESULT_JSON===')

if __name__=='__main__':main()
