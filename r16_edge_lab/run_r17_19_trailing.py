#!/usr/bin/env python3
"""New causal trailing exit; independent finite alpha test."""
from collections import defaultdict
from pathlib import Path
import hashlib,json,warnings
import numpy as np,pandas as pd
import r17_19_trailing_engine as engine
import r16_usdm_engine as features
from run_r17_05_regime_rotation import load_verified
from run_r17_16_band_reversion import section,CUT
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'r17_19_results'

def prepare(data):
    maps={side:defaultdict(list) for side in [1,-1]}
    for symbol,f in data.items():
        raw=f.reset_index();raw['volume']=0.
        x=features.features(raw,'4h').set_index('open_time');f['atr']=x.atr
        c=f.close;liquid=f.quote_volume.rolling(42,min_periods=42).median()>=5e6
        for side in [1,-1]:
            extreme=f.high.shift().rolling(55).max() if side==1 else f.low.shift().rolling(55).min()
            ratio=c/extreme-1
            mask=liquid&(side*ratio>0)&(side*ratio.shift()<=0)&(side*(x.ema50-x.ema200)>0)&(x.adx>=20)
            for t in c[mask].index:
                entry=int(t)+engine.BAR_MS
                if engine.START<=entry<engine.END:maps[side][entry].append((symbol,side,float(abs(ratio.loc[t]))))
    for side in maps:
        for t in maps[side]:maps[side][t].sort(key=lambda x:(-x[2],x[0]))
    return {(55,side):events for side,events in maps.items()}

def main():
    warnings.filterwarnings('ignore',message='Converting to Period');OUT.mkdir(exist_ok=True)
    pth=ROOT/'r17_19_protocol.json';p=json.loads(pth.read_text());data,funding=load_verified(ROOT/'usdm_history');signals=prepare(data)
    prefix_data={s:f.loc[f.index<CUT].copy() for s,f in data.items()};prefix=prepare(prefix_data)
    for key in signals:assert {t:v for t,v in signals[key].items() if t<=CUT}=={t:v for t,v in prefix[key].items() if t<=CUT}
    for s in data:assert np.allclose(data[s].loc[prefix_data[s].index,'atr'],prefix_data[s].atr,equal_nan=True)
    btc=data['BTCUSDT'].close;btcside=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index);out={}
    for spec in p['variants']:
        for factor in p['costs']:
            engine.STOP=.05;engine.FEE=.0006*factor;engine.SLIP=.0004*factor
            r=engine.replay(spec,data,funding,signals,btcside);daily=r.pop('daily_details');trades=r.pop('trade_details')
            r['segments']={name:section(daily,int(pd.Timestamp(a).timestamp()*1000),int(pd.Timestamp(b).timestamp()*1000)) for name,a,b in [('train','2023-01-01T00:00Z','2025-01-01T00:00Z'),('2025','2025-01-01T00:00Z','2026-01-01T00:00Z'),('h1_2026','2026-01-01T00:00Z','2026-07-01T00:00Z')]}
            key=spec['id']+'_cost'+str(factor);out[key]=r
            pd.DataFrame(daily).to_csv(OUT/(key+'_daily.csv'),index=False);pd.DataFrame(trades).to_csv(OUT/(key+'_trades.csv'),index=False)
            print(key,json.dumps({k:r[k] for k in ['compound_monthly','max_4h_mtm_drawdown','annual','trades']}),flush=True)
    eligible=[(k,r) for k,r in out.items() if k.endswith('cost1') and r['segments']['train']['return']>0 and r['segments']['train']['daily_drawdown']<=.25]
    selected=max(eligible,key=lambda x:x[1]['segments']['train']['return'])[0] if eligible else None
    passed=[k for k,r in eligible if all(v['compound_monthly']>=.05 and v['max_4h_mtm_drawdown']<=.25 and all(s['return']>0 for s in v['segments'].values()) for v in [r,out[k[:-1]+'2']])]
    report={'version':'R17.19','protocol_sha256':hashlib.sha256(pth.read_bytes()).hexdigest(),'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'trailing_engine_sha256':hashlib.sha256((ROOT/'r17_19_trailing_engine.py').read_bytes()).hexdigest(),'data_files_verified':152,'prefix_invariance':'PASS_SIGNALS_AND_ATR','reconciliations':12,'selected_by_train':selected,'passes_5pct_and_risk_gates':passed,'results':out,'live_promotion':False,'label':'RETROSPECTIVE_PREVIOUSLY_CONSULTED_DATA'}
    (OUT/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print('COMPLETE',selected,passed,flush=True)

if __name__=='__main__':main()
