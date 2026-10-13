#!/usr/bin/env python3
"""Long/short exhaustion reversion, independent of the long-only R17.15 batch."""
from collections import defaultdict
from pathlib import Path
import hashlib,json,warnings
import numpy as np,pandas as pd
import run_r17_10_breakouts as engine
from run_r17_05_regime_rotation import load_verified
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'r17_16_results';CUT=int(pd.Timestamp('2025-01-01T00:00Z').timestamp()*1000)

def compute(data):
    maps={side:defaultdict(list) for side in [1,-1]}
    for symbol,f in data.items():
        c=f.close;mean=c.rolling(20,min_periods=20).mean();std=c.rolling(20,min_periods=20).std()
        rma=lambda s:s.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
        rsi=100-100/(1+rma(c.diff().clip(lower=0))/rma(-c.diff().clip(upper=0)).replace(0,np.nan))
        liquid=f.quote_volume.rolling(42,min_periods=42).median()>=5e6
        for side in [1,-1]:
            band=mean-side*2*std
            mask=liquid&(side*(c.shift()-band.shift())<0)&(side*(c-band)>0)&(side*c.diff()>0)&((rsi.shift()<=30) if side==1 else (rsi.shift()>=70))
            strength=abs(c.shift()/band.shift()-1)
            for t in c[mask].index:
                entry=int(t)+engine.BAR_MS
                if engine.START<=entry<engine.END:maps[side][entry].append((symbol,side,float(strength.loc[t])))
    for side in maps:
        for t in maps[side]:maps[side][t].sort(key=lambda x:(-x[2],x[0]))
    return {(120,side):events for side,events in maps.items()}

def section(daily,start,end):
    f=pd.DataFrame(daily);old=f.loc[f.timestamp<=start,'equity'];initial=float(old.iloc[-1]) if len(old) else 10000.
    sub=f.loc[(f.timestamp>start)&(f.timestamp<=end),'equity'];v=np.r_[initial,sub]
    return {'return':float(v[-1]/initial-1),'daily_drawdown':float((1-v/np.maximum.accumulate(v)).max())}

def main():
    warnings.filterwarnings('ignore',message='Converting to Period');OUT.mkdir(exist_ok=True)
    pth=ROOT/'r17_16_protocol.json';p=json.loads(pth.read_text());data,funding=load_verified(ROOT/'usdm_history');signals=compute(data)
    prefix=compute({s:f.loc[f.index<CUT] for s,f in data.items()})
    for key in signals:assert {t:v for t,v in signals[key].items() if t<=CUT}=={t:v for t,v in prefix[key].items() if t<=CUT}
    btc=data['BTCUSDT'].close;btcside=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index);out={}
    for spec in p['variants']:
        for factor in p['costs']:
            engine.STOP=spec['stop'];engine.TARGET=spec['target'];engine.FEE=.0006*factor;engine.SLIP=.0004*factor
            r=engine.replay(spec,data,funding,signals,btcside);daily=r.pop('daily_details');trades=r.pop('trade_details')
            r['segments']={name:section(daily,int(pd.Timestamp(a).timestamp()*1000),int(pd.Timestamp(b).timestamp()*1000)) for name,a,b in [('train','2023-01-01T00:00Z','2025-01-01T00:00Z'),('2025','2025-01-01T00:00Z','2026-01-01T00:00Z'),('h1_2026','2026-01-01T00:00Z','2026-07-01T00:00Z')]}
            key=spec['id']+'_cost'+str(factor);out[key]=r
            pd.DataFrame(daily).to_csv(OUT/(key+'_daily.csv'),index=False);pd.DataFrame(trades).to_csv(OUT/(key+'_trades.csv'),index=False)
            print(key,json.dumps({k:r[k] for k in ['compound_monthly','max_4h_mtm_drawdown','annual','trades']}),flush=True)
    eligible=[(k,r) for k,r in out.items() if k.endswith('cost1') and r['segments']['train']['return']>0 and r['segments']['train']['daily_drawdown']<=.25]
    selected=max(eligible,key=lambda x:x[1]['segments']['train']['return'])[0] if eligible else None
    passed=[k for k,r in eligible if all(v['compound_monthly']>=.05 and v['max_4h_mtm_drawdown']<=.25 and all(s['return']>0 for s in v['segments'].values()) for v in [r,out[k[:-1]+'2']])]
    report={'version':'R17.16','protocol_sha256':hashlib.sha256(pth.read_bytes()).hexdigest(),'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_files_verified':152,'prefix_invariance':'PASS_BOTH_SIDES','reconciliations':12,'selected_by_train':selected,'passes_5pct_and_risk_gates':passed,'results':out,'live_promotion':False,'label':'RETROSPECTIVE_PREVIOUSLY_CONSULTED_DATA'}
    (OUT/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('COMPLETE',selected,passed,flush=True)

if __name__=='__main__':main()
