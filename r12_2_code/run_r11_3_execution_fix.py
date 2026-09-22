from __future__ import annotations
import json, math, sys
from pathlib import Path
from dataclasses import asdict
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'trade-r8'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from r11_multitimeframe_rank_engine import (
    config_for_timeframe,resample_universe,make_dataset,rank_model,R11_FEATURES,_slice
)
from r8_setup_experts_engine import add_indicators, _profit_factor
from run_r8_real import DEV_CANDIDATES, OUTER_HOLDOUT, download_universe, START, END

TF='4h'
TOP_K=2
MIN_RANK_Z=1.0
EXITS=('HOLD_36H','EMA20_EXIT','STOP_ONLY')
FIXED_POSITION_FRACTION=0.10
MAX_CONCURRENT=3
MAX_PAIR_CORR=0.80
CORR_LOOKBACK_BARS=18
DAILY_LOSS_LIMIT=0.02
MAX_DRAWDOWN=0.08


def bars_for_hours(cfg,hours):
    bh=cfg.expected_bar_delta/pd.Timedelta(hours=1)
    return max(1,int(round(hours/float(bh))))


def make_oos_predictions(ds,cfg,dev,test_symbols=None):
    devset=set(dev); tst=set(test_symbols) if test_symbols is not None else devset
    start=ds.index.min().floor('D'); end=ds.index.max().ceil('D')
    cursor=start+pd.Timedelta(days=cfg.train_days+cfg.calibration_days)
    purge=cfg.expected_bar_delta*cfg.purge_bars
    rows=[]; folds=[]
    while cursor+pd.Timedelta(days=cfg.test_days)<=end:
        test0=cursor; test1=cursor+pd.Timedelta(days=cfg.test_days)
        cal0=test0-pd.Timedelta(days=cfg.calibration_days); train0=cal0-pd.Timedelta(days=cfg.train_days)
        verify0=test0-pd.Timedelta(days=cfg.calibration_verify_days)
        tr=_slice(ds,train0,cal0-purge,devset)
        sel=_slice(ds,cal0,verify0-purge,devset); ver=_slice(ds,verify0,test0-purge,devset)
        te=_slice(ds,test0,test1,tst)
        base={'test_start':str(test0),'test_end':str(test1),'train_rows':len(tr),'select_rows':len(sel),'verify_rows':len(ver),'test_rows':len(te)}
        if len(tr)<cfg.min_training_rows or len(sel)<100 or len(ver)<40 or len(te)==0:
            folds.append({**base,'status':'SKIP'}); cursor=test1; continue
        m=rank_model(cfg); m.fit(tr[R11_FEATURES],tr.target_rank)
        z=te[['symbol','target_rank','stop_frac','tp_frac']].copy(); z['pred_rank']=m.predict(te[R11_FEATURES]); z['fold_test_start']=str(test0)
        parts=[]
        for ts,g in z.groupby(level=0,sort=True):
            q=g.copy().sort_values('pred_rank',ascending=False)
            med=float(q.pred_rank.median()); sd=float(q.pred_rank.std(ddof=0)); den=sd if np.isfinite(sd) and sd>1e-9 else 1.0
            q['rank_z']=(q.pred_rank-med)/den; q['pred_order']=np.arange(1,len(q)+1)
            q['selected']=(q.pred_order<=TOP_K)&(q.rank_z>=MIN_RANK_Z)
            parts.append(q)
        rows.append(pd.concat(parts).sort_index()); folds.append({**base,'status':'OOS'})
        cursor=test1
    return (pd.concat(rows).sort_index() if rows else pd.DataFrame()), pd.DataFrame(folds)


def locate_entry(d,ts):
    loc=d.index.get_indexer([ts])[0]
    if loc<0 or loc+1>=len(d): return None
    return loc+1


def calc_exit(d,ts,cfg,kind):
    entry_i=locate_entry(d,ts)
    if entry_i is None:return None
    entry=float(d.open.iloc[entry_i])
    if not np.isfinite(entry) or entry<=0:return None
    if kind=='HOLD_36H':
        n=bars_for_hours(cfg,36); last=entry_i+n-1
        if last>=len(d):return None
        gross=float(d.close.iloc[last]/entry-1); return gross,d.index[last],'HOLD_36H'
    maxn=bars_for_hours(cfg,48); last=entry_i+maxn-1
    if last>=len(d):return None
    if kind=='EMA20_EXIT':
        for j in range(entry_i,last+1):
            cl=float(d.close.iloc[j])
            if j>entry_i and pd.notna(d.ema20.iloc[j]) and cl<float(d.ema20.iloc[j]):
                return cl/entry-1,d.index[j],'EMA20_EXIT'
        return float(d.close.iloc[last]/entry-1),d.index[last],'HORIZON_48H'
    if kind=='STOP_ONLY':
        atr_pct=float((d.atr14/d.close).iloc[entry_i-1])
        if not np.isfinite(atr_pct):return None
        stop=float(np.clip(cfg.atr_stop_mult*atr_pct,cfg.min_stop_frac,cfg.max_stop_frac)); sp=entry*(1-stop)
        for j in range(entry_i,last+1):
            op=float(d.open.iloc[j]); lo=float(d.low.iloc[j])
            if op<=sp:return op/entry-1,d.index[j],'GAP_STOP'
            if lo<=sp:return -stop,d.index[j],'STOP'
        return float(d.close.iloc[last]/entry-1),d.index[last],'HORIZON_48H'
    raise ValueError(kind)


