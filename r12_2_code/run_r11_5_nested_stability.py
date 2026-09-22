from __future__ import annotations
import hashlib, json, math, sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'trade-r8'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from r11_multitimeframe_rank_engine import (
    config_for_timeframe, resample_universe, make_dataset, rank_model, R11_FEATURES, _slice
)
from run_r8_real import DEV_CANDIDATES, OUTER_HOLDOUT, download_universe, START, END
from run_r11_3_execution_fix import (
    build_signals, simulate_fixed, rolling_corr,
    FIXED_POSITION_FRACTION, MAX_CONCURRENT, MAX_PAIR_CORR, CORR_LOOKBACK_BARS,
    DAILY_LOSS_LIMIT, MAX_DRAWDOWN
)

TF='4h'
TOP_K=2
MIN_RANK_Z=1.0
KIND='STOP_ONLY'
STRICT_PURGE_HOURS=48
GATE_MIN_HISTORY=120
GATE_MIN_FOLDS=3
GATE_ALPHA=10.0
GATE_TARGET_MIN=-0.04
GATE_TARGET_MAX=0.08
GATE_MIN_PRED_NET=0.0
CONC_WINDOW_DAYS=90
CONC_MAX_SHARE=0.25
CONC_MIN_HISTORY=20

GATE_FEATURES=[
    'rank_z','pred_rank',
    'btc_ret_24h','btc_ema200_dist','btc_adx14',
    'market_breadth_ema200','market_breadth_ret24_pos',
    'market_risk_on','market_range','market_recovery',
    'ret_24h','ret_72h','rel_btc_24h','rel_btc_72h',
    'atr_pct','volatility_24h','rsi14','adx14','ema200_dist','move_to_cost'
]

def canonical_data(raw, symbols):
    return {s: raw[s].sort_index() for s in symbols if s in raw}

def canonical_frame(df):
    if df.empty: return df.copy()
    q=df.reset_index()
    ts=q.columns[0]
    q=q.rename(columns={ts:'__ts'})
    q=q.sort_values(['__ts','symbol'],kind='mergesort')
    return q.set_index('__ts')

def frame_hash(df, cols):
    if df.empty: return hashlib.sha256(b'EMPTY').hexdigest()
    q=df.reset_index()
    ts=q.columns[0]
    q=q.rename(columns={ts:'__ts'})
    use=['__ts']+[c for c in cols if c in q.columns]
    q=q[use].copy()
    if '__ts' in q:
        q['__ts']=pd.to_datetime(q['__ts'],utc=True).astype('int64')
    h=pd.util.hash_pandas_object(q,index=False).to_numpy(dtype='uint64').tobytes()
    return hashlib.sha256(h).hexdigest()

def make_oos_predictions_strict(ds,cfg,dev):
    devset=set(dev)
    start=ds.index.min().floor('D'); end=ds.index.max().ceil('D')
    cursor=start+pd.Timedelta(days=cfg.train_days+cfg.calibration_days)
    purge=max(cfg.expected_bar_delta*cfg.purge_bars,pd.Timedelta(hours=STRICT_PURGE_HOURS))
    rows=[]; folds=[]
    while cursor+pd.Timedelta(days=cfg.test_days)<=end:
        test0=cursor; test1=cursor+pd.Timedelta(days=cfg.test_days)
        cal0=test0-pd.Timedelta(days=cfg.calibration_days)
        train0=cal0-pd.Timedelta(days=cfg.train_days)
        verify0=test0-pd.Timedelta(days=cfg.calibration_verify_days)
        tr=canonical_frame(_slice(ds,train0,cal0-purge,devset))
        sel=canonical_frame(_slice(ds,cal0,verify0-purge,devset))
        ver=canonical_frame(_slice(ds,verify0,test0-purge,devset))
        te=canonical_frame(_slice(ds,test0,test1,devset))
        base={'test_start':str(test0),'test_end':str(test1),'train_rows':len(tr),
              'select_rows':len(sel),'verify_rows':len(ver),'test_rows':len(te),
              'purge_hours':STRICT_PURGE_HOURS}
        if len(tr)<cfg.min_training_rows or len(sel)<100 or len(ver)<40 or len(te)==0:
            folds.append({**base,'status':'SKIP'}); cursor=test1; continue
        m=rank_model(cfg)
        m.fit(tr[R11_FEATURES],tr.target_rank)
        z=te[['symbol','target_rank','stop_frac','tp_frac']].copy()
        z['pred_rank']=m.predict(te[R11_FEATURES])
        z['fold_test_start']=str(test0)
        parts=[]
        for ts,g in z.groupby(level=0,sort=True):
            q=g.reset_index()
            tcol=q.columns[0]
            q=q.rename(columns={tcol:'__ts'})
            q=q.sort_values(['pred_rank','symbol'],ascending=[False,True],kind='mergesort')
            med=float(q.pred_rank.median()); sd=float(q.pred_rank.std(ddof=0))
            den=sd if np.isfinite(sd) and sd>1e-9 else 1.0
            q['rank_z']=(q.pred_rank-med)/den
            q['pred_order']=np.arange(1,len(q)+1)
            q['selected']=(q.pred_order<=TOP_K)&(q.rank_z>=MIN_RANK_Z)
            parts.append(q.set_index('__ts'))
        rows.append(pd.concat(parts).sort_index())
        folds.append({**base,'status':'OOS'})
        cursor=test1
    return (pd.concat(rows).sort_index() if rows else pd.DataFrame()), pd.DataFrame(folds)

