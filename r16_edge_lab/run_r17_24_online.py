"""Frozen finite online-source strategy comparison; retrospective only."""
from pathlib import Path
import hashlib,json,warnings
import numpy as np,pandas as pd
import r17_21_audited_engine as e
from run_r17_05_regime_rotation import load_verified
from run_r17_19_trailing import prepare
from run_r17_20_new_hypotheses import compute,section
from r17_24_online_strategies import signals
R=Path(__file__).resolve().parent;O=R/'r17_24_results'
def ms(s): return int(pd.Timestamp(s).timestamp()*1000)
def main():
    warnings.filterwarnings('ignore',message='Converting to Period')
    O.mkdir(exist_ok=True)
    p=json.loads((R/'r17_24_protocol.json').read_text())
    data,funding=load_verified(R/'usdm_history');prepare(data)
    e.START=ms(p['start']);e.END=ms(p['end_exclusive'])
    btc=data['BTCUSDT'].close
    bs=pd.Series(np.where(btc>btc.rolling(180).mean(),1,-1),index=btc.index)
    results={};prefix=[];counts={}
    for mode in p['modes']:
        sig=compute(data) if mode=='control_volume' else signals(data,mode,e.START,e.END)
        if mode!='control_volume':
            for cut in [ms('2025-01-01T00:00Z'),ms('2026-01-01T00:00Z')]:
                pre=signals({s:f.loc[f.index<cut].copy() for s,f in data.items()},mode,e.START,e.END)
                for k in sig:
                    assert {t:v for t,v in sig[k].items() if t<=cut}=={t:v for t,v in pre[k].items() if t<=cut}
                prefix.append(mode+'_'+str(cut))
        counts[mode]=sum(len(v) for ev in sig.values() for v in ev.values())
        for gate in ([True] if mode=='control_volume' else p['btc_gates']):
            for factor in p['costs']:
                e.STOP=.05;e.TARGET=p['target'];e.FEE=.0006*factor;e.SLIP=.0004*factor
                spec=dict(id=mode+'_gate'+str(int(gate)),direction='long' if mode=='ft_ema_ha' else 'both',lookback_bars=6 if mode=='control_volume' else 1,btc_gate=gate,hold_bars=p['hold_bars'],**p['risk'])
                r=e.replay(spec,data,funding,sig,bs)
                daily=r.pop('daily_details');trades=r.pop('trade_details');key=spec['id']+'_cost'+str(factor)
                assert np.isclose(sum(x['net'] for x in trades),r['return']*e.CAPITAL)
                for tr in trades:
                    assert np.isclose(tr['net'],tr['side']*tr['qty']*(tr['exit_fill']-tr['entry_fill'])-tr['entry_fee']-tr['exit_fee']+tr['funding'])
                r['segments']={name:section(daily,ms(a),ms(b)) for name,a,b in [('2023_24','2023-01-01T00:00Z','2025-01-01T00:00Z'),('2025','2025-01-01T00:00Z','2026-01-01T00:00Z'),('h1_2026','2026-01-01T00:00Z','2026-07-01T00:00Z')]}
                r['months_ge_15']=sum(v>=.15 for v in r['monthly'].values());results[key]=r
                pd.DataFrame(daily).to_csv(O/(key+'_daily.csv'),index=False)
                pd.DataFrame(trades).to_csv(O/(key+'_trades.csv'),index=False)
                print(key,json.dumps({k:r[k] for k in ['compound_monthly','max_4h_mtm_drawdown','trades','annual']}),flush=True)
    candidates=[(k,r) for k,r in results.items() if not k.startswith('control') and k.endswith('cost1')]
    passed=[k for k,r in candidates if all(v['compound_monthly']>=.15 and v['max_4h_mtm_drawdown']<=.25 and v['trades']>=100 and all(z['return']>0 for z in v['segments'].values()) for v in (r,results[k[:-1]+'2']))]
    report=dict(version='R17.24',protocol_sha256=hashlib.sha256((R/'r17_24_protocol.json').read_bytes()).hexdigest(),data_files_verified=152,symbols=list(data),prefix_checks=prefix,reconciliations=len(results),signal_counts=counts,results=results,passes_goal=passed,live_promotion=False,label='RETROSPECTIVE_PREVIOUSLY_CONSULTED_DATA')
    (O/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('COMPLETE',passed,flush=True)
if __name__=='__main__':main()
