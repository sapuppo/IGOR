"""V10 R9.2 — Normalized Cross-Sectional Ranking Engine.

Research-only. Binance Spot USDT, long-only, 1h bars, no leverage.
Scores the liquid development universe every 6h and ranks opportunities against
one another instead of classifying setup events independently.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "trade-r8"))
from typing import Sequence
import math
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from r8_setup_experts_engine import (
    Config as BaseConfig, build_features, _add_market_context,
    simulate_portfolio, stress_extra_roundtrip, _profit_factor,
)

R9_FEATURES = [
    "ret_1h","ret_4h","ret_12h","ret_24h","ret_72h",
    "rel_btc_24h","rel_btc_72h","atr_pct","volatility_24h",
    "ema20_dist","ema50_dist","ema200_dist","ema50_slope_24h",
    "rsi14","adx14","bb_width","vol_z_24h","range_overlap_72h","range_pos_72h",
    "breakout_48h","corr_btc_72h","btc_ret_24h","btc_ema200_dist","btc_adx14",
    "market_breadth_ema200","market_breadth_ret24_pos","market_risk_on","market_range","market_recovery",
    "cs_ret24_rank","cs_ret72_rank","cs_rel_btc24_rank","cs_ema200_rank","cs_vol_z_rank",
    "cs_atr_rank","cs_volatility_rank","cs_bb_width_rank","cs_rsi_rank",
    "setup_trend_pullback","setup_breakout","setup_range","roundtrip_cost","move_to_cost",
]

@dataclass(frozen=True)
class R92Config(BaseConfig):
    decision_hours: tuple[int,...] = (0,6,12,18)
    rank_horizon_bars: int = 18
    rank_rr: float = 1.80
    train_days: int = 360
    calibration_days: int = 60
    test_days: int = 30
    purge_bars: int = 24
    min_training_rows: int = 18_000
    min_group_assets: int = 10
    min_quote_volume_24h: float = 10_000_000.0
    min_move_to_cost: float = 3.0
    rank_min_leaf: int = 100

    @property
    def max_horizon_bars(self)->int:
        return self.rank_horizon_bars


def _add_extra_ranks(chunks:dict[str,pd.DataFrame], development_symbols:Sequence[str])->dict[str,pd.DataFrame]:
    dev=[s for s in development_symbols if s in chunks]
    mapping={"cs_atr_rank":"atr_pct","cs_volatility_rank":"volatility_24h","cs_bb_width_rank":"bb_width","cs_rsi_rank":"rsi14"}
    mats={src:pd.concat({s:chunks[s][src] for s in dev},axis=1) for src in mapping.values()}
    ranks={src:m.rank(axis=1,pct=True,method="average") for src,m in mats.items()}
    out={}
    for sym,f in chunks.items():
        g=f.copy()
        for dest,src in mapping.items():
            if sym in dev:
                g[dest]=ranks[src][sym].reindex(g.index)
            else:
                m=mats[src].reindex(g.index)
                g[dest]=m.le(g[src],axis=0).mean(axis=1,skipna=True)
        out[sym]=g
    return out


def _rank_outcomes(f:pd.DataFrame, mask:pd.Series, cfg:R92Config)->pd.DataFrame:
    n=len(f); idx=f.index
    cols=["gross_return","net_return","stop_frac","tp_frac","entry_time","exit_time","exit_reason"]
    out=pd.DataFrame(index=idx,columns=cols)
    o,h,l,c=[f[x].to_numpy() for x in ("open","high","low","close")]
    for i in np.flatnonzero(mask.to_numpy()):
        entry_i=i+1; last_i=entry_i+cfg.rank_horizon_bars-1
        if last_i>=n:continue
        entry=float(o[entry_i]); atr=float(f.iloc[i].atr_pct)
        if not np.isfinite(entry) or entry<=0 or not np.isfinite(atr):continue
        stop=float(np.clip(cfg.atr_stop_mult*atr,cfg.min_stop_frac,cfg.max_stop_frac))
        tp=max(cfg.rank_rr*stop,2.5*cfg.roundtrip_cost)
        sp=entry*(1-stop); tpp=entry*(1+tp)
        gross=None; reason="HORIZON"; exit_i=last_i
        for j in range(entry_i,last_i+1):
            op,hi,lo=float(o[j]),float(h[j]),float(l[j])
            if not all(np.isfinite([op,hi,lo])):continue
            if op<=sp:gross=op/entry-1;reason="GAP_STOP";exit_i=j;break
            if op>=tpp:gross=op/entry-1;reason="GAP_TP";exit_i=j;break
            hs=lo<=sp; ht=hi>=tpp
            if hs and ht:gross=-stop;reason="STOP_FIRST_COLLISION";exit_i=j;break
            if hs:gross=-stop;reason="STOP";exit_i=j;break
            if ht:gross=tp;reason="TAKE_PROFIT";exit_i=j;break
        if gross is None:gross=float(c[last_i]/entry-1)
        out.loc[idx[i]]=[gross,gross-cfg.roundtrip_cost,stop,tp,idx[entry_i],idx[exit_i],reason]
    for col in ["gross_return","net_return","stop_frac","tp_frac"]:out[col]=pd.to_numeric(out[col],errors="coerce")
    return out


def make_rank_dataset(data:dict[str,pd.DataFrame],btc_symbol:str,cfg:R92Config,*,development_symbols:Sequence[str])->pd.DataFrame:
    if btc_symbol not in data:raise KeyError(btc_symbol)
    btc=data[btc_symbol]
    feats={s:build_features(s,d,btc,cfg) for s,d in data.items()}
    feats=_add_market_context(feats,development_symbols)
    feats=_add_extra_ranks(feats,development_symbols)
    chunks=[]
    for sym,f in feats.items():
        anchor=pd.Series(f.index.hour.isin(cfg.decision_hours),index=f.index)
        mask=anchor & (f.quote_volume_24h>=cfg.min_quote_volume_24h) & (f.move_to_cost>=cfg.min_move_to_cost) & (f.btc_risk_off==0)
        oc=_rank_outcomes(f,mask.fillna(False),cfg)
        g=f.join(oc);g["candidate"]=mask
        g["setup_type"]="RANK"
        chunks.append(g[g.candidate])
    x=pd.concat(chunks).sort_index()
    x=x.dropna(subset=R9_FEATURES+["net_return","gross_return","entry_time","exit_time","stop_frac"])
    devset=set(development_symbols)
    devmask=x.symbol.isin(devset)
    dev_counts=x[devmask].groupby(level=0).size()
    x=x[x.index.to_series().map(dev_counts).fillna(0).to_numpy()>=cfg.min_group_assets].copy()
    devmask=x.symbol.isin(devset)
    x["target_rank"]=np.nan
    x.loc[devmask,"target_rank"]=x[devmask].groupby(level=0).net_return.rank(pct=True,method="average")
    # Outer-holdout labels are percentiles against development outcomes only;
    # they never alter development targets. This matters only after the sealed holdout is opened.
    if (~devmask).any():
        devvals={ts:g.net_return.to_numpy() for ts,g in x[devmask].groupby(level=0)}
        vals=[]
        for ts,r in x[~devmask].iterrows():
            ref=devvals.get(ts)
            vals.append(float(np.mean(ref<=r.net_return)) if ref is not None and len(ref) else np.nan)
        x.loc[~devmask,"target_rank"]=vals
    return x.dropna(subset=["target_rank"])


def rank_model(cfg:R92Config)->HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="squared_error",learning_rate=0.04,max_iter=260,max_leaf_nodes=15,
        min_samples_leaf=cfg.rank_min_leaf,l2_regularization=5.0,random_state=cfg.random_state,
    )


def _slice(ds,start,end,symbols:set[str]):
    return ds[(ds.index>=start)&(ds.index<end)&(ds.symbol.isin(symbols))]


def apply_rank_rule(frame:pd.DataFrame,*,top_k:int,min_z:float)->pd.DataFrame:
    """Select the strongest relative opportunities at each decision timestamp.

    R9.2 removes the absolute predicted-rank threshold because R9.1 showed that
    the model's score scale shifts across folds even while rank IC stays positive.
    Selection is therefore based on within-group z-score only.
    """
    if frame.empty:return frame.assign(selected=False,score_z=np.nan,score_spread=np.nan)
    parts=[]
    for ts,g in frame.groupby(level=0,sort=True):
        q=g.copy().sort_values("pred_rank",ascending=False)
        med=float(q.pred_rank.median())
        sd=float(q.pred_rank.std(ddof=0))
        denom=sd if np.isfinite(sd) and sd>1e-9 else 1.0
        q["score_spread"]=q.pred_rank-med
        q["score_z"]=(q.pred_rank-med)/denom
        take=np.zeros(len(q),dtype=bool);take[:min(top_k,len(q))]=True
        q["selected"]=take & (q.score_z.to_numpy()>=min_z)
        parts.append(q)
    return pd.concat(parts).sort_index()


def signal_stats(frame:pd.DataFrame)->dict:
    z=frame[frame.selected]
    if z.empty:return {"n":0,"symbols":0,"precision":None,"avg":None,"pf":None,"max_share":None,"positive_months":0,"months":0}
    counts=z.symbol.value_counts();pf=_profit_factor(z.net_return)
    monthly=z.groupby(z.index.to_period("M")).net_return.mean()
    return {"n":len(z),"symbols":counts.size,"precision":float((z.net_return>0).mean()),"avg":float(z.net_return.mean()),"pf":pf,"max_share":float(counts.iloc[0]/len(z)),"positive_months":int((monthly>0).sum()),"months":int(len(monthly))}


def passes(st:dict,stage:str)->bool:
    # Economic gates remain conservative. R9.2 changes score normalization, not
    # the requirement that a selected basket has positive expectancy after costs.
    if stage=="select":
        return st["n"]>=30 and st["symbols"]>=8 and st["avg"] is not None and st["avg"]>=0.0005 and st["pf"] is not None and st["pf"]>=1.08 and st["precision"]>=0.44 and st["max_share"]<=0.20 and st["positive_months"]>=1
    return st["n"]>=12 and st["symbols"]>=5 and st["avg"] is not None and st["avg"]>0 and st["pf"] is not None and st["pf"]>=1.05 and st["precision"]>=0.42 and st["max_share"]<=0.30


def choose_rule(sel:pd.DataFrame,ver:pd.DataFrame)->tuple[dict|None,dict]:
    grid=[]
    for top_k in (1,2):
        for min_z in (0.50,0.75,1.00,1.25,1.50,1.75,2.00):
            ss=signal_stats(apply_rank_rule(sel,top_k=top_k,min_z=min_z))
            rec={"top_k":top_k,"min_z":min_z,"select":ss}
            if passes(ss,"select"):
                pf=ss["pf"] if ss["pf"] is not None and np.isfinite(ss["pf"]) else 10.0
                rec["score"]=ss["avg"]*100*math.sqrt(ss["n"])+math.log(max(pf,1e-6))+0.03*ss["symbols"]-ss["max_share"]
            else:rec["score"]=-1e9
            grid.append(rec)
    viable=sorted([r for r in grid if r["score"]>-1e8],key=lambda r:r["score"],reverse=True)
    verification=[]
    for r in viable:
        vs=signal_stats(apply_rank_rule(ver,top_k=r["top_k"],min_z=r["min_z"]))
        rr={**r,"verify":vs}
        verification.append(rr)
        if passes(vs,"verify"):return rr,{"grid":grid,"verification":verification}
    return None,{"grid":grid,"verification":verification}

def walk_forward_rank(ds:pd.DataFrame,cfg:R92Config,*,development_symbols:Sequence[str],test_symbols:Sequence[str]|None=None):
    all_syms=set(ds.symbol.unique());dev=set(development_symbols);tst=set(test_symbols) if test_symbols is not None else dev
    if test_symbols is not None and dev&tst:raise ValueError("dev/test overlap")
    start=ds.index.min().floor("D");end=ds.index.max().ceil("D")
    cursor=start+pd.Timedelta(days=cfg.train_days+cfg.calibration_days);purge=cfg.expected_bar_delta*cfg.purge_bars
    preds=[];folds=[]
    while cursor+pd.Timedelta(days=cfg.test_days)<=end:
        test0=cursor;test1=cursor+pd.Timedelta(days=cfg.test_days);cal0=test0-pd.Timedelta(days=cfg.calibration_days);train0=cal0-pd.Timedelta(days=cfg.train_days);verify0=test0-pd.Timedelta(days=20)
        tr=_slice(ds,train0,cal0-purge,dev);sel=_slice(ds,cal0,verify0-purge,dev);ver=_slice(ds,verify0,test0-purge,dev);te=_slice(ds,test0,test1,tst)
        base={"test_start":str(test0),"train_rows":len(tr),"select_rows":len(sel),"verify_rows":len(ver),"test_rows":len(te)}
        if len(tr)<cfg.min_training_rows or len(sel)<100 or len(ver)<40 or len(te)==0:
            folds.append({**base,"status":"NO_TRADE_INSUFFICIENT_DATA"});cursor=test1;continue
        m=rank_model(cfg);m.fit(tr[R9_FEATURES],tr.target_rank)
        def score(q):
            z=q[["symbol","gross_return","net_return","stop_frac","tp_frac","entry_time","exit_time","exit_reason","setup_type"]].copy();z["pred_rank"]=m.predict(q[R9_FEATURES]);return z
        s=score(sel);v=score(ver);t=score(te)
        rule,diag=choose_rule(s,v)
        if rule is None:
            folds.append({**base,"status":"NO_TRADE_NESTED_ZRANK_CALIBRATION"});cursor=test1;continue
        picked=apply_rank_rule(t,top_k=rule["top_k"],min_z=rule["min_z"])
        picked["meta_score"]=picked.score_z;picked["threshold"]=rule["min_z"];picked["fold_test_start"]=test0
        preds.append(picked)
        st=signal_stats(picked)
        folds.append({**base,"status":"TRADE_GATE_OPEN" if st["n"] else "NO_TRADE_TEST","selected":st["n"],"precision":st["precision"],"avg_net_return":st["avg"],"profit_factor":st["pf"],"symbols":st["symbols"],"top_k":rule["top_k"],"min_z":rule["min_z"],"select_stats":str(rule["select"]),"verify_stats":str(rule.get("verify"))})
        cursor=test1
    return (pd.concat(preds).sort_index() if preds else pd.DataFrame(),pd.DataFrame(folds))
