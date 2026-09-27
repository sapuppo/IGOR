"""Preregistered H2 4h trend shorts; isolated from frozen alpha code."""
import argparse
import gc
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

from r16_sim_core import PortfolioLedger
import r16_30_short_engine as trial
from r16_usdm_reports import metrics

parser=argparse.ArgumentParser()
for name in ('audit-root','data-root','gap-root','funding-mark-root','h1-root','out'):
    parser.add_argument('--'+name,type=Path,required=True)
args=parser.parse_args()
out=args.out;out.mkdir(parents=True,exist_ok=True)

def fixtures():
    p={'side':-1,'stop':103.,'target':94.,'deadline':10**12}
    assert trial.exit_reference(p,[104.,105.,103.,104.],0,at_open=True)==(104.,'STOP_GAP')
    assert trial.exit_reference(p,[93.,95.,92.,93.],0,at_open=True)==(94.,'TARGET_GAP')
    assert trial.exit_reference(p,[100.,105.,92.,95.],1)==(103.,'STOP_AMBIGUOUS')
    long={'side':1,'stop':97.,'target':106.,'deadline':10**12}
    assert trial.exit_reference(long,[100.,107.,96.,100.],1)==(97.,'STOP_AMBIGUOUS')
    l=PortfolioLedger(10000.,1.,.06)
    ok,reason=l.open(0,'short-fixture','CORE_SHORT','BTCUSDT',-1,1.,99.98,102.98,.0004,.0004,100.,.0002)
    assert ok,reason
    l.funding_event(1,'BTCUSDT',.001)
    assert l.funding>0
    l.close(2,'short-fixture',94.02,.0004,'TARGET',94.)
    assert l.realized_gross>0 and l.slippage_cost>0 and l.assert_reconciles()

def shorts(data):
    cfg=trial.CONFIG['engines']['CORE_SHORT']
    f4={s:trial.features(data.frames[(s,'4h')],'4h') for s in sorted(data.pit)}
    part=[pd.Series(np.where(x.ema200.notna(),(x.close>x.ema200).astype(float),np.nan),index=x.knowledge_ts,name=s) for s,x in f4.items()]
    breadth=pd.concat(part,axis=1).mean(axis=1)
    btc=f4['BTCUSDT'].set_index('knowledge_ts')
    falling=(btc.close<btc.ema200)&(btc.ema50<btc.ema200)&(btc.ret42<0)
    result=[]
    for symbol,x in f4.items():
        lo=x.low.shift().rolling(55,min_periods=55).min()
        context=falling.reindex(x.knowledge_ts).fillna(False).to_numpy()&(breadth.reindex(x.knowledge_ts).to_numpy()<=.45)
        mask=(x.close<lo)&(x.close.shift()>=lo.shift())&(x.ema50<x.ema200)&(x.adx>=cfg['adx'])&context
        for i in np.flatnonzero(mask.fillna(False).to_numpy()):
            row=x.iloc[i]
            if not np.isfinite(row.atr) or row.atr<=0:continue
            t=int(row.knowledge_ts)
            result.append({'id':f'CORE_SHORT:{symbol}:{t}','engine':'CORE_SHORT','symbol':symbol,'timestamp':t,'knowledge_ts':t,'source_open_ts':int(row.open_time),'atr':float(row.atr)})
    return sorted(result,key=lambda s:(s['timestamp'],s['symbol']))

fixtures()
data=trial.Dataset(args.data_root,gap_root=args.gap_root,funding_mark_root=args.funding_mark_root)
with gzip.open(args.audit_root/'signals.jsonl.gz','rt') as s:
    frozen=[json.loads(line) for line in s]
h1=[s for s in frozen if s['engine']!='REV15M']
assert len(frozen)==6650
output={'hypothesis':'H2_CORE_SHORT_on_H1','prereg_commit':'b57d53559b79e2e746ae4cd50c148ced82f20625',
        'source_alpha_commit':'f8c2307533265653f1faf0832fda836b21641f85',
        'dataset_manifest_sha256':trial.CONFIG['dataset_manifest_sha256'],'scenario':{}}

# Before adding any new engine, verify the side-aware simulator preserves H1 exactly.
for scenario in ('BASE','STRESS'):
    got=trial.replay(data,h1,scenario=scenario)
    prior=json.loads((args.h1_root/f'h1_{scenario.lower()}_ledger_manifest.json').read_text())
    assert got.ledger.manifest()['ledger_sha256']==prior['ledger_sha256'],'short extension changed frozen long replay'
    print('H1_REGRESSION_PASS',scenario,len(got.ledger.events),flush=True)
    del got

