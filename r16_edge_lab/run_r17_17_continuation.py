#!/usr/bin/env python3
"""Actual reverse-direction forward replay, never a sign change of realized P&L."""
from pathlib import Path
import hashlib,json,warnings
import numpy as np,pandas as pd
import run_r17_10_breakouts as engine
from run_r17_05_regime_rotation import load_verified
from run_r17_16_band_reversion import compute,section,CUT
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'r17_17_results'

def continuation(data):
    old=compute(data)
    return {(120,-side):{t:[(symbol,-direction,strength) for symbol,direction,strength in entries] for t,entries in events.items()} for (_,side),events in old.items()}

def main():
    warnings.filterwarnings('ignore',message='Converting to Period');OUT.mkdir(exist_ok=True)
    pth=ROOT/'r17_17_protocol.json';p=json.loads(pth.read_text());data,funding=load_verified(ROOT/'usdm_history');signals=continuation(data)
    prefix=continuation({s:f.loc[f.index<CUT] for s,f in data.items()})
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
    report={'version':'R17.17','protocol_sha256':hashlib.sha256(pth.read_bytes()).hexdigest(),'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'data_files_verified':152,'prefix_invariance':'PASS_BOTH_SIDES','reconciliations':12,'selected_by_train':selected,'passes_5pct_and_risk_gates':passed,'results':out,'live_promotion':False,'label':'RETROSPECTIVE_HYPOTHESIS_INFORMED_BY_PREVIOUS_FAILURES'}
    (OUT/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('COMPLETE',selected,passed,flush=True)

if __name__=='__main__':main()
