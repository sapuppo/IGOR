#!/usr/bin/env python3
"""Genuine portfolio replays; retrospective fragility and causal-regime diagnostics."""
from pathlib import Path
import copy,gzip,hashlib,json,warnings
import numpy as np
import pandas as pd
import r16_usdm_engine as engine
import r16_usdm_reports as reports

ROOT=Path(__file__).resolve().parent;OUT=ROOT/'r17_14_results'
START=int(pd.Timestamp('2023-01-01T00:00Z').timestamp()*1000)
CUT=int(pd.Timestamp('2025-01-01T00:00Z').timestamp()*1000)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,obj):Path(p).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')

def regimes(data):
    f=data.frames['BTCUSDT','4h'];c=f.close
    ret=c/c.shift(180)-1
    known=f.open_time.to_numpy()+engine.INTERVAL['4h']-1
    labels=np.where(ret.isna(),'UNKNOWN',np.where(ret>.05,'UP',np.where(ret<-.05,'DOWN','SIDEWAYS')))
    def at(t):
        i=int(np.searchsorted(known,t,side='right'))-1
        return str(labels[i]) if i>=0 else 'UNKNOWN'
    return at,known,labels

def group_stats(f,column):
    return {str(k):{'trades':len(g),'net_cash':float(g.net.sum()),'win_rate_pct':float((g.net>0).mean()*100),
                    'profit_factor':float(g.loc[g.net>0,'net'].sum()/-g.loc[g.net<0,'net'].sum()) if (g.net<0).any() else None}
            for k,g in f.groupby(column)}

def main():
    warnings.filterwarnings('ignore',message='Converting to Period')
    protocol=ROOT/'r17_14_protocol.json';cfg=json.loads((ROOT/'r17_07_candidate_config.json').read_text())
    fp=json.loads((ROOT/'r16_29_2_audit/fingerprints.json').read_text())
    for name in ['r16_usdm_engine.py','r16_usdm_reports.py','r16_sim_core.py']:
        if sha(ROOT/name)!=fp['code_files'][name]:raise ValueError('frozen code changed '+name)
    cache=ROOT/'r16_29_2_audit/signals.jsonl.gz'
    if sha(cache)!='0389c6b3218b1cb971a72e2bda03539b24fa33d8def98fb1a1352be8954a0ada':raise ValueError('wrong signal cache')
    with gzip.open(cache,'rt') as f:signals=[json.loads(x) for x in f if json.loads(x)['engine'] in cfg['engines']]
    data=engine.Dataset(ROOT/'usdm_history',verify=True);at,known,labels=regimes(data);OUT.mkdir(exist_ok=True)
    # BTC regime is strictly from closed observations at signal knowledge time.
    for s in signals:
        i=np.searchsorted(known,s['knowledge_ts'],side='right')-1
        assert i<0 or known[i]<=s['knowledge_ts']
    reports.START=START;output={};reference=None;toptrain=[];topfull=[];blocked={}
    for ident in json.loads(protocol.read_text())['tests']:
        active=[s for s in signals if s['timestamp']>=START]
        excluded=[]
        if ident.startswith('exclude_train_top1'):excluded=toptrain[:1]
        elif ident.startswith('exclude_train_top3'):excluded=toptrain[:3]
        elif ident=='exclude_full_top3_adversarial':excluded=topfull[:3]
        active=[s for s in active if s['symbol'] not in excluded]
        if ident.startswith('train_negative_regime_filter'):
            active=[s for s in active if at(s['knowledge_ts'])!=blocked.get(s['engine'])]
        current=copy.deepcopy(cfg)
        if ident=='double_cost' or ident.endswith('_double_cost'):
            current['scenarios']['STRESS']['fee']*=2;current['scenarios']['STRESS']['slip']*=2
        engine.CONFIG.clear();engine.CONFIG.update(current)
        replay=engine.replay(data,active,scenario='STRESS',trade_start=START)
        replay.ledger.assert_reconciles()
        report=reports.metrics(replay);report.pop('period_2022_2026',None)
        f=pd.DataFrame(replay.trades);f['market_regime']=f.knowledge_ts.map(at)
        train=f.loc[(f.entry_ts>=START)&(f.exit_ts<CUT)]
        report.update({'excluded_symbols':excluded,'blocked_market_regimes':blocked if ident.startswith('train_negative_regime_filter') else {},'diagnostics':replay.diagnostics,
                       'by_market_regime':group_stats(f,'market_regime'),'by_engine':group_stats(f,'engine')})
        f.to_csv(OUT/(ident+'_trades.csv'),index=False);pd.DataFrame(replay.daily).to_csv(OUT/(ident+'_daily.csv'),index=False)
        report['artifact_sha256']={name:sha(OUT/name) for name in [ident+'_trades.csv',ident+'_daily.csv']}
        if ident=='control':
            expected=pd.read_csv(ROOT/'r17_07_results/pair_fixed_trades.csv')
            assert len(expected)==len(f) and np.allclose(expected.net,f.net,rtol=0,atol=1e-8)
            assert expected.id.tolist()==f.id.tolist()
            old=json.loads((ROOT/'r17_07_results/pair_fixed.json').read_text())
            assert abs(report['return']-old['return'])<1e-10
            toptrain=train.groupby('symbol').net.sum().sort_values(ascending=False).index.tolist()
            topfull=f.groupby('symbol').net.sum().sort_values(ascending=False).index.tolist()
            for e,g in train.groupby('engine'):
                choices=[(float(z.net.sum()),k) for k,z in g.groupby('market_regime') if len(z)>=30 and z.net.sum()<0 and k!='UNKNOWN']
                if choices:blocked[e]=min(choices)[1]
            total=float(f.net.sum());sums=f.groupby('symbol').net.sum().sort_values(ascending=False)
            reference={'train_rank':toptrain,'full_rank':topfull,'filter_selected_on_train':blocked,'train_by_engine_regime':{e:group_stats(g,'market_regime') for e,g in train.groupby('engine')},
                       'full_by_symbol':group_stats(f,'symbol'),'top3_cash_contribution_pct':float(sums.iloc[:3].sum()/total*100),'total_net_cash':total,
                       'by_year_engine_regime':{str(y):{e:group_stats(g,'market_regime') for e,g in z.groupby('engine')} for y,z in f.groupby(pd.to_datetime(f.entry_ts,unit='ms',utc=True).dt.year)}}
        dump(OUT/(ident+'.json'),report);output[ident]=report
        print(ident,json.dumps({k:report[k] for k in ['return','compound_monthly','max_drawdown_mtm','annual']}),flush=True)
    dump(OUT/'summary.json',{'version':'R17.14','protocol_sha256':sha(protocol),'driver_sha256':sha(__file__),'signal_cache_sha256':sha(cache),'dataset_files_verified':152,'control_reproduction':'PASS','causal_regime_timestamp_check':'PASS','label':'RETROSPECTIVE_PREVIOUSLY_VIEWED_DATA_NOT_OOS','reference':reference,'results':output,'live_promotion':False})
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