def enrich_signals(signals,pred,ds):
    p=pred[pred.selected][['symbol','rank_z','pred_rank']].copy().reset_index()
    p=p.rename(columns={p.columns[0]:'signal_time'})
    base_cols=['symbol']+[c for c in GATE_FEATURES if c not in ('rank_z','pred_rank')]
    b=ds[base_cols].copy().reset_index()
    b=b.rename(columns={b.columns[0]:'signal_time'})
    s=signals.merge(p,on=['signal_time','symbol'],how='left').merge(b,on=['signal_time','symbol'],how='left')
    s['signal_time']=pd.to_datetime(s.signal_time,utc=True)
    s['exit_time']=pd.to_datetime(s.exit_time,utc=True)
    return s.sort_values(['signal_time','symbol'],kind='mergesort').reset_index(drop=True)

def make_gate():
    return Pipeline([
        ('impute',SimpleImputer(strategy='median')),
        ('scale',StandardScaler()),
        ('ridge',Ridge(alpha=GATE_ALPHA))
    ])

def apply_online_gate(signals, fold_meta):
    s=signals.copy()
    s['gate_ready']=False
    s['gate_pred_net']=np.nan
    s['gate_selected']=False
    reports=[]
    fold_starts=sorted(pd.to_datetime(fold_meta.loc[fold_meta.status=='OOS','test_start'],utc=True).unique())
    for fs in fold_starts:
        cur=s[s.fold_test_start.astype(str)==str(fs)]
        hist=s[(s.signal_time<fs)&(s.exit_time<fs)]
        hist_folds=hist.fold_test_start.nunique()
        rep={'fold_test_start':str(fs),'history_n':int(len(hist)),'history_folds':int(hist_folds),'current_n':int(len(cur))}
        if len(hist)<GATE_MIN_HISTORY or hist_folds<GATE_MIN_FOLDS or cur.empty:
            rep['status']='GATE_NOT_READY'
            reports.append(rep); continue
        model=make_gate()
        y=hist.net_return.clip(GATE_TARGET_MIN,GATE_TARGET_MAX)
        model.fit(hist[GATE_FEATURES],y)
        pred=model.predict(cur[GATE_FEATURES])
        s.loc[cur.index,'gate_ready']=True
        s.loc[cur.index,'gate_pred_net']=pred
        sel=pred>GATE_MIN_PRED_NET
        s.loc[cur.index,'gate_selected']=sel
        rep.update({'status':'GATE_READY','selected':int(sel.sum()),'pred_mean':float(np.mean(pred)),
                    'pred_median':float(np.median(pred))})
        reports.append(rep)
    return s,pd.DataFrame(reports)

