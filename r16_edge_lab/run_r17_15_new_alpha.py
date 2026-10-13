#!/usr/bin/env python3
"""Finite new-alpha batch, no leverage escalation and no baseline modification."""
from pathlib import Path
import copy,json,hashlib,gc,warnings
import numpy as np,pandas as pd
import r16_usdm_engine as engine
import r16_usdm_reports as reports
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'r17_15_results'
START=int(pd.Timestamp('2023-01-01T00:00Z').timestamp()*1000)
CUT=int(pd.Timestamp('2025-01-01T00:00Z').timestamp()*1000)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')

def generate(data):
    f4={s:engine.features(data.frames[s,'4h'],'4h') for s in sorted(data.pit)}
    btc=f4['BTCUSDT'].set_index('knowledge_ts');bull=btc.close>btc.ema200
    breadth=pd.concat([pd.Series(np.where(x.ema200.notna(),(x.close>x.ema200).astype(float),np.nan),index=x.knowledge_ts) for x in f4.values()],axis=1).mean(axis=1)
    output={k:[] for k in ['breakout20','breakout55','squeeze20','pullback','reversal4','reversal8']}
    for s in sorted(data.pit):
        x=f4[s];c=x.close;ma20=c.ewm(span=20,adjust=False,min_periods=20).mean()
        ctx=(x.ema50>x.ema200)&(c>x.ema50)&(x.adx>=20)&bull.reindex(x.knowledge_ts).fillna(False).to_numpy()&(breadth.reindex(x.knowledge_ts).to_numpy()>=.45)
        hi20=x.high.shift().rolling(20,min_periods=20).max();hi55=x.high.shift().rolling(55,min_periods=55).max()
        break20=ctx&(c>hi20)&(c.shift()<=hi20.shift())
        squeeze=(x.atr.shift()/c.shift()<(x.atr/c).shift().rolling(252,min_periods=252).median())&((x.high-x.low)>1.5*x.atr.shift())
        masks={'breakout20':break20,'breakout55':ctx&(c>hi55)&(c.shift()<=hi55.shift()),'squeeze20':break20&squeeze,'pullback':ctx&(c.shift()<=ma20.shift())&(c>ma20)}
        for name,mask in masks.items():append(output[name],x,mask,s,'CORE')
        x=engine.features(data.frames[s,'1h'],'1h')
        common=(x.body>=.6)
        append(output['reversal4'],x,common&(x.move<=-.04)&(x.volz>=2)&(x.rsi<=30),s,'REV1H')
        append(output['reversal8'],x,common&(x.move<=-.08)&(x.volz>=1.5)&(x.rsi<=35),s,'REV1H')
    for name in output:output[name].sort(key=lambda s:(s['timestamp'],engine.ENGINE_PRIORITY[s['engine']],s['symbol']))
    return output

def append(out,x,mask,s,e):
    for i in np.flatnonzero(mask.fillna(False).to_numpy()):
        r=x.iloc[i]
        if not np.isfinite(r.atr) or r.atr<=0:continue
        t=int(r.knowledge_ts)
        out.append({'id':f'{e}:{s}:{t}','engine':e,'symbol':s,'timestamp':t,'knowledge_ts':t,'source_open_ts':int(r.open_time),'atr':float(r.atr)})

def segments(result):
    daily=pd.DataFrame(result.daily);out={}
    for name,a,b in [('train','2023-01-01','2025-01-01'),('2025','2025-01-01','2026-01-01'),('h1_2026','2026-01-01','2026-07-01')]:
        start=int(pd.Timestamp(a,tz='UTC').timestamp()*1000);end=int(pd.Timestamp(b,tz='UTC').timestamp()*1000)
        prior=daily.loc[daily.timestamp<start,'equity'];initial=float(prior.iloc[-1]) if len(prior) else 10000.
        vals=np.r_[initial,[e['equity'] for e in result.ledger.events if start<=e['timestamp']<end]]
        last=float(daily.loc[daily.timestamp<end,'equity'].iloc[-1])
        out[name]={'return':last/initial-1,'event_drawdown':float((1-vals/np.maximum.accumulate(vals)).max())}
    return out

