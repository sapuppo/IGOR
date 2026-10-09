#!/usr/bin/env python3
"""Finite retrospective experiment. Does not alter the paper or baseline robot."""
from collections import defaultdict
from pathlib import Path
import gzip,hashlib,json,math
import numpy as np
import pandas as pd
import run_r17_10_breakouts as engine

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'r17_13_results'

def load_research_inputs():
    """Verify every actual input to this 4h experiment; do not bless 15m execution data."""
    root=ROOT/'usdm_history';manifest=json.loads((root/'manifest.json').read_text())
    if manifest['dataset_manifest_sha256']!='a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041':raise ValueError('wrong manifest')
    symbols={x['symbol'] for x in manifest['symbols'] if x['eligible']}
    data={};funding={};verified=[]
    for e in manifest['files']:
        if e['symbol'] not in symbols or not (e['kind']=='funding' or e.get('interval')=='4h'):continue
        p=root/('funding' if e['kind']=='funding' else 'klines/4h')/(e['symbol']+'.csv.gz')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=e['sha256']:raise ValueError('research input hash mismatch '+str(p))
        verified.append(str(p.relative_to(ROOT)))
        with gzip.open(p,'rt') as handle:f=pd.read_csv(handle)
        key='fundingTime' if e['kind']=='funding' else 'open_time'
        if f[key].duplicated().any() or not f[key].is_monotonic_increasing:raise ValueError('unordered data')
        if e['kind']=='funding':
            events=defaultdict(list)
            for x in f.itertuples():
                if not np.isfinite(x.fundingRate):raise ValueError('bad funding')
                if engine.START<=x.fundingTime<engine.END:events[x.fundingTime//engine.BAR_MS*engine.BAR_MS].append((int(x.fundingTime),float(x.fundingRate)))
            funding[e['symbol']]=events
        else:
            cols=['open','high','low','close','quote_volume']
            if not np.isfinite(f[cols]).all().all() or (f[cols[:4]]<=0).any().any() or (f.quote_volume<0).any():raise ValueError('bad prices')
            if (f.high<f[['open','low','close']].max(axis=1)).any() or (f.low>f[['open','high','close']].min(axis=1)).any():raise ValueError('bad OHLC')
            data[e['symbol']]=f.set_index('open_time')
    if len(symbols)!=38 or set(data)!=symbols or set(funding)!=symbols or len(verified)!=76:raise ValueError('incomplete research inputs')
    return data,funding,verified

def signals_for(data,spec):
    events=defaultdict(list); side=1 if spec['direction']=='long' else -1
    for symbol,f in data.items():
        c=f.close;fast=c.ewm(span=20,adjust=False,min_periods=20).mean()
        slow=c.ewm(span=120,adjust=False,min_periods=120).mean()
        tr=pd.concat([f.high-f.low,(f.high-c.shift()).abs(),(f.low-c.shift()).abs()],axis=1).max(axis=1)
        atr=tr.rolling(14,min_periods=14).mean()/c
        volume=f.quote_volume.shift().rolling(42,min_periods=42).median()
        mask=(f.quote_volume.rolling(42,min_periods=42).median()>=5e6)&(atr<=.06)&(side*(fast-slow)>0)&(side*(c-slow)>0)
        if spec['family']=='filtered_breakout':
            extreme=(f.high.shift().rolling(120).max() if side==1 else f.low.shift().rolling(120).min())
            mask &= (side*(c/extreme-1)>0)&(f.quote_volume>=1.2*volume)
            strength=side*(c/extreme-1)
        else:
            mask &= (side*(c.shift()-fast.shift())<=0)&(side*(c-fast)>0)
            strength=side*(c/fast-1)
        for timestamp in c[mask].index:
            entry=int(timestamp)+engine.BAR_MS
            if engine.START<=entry<engine.END:events[entry].append((symbol,side,float(strength.loc[timestamp])))
    for t in events:events[t].sort(key=lambda x:(-x[2],x[0]))
    return {(120,side):events}

def section(daily,start,end):
    full=pd.DataFrame(daily); prior=full.loc[full.timestamp<=start,'equity']
    initial=float(prior.iloc[-1]) if len(prior) else engine.CAPITAL
    sub=full.loc[(full.timestamp>start)&(full.timestamp<=end)]
    arr=np.r_[initial,sub.equity.to_numpy()]
    return {'return_pct':100*(arr[-1]/initial-1),'daily_drawdown_pct':100*float((1-arr/np.maximum.accumulate(arr)).max())}

def main():
    protocol_path=ROOT/'r17_13_protocol.json';protocol=json.loads(protocol_path.read_text());OUT.mkdir(exist_ok=True)
    data,funding,verified=load_research_inputs();print('76_RESEARCH_INPUTS_VERIFIED; FULL_EXECUTION_DATASET_NOT_CLEARED',flush=True)
    btc=data['BTCUSDT'].close;btc_side=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index)
    output={}
    for spec in protocol['variants']:
        signals=signals_for(data,spec)
        for factor in protocol['cost_scenarios']:
            engine.STOP=spec['stop'];engine.TARGET=spec['target'];engine.FEE=.0006*factor;engine.SLIP=.0004*factor
            result=engine.replay(spec,data,funding,signals,btc_side)
            trades=result.pop('trade_details');daily=result.pop('daily_details')
            result['segments']={name:section(daily,int(pd.Timestamp(a).timestamp()*1000),int(pd.Timestamp(b).timestamp()*1000)) for name,a,b in [('train','2023-01-01T00:00Z','2025-01-01T00:00Z'),('year_2025','2025-01-01T00:00Z','2026-01-01T00:00Z'),('h1_2026','2026-01-01T00:00Z','2026-07-01T00:00Z')]}
            key=spec['id']+'_cost'+str(factor);output[key]=result
            pd.DataFrame(trades).to_csv(OUT/(key+'_trades.csv'),index=False)
            pd.DataFrame(daily).to_csv(OUT/(key+'_daily.csv'),index=False)
            print(key,round(result['compound_monthly']*100,3),result['segments'],flush=True)
    base=[(k,r) for k,r in output.items() if k.endswith('_cost1')]
    eligible=[(k,r) for k,r in base if r['segments']['train']['return_pct']>0 and r['segments']['train']['daily_drawdown_pct']<=20]
    selected=max(eligible,key=lambda x:x[1]['segments']['train']['return_pct'])[0] if eligible else None
    accepted=[]
    for key,r in eligible:
        stressed=output[key[:-1]+'2']
        if r['segments']['year_2025']['return_pct']>0 and r['segments']['h1_2026']['return_pct']>0 and stressed['return']>0 and stressed['segments']['year_2025']['return_pct']>0 and stressed['segments']['h1_2026']['return_pct']>0:accepted.append(key)
    # Diagnostics on the existing components: actual money P&L, not additive percentages.
    diagnostics={}
    for label,path in [('pair_fixed',ROOT/'r17_07_results/pair_fixed_trades.csv'),('short20d',ROOT/'r17_10_results/short_20d_7d_trades.csv')]:
        f=pd.read_csv(path);groups=f.groupby('reason').net.agg(['count','sum','mean'])
        wins=float(f.loc[f.net>0,'net'].sum());losses=float(-f.loc[f.net<0,'net'].sum())
        diagnostics[label]={'trades':len(f),'win_rate_pct':float((f.net>0).mean()*100),'profit_factor':wins/losses if losses else None,'net_pnl':float(f.net.sum()),'by_exit':groups.to_dict('index')}
    report={'version':'R17.13','label':'RETROSPECTIVE_DIAGNOSTIC_PREVIOUSLY_CONSULTED_DATA','verified_research_input_files':verified,'full_execution_dataset_cleared':False,'protocol_sha256':hashlib.sha256(protocol_path.read_bytes()).hexdigest(),'selected_by_train':selected,'passes_rejection_gates':accepted,'results':output,'existing_diagnostics':diagnostics,'live_promotion':False}
    (OUT/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('COMPLETE',selected,accepted,flush=True)

if __name__=='__main__':main()