trial.CONFIG['engines']['CORE_SHORT']={**trial.CONFIG['engines']['CORE'],'name':'CORE_SHORT_H4_BREAK55_BEAR'}
added=shorts(data)
assert all(s['timestamp']==s['knowledge_ts']==s['source_open_ts']+4*3_600_000-1 for s in added)
combo=sorted(h1+added,key=lambda x:(x['timestamp'],trial.ENGINE_PRIORITY[x['engine']],x['symbol']))
print('SHORT_SIGNALS',len(added),'PORTFOLIO_SIGNALS',len(combo),flush=True)
output['short_signal_count']=len(added)
output['short_signal_sha256']=hashlib.sha256(json.dumps(added,sort_keys=True,separators=(',',':')).encode()).hexdigest()
(out/'short_signals.json').write_text(json.dumps(added,indent=2,sort_keys=True)+'\n')

for scenario in ('BASE','STRESS'):
    started=time.monotonic()
    r=trial.replay(data,combo,scenario=scenario)
    m=metrics(r)
    assert r.ledger.assert_reconciles()
    assert r.diagnostics['missing_active_bars']==0
    worst=max((e for e in r.ledger.events if e['event']=='OPEN'), key=lambda e:e['gross_to_equity'],default=None)
    print('MAX_ENTRY_GROSS',scenario,{k:worst.get(k) for k in ('seq','timestamp','engine','side','symbol','gross_to_equity','gross_notional','equity')} if worst else None,flush=True)
    assert worst is None or worst['gross_to_equity']<=1+1e-6
    assert m['max_open_stop_risk_fraction']<=.06+1e-8
    assert all(t.get('side')==(-1 if t['engine']=='CORE_SHORT' else 1) for t in r.trades)
    assert all((t['stop']>t['entry_fill']>t['target']) if t['side']==-1 else (t['stop']<t['entry_fill']<t['target']) for t in r.trades)
    assert abs(sum(t['net'] for t in r.trades)-10000*m['return'])<.001
    (out/f'h2_{scenario.lower()}_metrics.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    (out/f'h2_{scenario.lower()}_diagnostics.json').write_text(json.dumps(r.diagnostics,indent=2,sort_keys=True)+'\n')
    (out/f'h2_{scenario.lower()}_ledger_manifest.json').write_text(json.dumps(r.ledger.manifest(),indent=2,sort_keys=True)+'\n')
    pd.DataFrame(r.trades).to_csv(out/f'h2_{scenario.lower()}_trades.csv',index=False)
    h1m=json.loads((args.h1_root/f'h1_{scenario.lower()}_metrics.json').read_text())
    output['scenario'][scenario]={'h1_comparator':{k:h1m[k] for k in ('return','compound_monthly','max_drawdown_mtm','trades')},
                                   'h2_metrics':{k:m[k] for k in ('return','compound_monthly','max_drawdown_mtm','worst_month','trades','gross_pnl','commissions','slippage','funding_cashflow','max_open_stop_risk_fraction','time_weighted_capital_utilization')},
                                   'h2_engine_attribution':m['attribution']['engine'],'h2_annual':m['annual'],
                                   'funding_evidence':r.diagnostics['funding_settlement_evidence'],
                                   'h2_ledger_sha256':r.ledger.manifest()['ledger_sha256'],'elapsed_seconds':round(time.monotonic()-started,2)}
    print('H2_RESULT',scenario,'trades',m['trades'],'monthly',m['compound_monthly'],'dd',m['max_drawdown_mtm'],flush=True)
    if scenario=='BASE':
        cut=int(pd.Timestamp('2023-07-01T00:00:00Z').timestamp()*1000)-1
        full_prefix=[e for e in r.ledger.events if e['timestamp']<=cut]
    (out/'progress.json').write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')

for label, kwargs in [('prefix',{'cutoff':cut}),('future_perturbation',{'cutoff':cut,'perturb_after':cut})]:
    partial=trial.Dataset(args.data_root,gap_root=args.gap_root,funding_mark_root=args.funding_mark_root,**kwargs)
    assert shorts(partial)==[s for s in added if s['timestamp']<=cut], label+' future signal leaked'
    selected=[s for s in combo if s['timestamp']<=cut]
    checked=trial.replay(partial,selected,scenario='BASE',until=cut,liquidate_end=False)
    assert checked.ledger.events==full_prefix,label+' ledger differs from full-history prefix'
    print('CAUSAL_PREFIX_PASS',label,len(full_prefix),flush=True)
    del partial,checked
    gc.collect()
output['causal_prefix']={'cutoff_utc':'2023-06-30T23:59:59.999Z','events':len(full_prefix),'ordinary':True,'future_perturbation':True}
output['technical_status']='RESEARCH_DIAGNOSTIC_ONLY: funding settlement incomplete; no untouched OOS'
(out/'h2_result.json').write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
(out/'artifact_manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file() and p.name not in ('artifact_manifest.json','progress.json')},indent=2)+'\n')
print('H2_RESEARCH_COMPLETE',flush=True)