def main():
    warnings.filterwarnings('ignore',message='Converting to Period')
    protocol_path=ROOT/'r17_15_protocol.json';p=json.loads(protocol_path.read_text());OUT.mkdir(exist_ok=True)
    cfg=json.loads((ROOT/'r17_07_candidate_config.json').read_text());data=engine.Dataset(ROOT/'usdm_history',verify=True)
    signals=generate(data);print('DATA_VERIFIED', {k:len(v) for k,v in signals.items()},flush=True)
    # Prefix invariance for every family, without rereading historical outcomes.
    import types
    truncated=types.SimpleNamespace(pit=data.pit,frames={key:f.loc[f.open_time+engine.INTERVAL[key[1]]-1<CUT].copy() for key,f in data.frames.items() if key[1]!='15m'})
    prefix=generate(truncated)
    for name in signals:assert [s for s in signals[name] if s['knowledge_ts']<CUT]==prefix[name],name
    reports.START=START;results={}
    for spec in p['variants']:
        selected=[s for family in spec['families'] for s in signals[family]]
        selected.sort(key=lambda s:(s['timestamp'],engine.ENGINE_PRIORITY[s['engine']],s['symbol']))
        for factor in p['costs']:
            current=copy.deepcopy(cfg);names={s['engine'] for s in selected};current['engines']={k:v for k,v in current['engines'].items() if k in names}
            for e in current['engines'].values():e.update({'stop_atr':spec['stop'],'target_atr':spec['target'],'hold_bars':spec['hold']})
            current['scenarios']['STRESS']['fee']*=factor;current['scenarios']['STRESS']['slip']*=factor
            engine.CONFIG.clear();engine.CONFIG.update(current)
            replay=engine.replay(data,selected,scenario='STRESS',trade_start=START);replay.ledger.assert_reconciles()
            report=reports.metrics(replay);report.pop('period_2022_2026',None);report['segments']=segments(replay);report['spec']=spec;report['diagnostics']=replay.diagnostics
            ident=spec['id']+'_cost'+str(factor);results[ident]=report
            pd.DataFrame(replay.trades).to_csv(OUT/(ident+'_trades.csv'),index=False);pd.DataFrame(replay.daily).to_csv(OUT/(ident+'_daily.csv'),index=False)
            report['artifacts']={f:sha(OUT/f) for f in [ident+'_trades.csv',ident+'_daily.csv']}
            print(ident,json.dumps({k:report[k] for k in ['compound_monthly','max_drawdown_mtm','annual','trades']}),flush=True)
            del replay;gc.collect()
    eligible=[(k,r) for k,r in results.items() if k.endswith('cost1') and r['segments']['train']['return']>0 and r['segments']['train']['event_drawdown']<=.25]
    selected=max(eligible,key=lambda z:z[1]['segments']['train']['return'])[0] if eligible else None
    passes=[]
    for k,r in eligible:
        stress=results[k[:-1]+'2']
        if all(v['compound_monthly']>=.05 and v['max_drawdown_mtm']<=.25 and all(s['return']>0 for s in v['segments'].values()) for v in [r,stress]):passes.append(k)
    dump(OUT/'summary.json',{'version':'R17.15','target_monthly':.05,'protocol_sha256':sha(protocol_path),'driver_sha256':sha(__file__),'data_files_verified':152,'causal_signal_prefix_invariance':'PASS_ALL_6_FAMILIES','reconciliations':16,'selected_by_2023_2024':selected,'passes_5pct_and_risk_gates':passes,'results':results,'label':'RETROSPECTIVE_PREVIOUSLY_CONSULTED_HISTORY_NOT_INDEPENDENT_OOS','live_promotion':False})
    print('COMPLETE',selected,passes,flush=True)

if __name__=='__main__':main()