def simulate_concentration(signals,data,cfg,extra_cost=0.0):
    if signals.empty:return pd.DataFrame(),{'trades':0,'status':'NO_TRADES'}
    sig=signals.sort_values(['entry_time','meta_score'],ascending=[True,False],kind='mergesort').copy()
    equity=10000.0; peak=equity; active=[]; accepted=[]; daily={}; stopped=False
    rejects={'same_symbol':0,'max_concurrent':0,'correlation':0,'daily_loss':0,'drawdown_stop':0,'concentration':0}
    def realize(t):
        nonlocal equity,peak,active
        done=[p for p in active if p['exit_time']<=t]
        active=[p for p in active if p['exit_time']>t]
        for p in sorted(done,key=lambda z:z['exit_time']):
            equity+=p['pnl_cash']
            d=p['exit_time'].date()
            daily[d]=daily.get(d,0.0)+p['pnl_cash']
            peak=max(peak,equity)
    for _,row in sig.iterrows():
        et=pd.Timestamp(row.entry_time); realize(et)
        if peak<=0 or 1-equity/peak>=MAX_DRAWDOWN:
            rejects['drawdown_stop']+=1; stopped=True; continue
        loss=-min(0.0,daily.get(et.date(),0.0))/max(equity,1e-9)
        if loss>=DAILY_LOSS_LIMIT:
            rejects['daily_loss']+=1; continue
        if any(p['symbol']==row.symbol for p in active):
            rejects['same_symbol']+=1; continue
        if len(active)>=MAX_CONCURRENT:
            rejects['max_concurrent']+=1; continue
        corr_bad=False
        for p in active:
            c=rolling_corr(data,row.symbol,p['symbol'],pd.Timestamp(row.signal_time),CORR_LOOKBACK_BARS)
            if c is not None and c>=MAX_PAIR_CORR:
                corr_bad=True; break
        if corr_bad:
            rejects['correlation']+=1; continue
        cutoff=et-pd.Timedelta(days=CONC_WINDOW_DAYS)
        hist=[p for p in accepted if pd.Timestamp(p['entry_time'])<et and pd.Timestamp(p['entry_time'])>=cutoff]
        if len(hist)>=CONC_MIN_HISTORY:
            cnt=sum(1 for p in hist if p['symbol']==row.symbol)
            if (cnt+1)/(len(hist)+1)>CONC_MAX_SHARE:
                rejects['concentration']+=1; continue
        net=float(row.gross_return)-cfg.roundtrip_cost-extra_cost
        pnl=equity*FIXED_POSITION_FRACTION*net
        rec=row.to_dict()
        rec.update({'net_return':net,'position_fraction':FIXED_POSITION_FRACTION,'equity_at_entry':equity,'pnl_cash':pnl})
        accepted.append(rec); active.append(rec)
    if accepted:
        realize(max(pd.Timestamp(x['exit_time']) for x in accepted))
    tr=pd.DataFrame(accepted)
    if tr.empty:return tr,{'trades':0,'status':'NO_ACCEPTED_TRADES','rejects':rejects}
    q=tr.sort_values('exit_time').copy()
    q['equity_after']=10000+q.pnl_cash.cumsum()
    q['peak']=q.equity_after.cummax()
    q['dd']=1-q.equity_after/q.peak
    gains=float(tr.loc[tr.pnl_cash>0,'pnl_cash'].sum())
    losses=float(-tr.loc[tr.pnl_cash<0,'pnl_cash'].sum())
    pf=(math.inf if losses<=0 and gains>0 else gains/losses if losses>0 else None)
    vc=tr.symbol.value_counts()
    return tr,{'trades':int(len(tr)),'precision':float((tr.net_return>0).mean()),
      'avg_net_return':float(tr.net_return.mean()),'profit_factor_cash':pf,
      'portfolio_return':float((10000+tr.pnl_cash.sum())/10000-1),
      'ending_equity':float(10000+tr.pnl_cash.sum()),'max_drawdown':float(q.dd.max()),
      'symbols':vc.to_dict(),'max_symbol_share':float(vc.iloc[0]/len(tr)) if len(tr) else None,
      'rejects':rejects,'drawdown_stop_triggered':stopped}

def fold_stability(trades, fold_meta):
    folds=[str(x) for x in fold_meta.loc[fold_meta.status=='OOS','test_start'].tolist()]
    rows=[]
    for f in folds:
        g=trades[trades.fold_test_start.astype(str)==f] if not trades.empty else trades
        pnl=float(g.pnl_cash.sum()) if len(g) and 'pnl_cash' in g else 0.0
        avg=float(g.net_return.mean()) if len(g) else 0.0
        rows.append({'fold_test_start':f,'trades':int(len(g)),'pnl_cash':pnl,'avg_net':avg,'positive':bool(pnl>0)})
    d=pd.DataFrame(rows)
    return {'folds':int(len(d)),'positive_folds':int(d.positive.sum()),
            'positive_share':float(d.positive.mean()) if len(d) else 0.0,
            'median_fold_pnl':float(d.pnl_cash.median()) if len(d) else 0.0,
            'rows':rows}

def gate_checks(port,stress,stability):
    pf=port.get('profit_factor_cash'); spf=stress.get('profit_factor_cash')
    return {
      'trades_ok':port.get('trades',0)>=100,
      'return_positive':port.get('portfolio_return',-1)>0,
      'pf_ok':pf is not None and (math.isinf(pf) or pf>=1.15),
      'dd_ok':port.get('max_drawdown',1)<0.08,
      'precision_ok':port.get('precision',0)>=0.40,
      'symbol_coverage_ok':len(port.get('symbols',{}))>=10,
      'fold_stability_ok':stability.get('positive_share',0)>=0.55,
      'stress_positive':stress.get('portfolio_return',-1)>0,
      'stress_pf_ok':spf is not None and (math.isinf(spf) or spf>=1.05),
      'no_dd_stop':not port.get('drawdown_stop_triggered',True),
    }

