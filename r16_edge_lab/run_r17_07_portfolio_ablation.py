"""Execute only preregistered finite R17.07 portfolio configurations."""
from pathlib import Path
import copy, gc, gzip, hashlib, json, time, warnings
import numpy as np
import pandas as pd
import r16_usdm_engine as engine
import r16_usdm_reports as reports

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'r17_07_results'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,obj): p.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')

def main():
    warnings.filterwarnings('ignore',message='Converting to PeriodArray')
    protocol=json.loads((ROOT/'r17_07_protocol.json').read_text())
    frozen=copy.deepcopy(engine.CONFIG)
    fp=json.loads((ROOT/'r16_29_2_audit/fingerprints.json').read_text())
    for name in ['r16_usdm_engine.py','r16_usdm_reports.py','r16_sim_core.py']:
        assert sha(ROOT/name)==fp['code_files'][name],name
    cache=ROOT/'r16_29_2_audit/signals.jsonl.gz'
    assert sha(cache)==protocol['signal_cache_sha256']
    with gzip.open(cache,'rt') as f: signals=[json.loads(x) for x in f]
    OUT.mkdir(exist_ok=True)
    start=int(pd.Timestamp(protocol['start']).timestamp()*1000)
    cutoff=int(pd.Timestamp('2025-01-01T00:00:00Z').timestamp()*1000)
    reports.START=start
    print('Loading verified dataset',flush=True)
    data=engine.Dataset(ROOT/'usdm_history',verify=True)
    results={}
    def run(spec,double_cost=False):
        cfg=copy.deepcopy(frozen)
        cfg['engines']={k:v for k,v in cfg['engines'].items() if k in spec['engines']}
        for v in cfg['engines'].values(): v['risk']*=spec['risk_scale']
        cfg['per_position_cap']=spec['cap']
        if spec['fixed_multiplier'] is not None:
            cfg['regime_hot_multiplier']=cfg['regime_cold_multiplier']=spec['fixed_multiplier']
        if double_cost:
            cfg['scenarios']['STRESS']['fee']*=2
            cfg['scenarios']['STRESS']['slip']*=2
        engine.CONFIG.clear(); engine.CONFIG.update(cfg)
        ident=spec['id']+('_double_cost' if double_cost else '')
        print('RUN '+ident,flush=True); began=time.monotonic()
        result=engine.replay(data,[s for s in signals if s['engine'] in cfg['engines']],scenario='STRESS',trade_start=start)
        result.ledger.assert_reconciles()
        report=reports.metrics(result)
        report.pop('period_2022_2026',None)
        monthly=report['monthly']; train=[v for k,v in monthly.items() if k<'2025-01']
        events=np.array([e['equity'] for e in result.ledger.events if e['timestamp']<cutoff])
        train_dd=float((1-events/np.maximum.accumulate(events)).max())
        report['selection_window']={'return':float(np.prod(1+np.array(train))-1),'max_drawdown':train_dd,'months':len(train)}
        report['months_at_least_20_percent']=sum(v>=.2 for v in monthly.values())
        report['configuration']=cfg
        report['diagnostics']=result.diagnostics
        report['ledger']=result.ledger.manifest()
        report['elapsed_seconds']=time.monotonic()-began
        pd.DataFrame(result.daily).to_csv(OUT/(ident+'_daily.csv'),index=False)
        pd.DataFrame(result.trades).to_csv(OUT/(ident+'_trades.csv'),index=False)
        report['artifact_sha256']={p.name:sha(p) for p in [OUT/(ident+'_daily.csv'),OUT/(ident+'_trades.csv')]}
        dump(OUT/(ident+'.json'),report)
        print(json.dumps({'id':ident,'return':report['return'],'monthly':report['compound_monthly'],'dd':report['max_drawdown_mtm'],'2026':report['annual'].get('2026'),'gaps':result.diagnostics['missing_active_bars'],'seconds':report['elapsed_seconds']}),flush=True)
        del result; gc.collect()
        return report
    for spec in protocol['variants']:
        results[spec['id']]=run(spec)
    eligible=[s for s in protocol['variants'] if results[s['id']]['selection_window']['return']>0 and results[s['id']]['selection_window']['max_drawdown']<=.20 and results[s['id']]['diagnostics']['missing_active_bars']==0]
    chosen=max(eligible,key=lambda s:(results[s['id']]['selection_window']['return'],-results[s['id']]['selection_window']['max_drawdown'])) if eligible else None
    extra=run(chosen,True) if chosen else None
    dump(OUT/'summary.json',{'protocol_sha256':sha(ROOT/'r17_07_protocol.json'),'driver_sha256':sha(Path(__file__)),'selected_by_2023_2024':chosen['id'] if chosen else None,'results':results,'selected_double_cost':extra,'status':'RETROSPECTIVE_DIAGNOSTIC_NOT_VALIDATED_PROFIT'})
    print('COMPLETE',flush=True)

if __name__=='__main__': main()
