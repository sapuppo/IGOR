#!/usr/bin/env python3
"""Causal-in-time fixed capital sleeves; exploratory source selection disclosed."""
from pathlib import Path
import hashlib,json,math
import numpy as np,pandas as pd
import run_r17_10_breakouts as short
from run_r17_05_regime_rotation import load_verified
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'r17_11_results';CAP=10000.

def read_equity(path,stop_at_midnight):
    frame=pd.read_csv(path)
    time=pd.to_datetime(frame.timestamp,unit='ms',utc=True)
    if stop_at_midnight:time=time-pd.Timedelta(milliseconds=1)
    idx=time.dt.strftime('%Y-%m-%d');s=pd.Series(frame.equity.to_numpy(dtype=float),index=idx)
    assert s.index.is_unique and len(s)==1277 and np.isfinite(s).all()
    return s

def evaluate(a,b,w):
    eq=w*a+(1-w)*b
    assert len(eq)==1277 and eq.notna().all() and eq.min()>0
    vals=np.r_[CAP,eq.to_numpy()]
    dd=float((1-vals/np.maximum.accumulate(vals)).max())
    dates=pd.to_datetime(eq.index,utc=True)
    series=pd.Series(eq.to_numpy(),index=dates)
    m=series.resample('ME').last();y=series.resample('YE').last()
    monthly=m/m.shift(fill_value=CAP)-1;annual=y/y.shift(fill_value=CAP)-1
    train=series.loc[series.index<'2025-01-01']
    trainval=np.r_[CAP,train.to_numpy()]
    return {'weight_pair_fixed':w,'weight_breakdown':1-w,'return':eq.iloc[-1]/CAP-1,
            'compound_monthly':(eq.iloc[-1]/CAP)**(1/len(m))-1,
            'max_daily_mtm_drawdown':dd,'train_2023_2024':{
                'return':train.iloc[-1]/CAP-1,
                'max_daily_mtm_drawdown':float((1-trainval/np.maximum.accumulate(trainval)).max())},
            'months_ge_20':int((monthly>=.2).sum()),
            'monthly':{str(k.to_period('M')):float(v) for k,v in monthly.items()},
            'annual':{str(k.year):float(v) for k,v in annual.items()},
            'daily_equity_sha256':hashlib.sha256(json.dumps(eq.tolist(),separators=(',',':')).encode()).hexdigest(),
            'daily':pd.DataFrame({'date':eq.index,'equity':eq.to_numpy()})}

def main():
    OUT.mkdir(exist_ok=True)
    protocol=json.loads((ROOT/'r17_11_protocol.json').read_text())
    a=read_equity(ROOT/'r17_07_results/pair_fixed_daily.csv',False)
    b=read_equity(ROOT/'r17_10_results/short_20d_7d_daily.csv',True)
    assert a.index.equals(b.index)
    results={}
    for w in protocol['weights_A']:
        r=evaluate(a,b,w); r['daily'].to_csv(OUT/(f'hybrid_pair{int(w*100)}_short{round((1-w)*100)}_daily.csv'),index=False)
        r.pop('daily'); results[str(w)]=r
        print('WEIGHT',w,'return',r['return'],'monthly',r['compound_monthly'],'2026',r['annual']['2026'],'dd',r['max_daily_mtm_drawdown'],flush=True)
    elig=[r for r in results.values() if r['train_2023_2024']['return']>0 and r['train_2023_2024']['max_daily_mtm_drawdown']<=.2]
    selected=max(elig,key=lambda x:(x['train_2023_2024']['return'],-x['train_2023_2024']['max_daily_mtm_drawdown']))['weight_pair_fixed'] if elig else None
    data,funding=load_verified(ROOT/'usdm_history')
    spec=next(x for x in json.loads((ROOT/'r17_10_protocol.json').read_text())['variants'] if x['id']=='short_20d_7d')
    signals,btc_side=short.precompute(data,[spec])
    short.FEE=.0012; short.SLIP=.0008
    r=short.replay(spec,data,funding,signals,btc_side)
    detail=r.pop('daily_details'); r.pop('trade_details')
    pd.DataFrame(detail).to_csv(OUT/'breakdown_double_cost_daily.csv',index=False)
    r['scenario']='fee_0.12pct_slip_0.08pct_each_side'; r['daily_artifact_sha256']=hashlib.sha256((OUT/'breakdown_double_cost_daily.csv').read_bytes()).hexdigest()
    b2=read_equity(OUT/'breakdown_double_cost_daily.csv',True)
    results2={}
    for w in protocol['weights_A']:
        out=evaluate(a,b2,w);out.pop('daily');results2[str(w)]=out
        print('DOUBLE',w,'monthly',out['compound_monthly'],'2026',out['annual']['2026'],'dd',out['max_daily_mtm_drawdown'],flush=True)
    report={'version':'R17.11','protocol_sha256':hashlib.sha256((ROOT/'r17_11_protocol.json').read_bytes()).hexdigest(),
       'selected_by_2023_2024':selected,'hybrids':results,'breakdown_double_cost':r,'hybrids_breakdown_double_cost':results2,
       'label':'2026-contaminated component choice, exploratory diagnostics only; drawdown measured at daily closes'}
    (OUT/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('COMPLETE',flush=True)
if __name__=='__main__':main()