def evaluate_arm(name,signals,data,cfg,fold_meta,use_concentration):
    if use_concentration:
        tr,port=simulate_concentration(signals,data,cfg,0.0)
        trs,stress=simulate_concentration(signals,data,cfg,2*cfg.slippage_side)
    else:
        tr,port=simulate_fixed(signals,data,cfg,0.0)
        trs,stress=simulate_fixed(signals,data,cfg,2*cfg.slippage_side)
    stability=fold_stability(tr,fold_meta)
    checks=gate_checks(port,stress,stability)
    if not tr.empty: tr.to_csv(f'r11_5_{name.lower()}_trades.csv',index=False)
    if not trs.empty: trs.to_csv(f'r11_5_{name.lower()}_trades_2x_slippage.csv',index=False)
    return {'signals':int(len(signals)),'portfolio':port,'double_slippage':stress,
            'fold_stability':stability,'checks':checks,'development_pass':all(checks.values())}

def main():
    cfg=config_for_timeframe(TF)
    raw,skipped=download_universe(DEV_CANDIDATES)
    dev=[s for s in DEV_CANDIDATES if s in raw]
    raw=canonical_data(raw,dev)
    data=canonical_data(resample_universe(raw,TF),dev)
    ds=canonical_frame(make_dataset(data,'BTCUSDT',cfg,development_symbols=dev))
    dataset_hash=frame_hash(ds,['symbol','target_rank']+R11_FEATURES)

    pred1,folds=make_oos_predictions_strict(ds,cfg,dev)
    pred2,_=make_oos_predictions_strict(ds,cfg,dev)
    pred_hash_1=frame_hash(pred1,['symbol','pred_rank','rank_z','pred_order','selected','fold_test_start'])
    pred_hash_2=frame_hash(pred2,['symbol','pred_rank','rank_z','pred_order','selected','fold_test_start'])
    reproducible=(pred_hash_1==pred_hash_2)
    if not reproducible:
        raise RuntimeError(f'Prediction reproducibility failed: {pred_hash_1} != {pred_hash_2}')

    base_signals=build_signals(pred1,data,cfg,KIND)
    enriched=enrich_signals(base_signals,pred1,ds)
    gated,gate_folds=apply_online_gate(enriched,folds)

    base=enriched.copy()
    gated_sig=gated[gated.gate_selected].copy()

    arms={
      'BASE':(base,False),
      'REGIME_GATE':(gated_sig,False),
      'CONCENTRATION':(base,True),
      'REGIME_PLUS_CONC':(gated_sig,True),
    }
    result={
      'version':'V10-R11.5-NESTED-STABILITY-GATE',
      'period':[str(START),str(END)],
      'timeframe':TF,'top_k':TOP_K,'min_rank_z':MIN_RANK_Z,'exit':KIND,
      'strict_purge_hours':STRICT_PURGE_HOURS,
      'gate':{'type':'causal expanding Ridge net-return gate','features':GATE_FEATURES,
              'min_history':GATE_MIN_HISTORY,'min_folds':GATE_MIN_FOLDS,'alpha':GATE_ALPHA,
              'target_clip':[GATE_TARGET_MIN,GATE_TARGET_MAX],'pred_net_threshold':GATE_MIN_PRED_NET},
      'concentration':{'window_days':CONC_WINDOW_DAYS,'max_symbol_share':CONC_MAX_SHARE,'min_history':CONC_MIN_HISTORY},
      'development_symbols':dev,'skipped':skipped,'dataset_rows':int(len(ds)),
      'dataset_hash':dataset_hash,'prediction_hash_1':pred_hash_1,'prediction_hash_2':pred_hash_2,
      'prediction_reproducible':reproducible,
      'base_selected_signals':int(pred1.selected.sum()),
      'base_stop_only_signals':int(len(base_signals)),
      'gate_selected_signals':int(len(gated_sig)),
      'outer_holdout_preregistered':OUTER_HOLDOUT,'outer_holdout_opened':False,
      'outer_holdout_reason':'R11.5 is a development ablation. Holdout remains sealed regardless of arm results.',
      'arms':{}
    }
    for name,(sig,conc) in arms.items():
        result['arms'][name]=evaluate_arm(name,sig,data,cfg,folds,conc)
    result['passing_arms']=[k for k,v in result['arms'].items() if v['development_pass']]

    folds.to_csv('r11_5_outer_folds.csv',index=False)
    gate_folds.to_csv('r11_5_gate_folds.csv',index=False)
    gated.to_csv('r11_5_enriched_signals.csv',index=False)
    Path('r11_5_result.json').write_text(json.dumps(result,indent=2,default=str))
    Path('r11_5_report.md').write_text('# V10 R11.5 Nested Stability Gate\n\n```json\n'+json.dumps(result,indent=2,default=str)+'\n```\n')
    print('===R11_5_RESULT_JSON===')
    print(json.dumps(result,separators=(',',':'),default=str))
    print('===END_R11_5_RESULT_JSON===')

if __name__=='__main__':
    main()