def build_signals(pred,data,cfg,kind):
    inds={s:add_indicators(d) for s,d in data.items()}
    rows=[]
    for ts,row in pred[pred.selected].iterrows():
        e=calc_exit(inds[row.symbol],ts,cfg,kind)
        if not e:continue
        gross,exit_time,reason=e
        rows.append({'signal_time':ts,'entry_time':ts,'exit_time':exit_time,'symbol':row.symbol,'setup_type':kind,
                     'meta_score':float(row.rank_z),'threshold':MIN_RANK_Z,'selected':True,
                     'gross_return':float(gross),'net_return':float(gross-cfg.roundtrip_cost),'exit_reason':reason,
                     'fold_test_start':row.fold_test_start})
    return pd.DataFrame(rows)


def rolling_corr(data,s1,s2,t,lookback):
    if s1 not in data or s2 not in data:return None
    a=data[s1].close.loc[:t].tail(lookback+1).pct_change().dropna(); b=data[s2].close.loc[:t].tail(lookback+1).pct_change().dropna()
    q=pd.concat([a,b],axis=1,join='inner').dropna()
    if len(q)<max(8,lookback//2):return None
    x=float(q.iloc[:,0].corr(q.iloc[:,1])); return x if np.isfinite(x) else None


def simulate_fixed(signals,data,cfg,extra_cost=0.0):
    if signals.empty:return pd.DataFrame(),{'trades':0,'status':'NO_TRADES'}
    sig=signals.sort_values(['entry_time','meta_score'],ascending=[True,False]).copy()
    equity=10000.0; peak=equity; active=[]; accepted=[]; daily={}; stopped=False
    rejects={'same_symbol':0,'max_concurrent':0,'correlation':0,'daily_loss':0,'drawdown_stop':0}
    def realize(t):
        nonlocal equity,peak,active
        done=[p for p in active if p['exit_time']<=t]; active=[p for p in active if p['exit_time']>t]
        for p in sorted(done,key=lambda z:z['exit_time']):
            equity+=p['pnl_cash']; d=p['exit_time'].date(); daily[d]=daily.get(d,0.0)+p['pnl_cash']; peak=max(peak,equity)
    for _,row in sig.iterrows():
        et=pd.Timestamp(row.entry_time); xt=pd.Timestamp(row.exit_time); realize(et)
        if peak<=0 or 1-equity/peak>=MAX_DRAWDOWN: rejects['drawdown_stop']+=1; stopped=True; continue
        loss=-min(0.0,daily.get(et.date(),0.0))/max(equity,1e-9)
        if loss>=DAILY_LOSS_LIMIT: rejects['daily_loss']+=1; continue
        if any(p['symbol']==row.symbol for p in active): rejects['same_symbol']+=1; continue
        if len(active)>=MAX_CONCURRENT: rejects['max_concurrent']+=1; continue
        corr_bad=False
        for p in active:
            c=rolling_corr(data,row.symbol,p['symbol'],pd.Timestamp(row.signal_time),CORR_LOOKBACK_BARS)
            if c is not None and c>=MAX_PAIR_CORR: corr_bad=True; break
        if corr_bad: rejects['correlation']+=1; continue
        net=float(row.gross_return)-cfg.roundtrip_cost-extra_cost; pnl=equity*FIXED_POSITION_FRACTION*net
        rec=row.to_dict(); rec.update({'net_return':net,'position_fraction':FIXED_POSITION_FRACTION,'equity_at_entry':equity,'pnl_cash':pnl})
        accepted.append(rec); active.append(rec)
    if accepted:
        realize(max(pd.Timestamp(x['exit_time']) for x in accepted))
    tr=pd.DataFrame(accepted)
    if tr.empty:return tr,{'trades':0,'status':'NO_ACCEPTED_TRADES','rejects':rejects}
    q=tr.sort_values('exit_time').copy(); q['equity_after']=10000+q.pnl_cash.cumsum(); q['peak']=q.equity_after.cummax(); q['dd']=1-q.equity_after/q.peak
    gains=float(tr.loc[tr.pnl_cash>0,'pnl_cash'].sum()); losses=float(-tr.loc[tr.pnl_cash<0,'pnl_cash'].sum()); pf=(math.inf if losses<=0 and gains>0 else gains/losses if losses>0 else None)
    return tr,{'trades':int(len(tr)),'precision':float((tr.net_return>0).mean()),'avg_net_return':float(tr.net_return.mean()),'profit_factor_cash':pf,
               'portfolio_return':float((10000+tr.pnl_cash.sum())/10000-1),'ending_equity':float(10000+tr.pnl_cash.sum()),'max_drawdown':float(q.dd.max()),
               'symbols':tr.symbol.value_counts().to_dict(),'rejects':rejects,'drawdown_stop_triggered':stopped}


def fold_stability(signals):
    if signals.empty:return {'folds':0,'positive_folds':0,'positive_share':0.0}
    g=signals.groupby('fold_test_start').net_return.agg(['mean','count'])
    return {'folds':int(len(g)),'positive_folds':int((g['mean']>0).sum()),'positive_share':float((g['mean']>0).mean()),'median_fold_avg':float(g['mean'].median())}


def dev_gate(port,stress,stability):
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


def evaluate(pred,data,cfg,kind,prefix):
    sig=build_signals(pred,data,cfg,kind)
    tr,port=simulate_fixed(sig,data,cfg,0.0)
    extra=2*cfg.slippage_side # slippage 2x adds one extra normal RT slippage component
    trs,stress=simulate_fixed(sig,data,cfg,extra)
    stability=fold_stability(sig); checks=dev_gate(port,stress,stability); passed=all(checks.values())
    sig.to_csv(f'{prefix}_{kind.lower()}_signals.csv',index=False)
    if not tr.empty:tr.to_csv(f'{prefix}_{kind.lower()}_trades.csv',index=False)
    if not trs.empty:trs.to_csv(f'{prefix}_{kind.lower()}_trades_2x_slippage.csv',index=False)
    return {'signals':int(len(sig)),'portfolio':port,'double_slippage':stress,'fold_stability':stability,'checks':checks,'development_pass':passed}


def main():
    cfg=config_for_timeframe(TF)
    raw,skipped=download_universe(DEV_CANDIDATES); dev=[s for s in DEV_CANDIDATES if s in raw]
    data=resample_universe(raw,TF); ds=make_dataset(data,'BTCUSDT',cfg,development_symbols=dev)
    pred,folds=make_oos_predictions(ds,cfg,dev); folds.to_csv('r11_3_dev_folds.csv',index=False)
    result={'version':'V10-R11.3-EXECUTION-FIX','period':[str(START),str(END)],'timeframe':TF,'top_k':TOP_K,'min_rank_z':MIN_RANK_Z,
            'position_fraction':FIXED_POSITION_FRACTION,'development_symbols':dev,'skipped':skipped,'dataset_rows':len(ds),'outer_holdout_preregistered':OUTER_HOLDOUT,
            'outer_holdout_opened':False,'variants':{}}
    for kind in EXITS:
        result['variants'][kind]=evaluate(pred,data,cfg,kind,'r11_3_dev')
    passed=[k for k,v in result['variants'].items() if v['development_pass']]; result['passed_development_variants']=passed
    if passed:
        hd,hskip=download_universe(OUTER_HOLDOUT,workers=3); result['outer_holdout_skipped']=hskip
        if len(hd)==len(OUTER_HOLDOUT):
            allraw={**raw,**hd}; alldata=resample_universe(allraw,TF); dsh=make_dataset(alldata,'BTCUSDT',cfg,development_symbols=dev)
            ph,fh=make_oos_predictions(dsh,cfg,dev,test_symbols=OUTER_HOLDOUT); fh.to_csv('r11_3_holdout_folds.csv',index=False)
            result['outer_holdout_opened']=True; result['outer_holdout_variants']={}
            for kind in passed:
                sig=build_signals(ph,alldata,cfg,kind); tr,port=simulate_fixed(sig,alldata,cfg,0.0); extra=2*cfg.slippage_side; _,stress=simulate_fixed(sig,alldata,cfg,extra)
                result['outer_holdout_variants'][kind]={'signals':len(sig),'portfolio':port,'double_slippage':stress}
                if not sig.empty:sig.to_csv(f'r11_3_holdout_{kind.lower()}_signals.csv',index=False)
                if not tr.empty:tr.to_csv(f'r11_3_holdout_{kind.lower()}_trades.csv',index=False)
        else:result['outer_holdout_reason']='Holdout data unavailable.'
    else:
        result['outer_holdout_reason']='Preserved unopened because no R11.3 execution variant passed frozen development gates.'
    Path('r11_3_result.json').write_text(json.dumps(result,indent=2,default=str))
    Path('r11_3_report.md').write_text('# V10 R11.3 Execution Fix\n\n```json\n'+json.dumps(result,indent=2,default=str)+'\n```\n')
    print('===R11_3_RESULT_JSON==='); print(json.dumps(result,separators=(',',':'),default=str)); print('===END_R11_3_RESULT_JSON===')

if __name__=='__main__':main()
