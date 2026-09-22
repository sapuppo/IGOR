"""V10 R11 — Multi-Timeframe Cross-Sectional Ranking.

Research-only. Binance Spot USDT, long-only, no leverage.
Two preregistered variants are evaluated independently: 2h and 4h.
The market filter is deterministic (not a learned timing model) and all
cross-sectional context is built only from development symbols.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import math, sys
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "trade-r8"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from r8_setup_experts_engine import (
    Config as BaseConfig, add_indicators, _range_overlap, _add_market_context,
    simulate_portfolio, stress_extra_roundtrip, _profit_factor,
)
from r9_2_cross_sectional_rank_engine import _add_extra_ranks

R11_FEATURES = [
    "ret_1b","ret_2b","ret_4h","ret_12h","ret_24h","ret_72h",
    "rel_btc_24h","rel_btc_72h","atr_pct","volatility_24h",
    "ema20_dist","ema50_dist","ema200_dist","ema50_slope_24h",
    "rsi14","adx14","bb_width","vol_z_24h","range_overlap_72h","range_pos_72h",
    "breakout_48h","corr_btc_72h","btc_ret_24h","btc_ema200_dist","btc_adx14",
    "market_breadth_ema200","market_breadth_ret24_pos","market_risk_on","market_range","market_recovery",
    "cs_ret24_rank","cs_ret72_rank","cs_rel_btc24_rank","cs_ema200_rank","cs_vol_z_rank",
    "cs_atr_rank","cs_volatility_rank","cs_bb_width_rank","cs_rsi_rank",
    "asset_trend","asset_recovery","roundtrip_cost","move_to_cost",
]


@dataclass(frozen=True)
class R11Config(BaseConfig):
    bar_interval: str = "2h"
    decision_hours: tuple[int,...] = (0,6,12,18)
    rank_horizon_bars: int = 18
    rank_rr: float = 2.0
    train_days: int = 360
    calibration_days: int = 60
    calibration_verify_days: int = 20
    test_days: int = 30
    purge_bars: int = 12
    min_training_rows: int = 12_000
    min_group_assets: int = 10
    min_quote_volume_24h: float = 10_000_000.0
    min_move_to_cost: float = 3.0
    rank_min_leaf: int = 80
    atr_stop_mult: float = 1.25
    min_stop_frac: float = 0.009
    max_stop_frac: float = 0.030
    corr_lookback_bars: int = 36

    @property
    def max_horizon_bars(self)->int:
        return self.rank_horizon_bars


def config_for_timeframe(tf:str)->R11Config:
    if tf == "2h":
        return R11Config(
            bar_interval="2h", decision_hours=(0,6,12,18), rank_horizon_bars=18,
            purge_bars=12, min_training_rows=12_000, rank_min_leaf=80,
            corr_lookback_bars=36,
        )
    if tf == "4h":
        return R11Config(
            bar_interval="4h", decision_hours=(0,8,16), rank_horizon_bars=12,
            purge_bars=6, min_training_rows=8_000, rank_min_leaf=60,
            corr_lookback_bars=18,
        )
    raise ValueError(tf)


def _bars_for_hours(cfg:R11Config,hours:int)->int:
    bh=cfg.expected_bar_delta/pd.Timedelta(hours=1)
    return max(1,int(round(hours/float(bh))))


def resample_ohlcv(df:pd.DataFrame, tf:str)->pd.DataFrame:
    """Aggregate 1h bars to close-boundary indexed 2h/4h bars.

    A bar labelled 02:00 contains [00:00,02:00) and is fully known at 02:00.
    The next bar opens at that same boundary, which is used as execution time.
    """
    d=df.copy().sort_index()
    agg={"open":"first","high":"max","low":"min","close":"last"}
    if "volume" in d: agg["volume"]="sum"
    if "quote_volume" in d: agg["quote_volume"]="sum"
    q=d.resample(tf,origin="epoch",closed="left",label="right").agg(agg)
    need=["open","high","low","close"]
    q=q.dropna(subset=need)
    if "volume" not in q: q["volume"]=0.0
    if "quote_volume" not in q: q["quote_volume"]=q.close*q.volume
    return q


def resample_universe(data:dict[str,pd.DataFrame],tf:str)->dict[str,pd.DataFrame]:
    return {s:resample_ohlcv(d,tf) for s,d in data.items()}


def build_features_tf(symbol:str,df:pd.DataFrame,btc:pd.DataFrame,cfg:R11Config)->pd.DataFrame:
    d=add_indicators(df); b=add_indicators(btc).reindex(d.index).ffill()
    out=pd.DataFrame(index=d.index); out["symbol"]=symbol
    h4,h12,h24,h48,h72=[_bars_for_hours(cfg,h) for h in (4,12,24,48,72)]
    out["ret_1b"]=d.close.pct_change(1)
    out["ret_2b"]=d.close.pct_change(2)
    out["ret_4h"]=d.close.pct_change(h4)
    out["ret_12h"]=d.close.pct_change(h12)
    out["ret_24h"]=d.close.pct_change(h24)
    out["ret_72h"]=d.close.pct_change(h72)
    out["rel_btc_24h"]=out.ret_24h-b.close.pct_change(h24)
    out["rel_btc_72h"]=out.ret_72h-b.close.pct_change(h72)
    out["atr_pct"]=d.atr14/d.close
    out["volatility_24h"]=d.close.pct_change().rolling(h24).std(ddof=0)*math.sqrt(max(h24,1))
    out["ema20_dist"]=d.close/d.ema20-1
    out["ema50_dist"]=d.close/d.ema50-1
    out["ema200_dist"]=d.close/d.ema200-1
    out["ema50_slope_24h"]=d.ema50/d.ema50.shift(h24)-1
    out["rsi14"]=d.rsi14/100
    out["adx14"]=d.adx14/100
    out["bb_width"]=d.bb_width
    qv=np.log1p(d.quote_volume)
    out["vol_z_24h"]=(qv-qv.rolling(h24).mean())/qv.rolling(h24).std(ddof=0)
    out["range_overlap_72h"]=_range_overlap(d.high,d.low,max(4,h72))
    hi72=d.high.shift(1).rolling(h72).max(); lo72=d.low.shift(1).rolling(h72).min()
    out["range_pos_72h"]=(d.close-lo72)/(hi72-lo72).replace(0,np.nan)
    hi48=d.high.shift(1).rolling(h48).max(); out["breakout_48h"]=d.close/hi48-1
    out["corr_btc_72h"]=d.close.pct_change().rolling(h72).corr(b.close.pct_change())
    out["btc_ret_24h"]=b.close.pct_change(h24)
    out["btc_ema200_dist"]=b.close/b.ema200-1
    out["btc_adx14"]=b.adx14/100
    out["btc_risk_off"]=((b.close<b.ema200)&(b.ema50<b.ema200)&(b.adx14>=20)).astype(float)
    out["roundtrip_cost"]=cfg.roundtrip_cost
    amp=(d.high.shift(1).rolling(h24).max()-d.low.shift(1).rolling(h24).min())/d.close
    exp_move=pd.concat([1.5*out.atr_pct,0.35*amp],axis=1).max(axis=1)
    out["move_to_cost"]=exp_move/cfg.roundtrip_cost
    out["quote_volume_24h"]=d.quote_volume.shift(1).rolling(h24).sum()
    out["asset_trend"]=((d.ema50>d.ema200)&(out.ema50_slope_24h>0)).astype(float)
    out["asset_recovery"]=((out.ret_24h>0)&(d.close>d.ema20)&(out.rsi14>0.48)).astype(float)
    out["market_breadth_ema200"]=np.nan; out["market_breadth_ret24_pos"]=np.nan
    for c in ("open","high","low","close"): out[c]=d[c]
    return out.replace([np.inf,-np.inf],np.nan)


def deterministic_market_ok(f:pd.DataFrame)->pd.Series:
    risk_on=f.market_risk_on>0
    recovery=f.market_recovery>0
    constructive_range=(f.market_range>0)&(f.market_breadth_ret24_pos>=0.50)&(f.btc_ret_24h>-0.015)
    broad_constructive=(f.btc_ema200_dist>-0.03)&(f.market_breadth_ema200>=0.40)&(f.market_breadth_ret24_pos>=0.55)
    return risk_on|recovery|constructive_range|broad_constructive


def _rank_outcomes(f:pd.DataFrame,mask:pd.Series,cfg:R11Config)->pd.DataFrame:
    n=len(f); idx=f.index
    cols=["gross_return","net_return","stop_frac","tp_frac","entry_time","exit_time","exit_reason"]
    out=pd.DataFrame(index=idx,columns=cols)
    o,h,l,c=[f[x].to_numpy() for x in ("open","high","low","close")]
    delta=cfg.expected_bar_delta
    for i in np.flatnonzero(mask.to_numpy()):
        entry_i=i+1; last_i=entry_i+cfg.rank_horizon_bars-1
        if last_i>=n: continue
        entry=float(o[entry_i]); atr=float(f.iloc[i].atr_pct)
        if not np.isfinite(entry) or entry<=0 or not np.isfinite(atr): continue
        stop=float(np.clip(cfg.atr_stop_mult*atr,cfg.min_stop_frac,cfg.max_stop_frac))
        tp=max(cfg.rank_rr*stop,3.0*cfg.roundtrip_cost)
        sp=entry*(1-stop); tpp=entry*(1+tp)
        gross=None; reason="HORIZON"; exit_i=last_i
        for j in range(entry_i,last_i+1):
            op,hi,lo=float(o[j]),float(h[j]),float(l[j])
            if not all(np.isfinite([op,hi,lo])): continue
            if op<=sp: gross=op/entry-1; reason="GAP_STOP"; exit_i=j; break
            if op>=tpp: gross=op/entry-1; reason="GAP_TP"; exit_i=j; break
            hs=lo<=sp; ht=hi>=tpp
            if hs and ht: gross=-stop; reason="STOP_FIRST_COLLISION"; exit_i=j; break
            if hs: gross=-stop; reason="STOP"; exit_i=j; break
            if ht: gross=tp; reason="TAKE_PROFIT"; exit_i=j; break
        if gross is None: gross=float(c[last_i]/entry-1)
        # idx is bar-close boundary. Next bar opens at the signal close boundary.
        entry_time=idx[i]
        exit_time=idx[exit_i]
        out.loc[idx[i]]=[gross,gross-cfg.roundtrip_cost,stop,tp,entry_time,exit_time,reason]
    for col in ["gross_return","net_return","stop_frac","tp_frac"]:
        out[col]=pd.to_numeric(out[col],errors="coerce")
    return out


def make_dataset(data:dict[str,pd.DataFrame],btc_symbol:str,cfg:R11Config,*,development_symbols:Sequence[str])->pd.DataFrame:
    btc=data[btc_symbol]
    feats={s:build_features_tf(s,d,btc,cfg) for s,d in data.items()}
    feats=_add_market_context(feats,development_symbols)
    feats=_add_extra_ranks(feats,development_symbols)
    chunks=[]
    for sym,f in feats.items():
        anchor=pd.Series(f.index.hour.isin(cfg.decision_hours),index=f.index)
        market_ok=deterministic_market_ok(f)
        mask=anchor & market_ok & (f.quote_volume_24h>=cfg.min_quote_volume_24h) & (f.move_to_cost>=cfg.min_move_to_cost)
        oc=_rank_outcomes(f,mask.fillna(False),cfg)
        g=f.join(oc); g["candidate"]=mask; g["setup_type"]="R11_RANK"
        chunks.append(g[g.candidate])
    x=pd.concat(chunks).sort_index()
    x=x.dropna(subset=R11_FEATURES+["net_return","gross_return","entry_time","exit_time","stop_frac"])
    devset=set(development_symbols); devmask=x.symbol.isin(devset)
    counts=x[devmask].groupby(level=0).size()
    x=x[x.index.to_series().map(counts).fillna(0).to_numpy()>=cfg.min_group_assets].copy()
    devmask=x.symbol.isin(devset); x["target_rank"]=np.nan
    x.loc[devmask,"target_rank"]=x[devmask].groupby(level=0).net_return.rank(pct=True,method="average")
    if (~devmask).any():
        devvals={ts:g.net_return.to_numpy() for ts,g in x[devmask].groupby(level=0)}
        vals=[]
        for ts,r in x[~devmask].iterrows():
            ref=devvals.get(ts); vals.append(float(np.mean(ref<=r.net_return)) if ref is not None and len(ref) else np.nan)
        x.loc[~devmask,"target_rank"]=vals
    return x.dropna(subset=["target_rank"])


def rank_model(cfg:R11Config)->HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="squared_error",learning_rate=.04,max_iter=260,max_leaf_nodes=15,
        min_samples_leaf=cfg.rank_min_leaf,l2_regularization=5.0,random_state=cfg.random_state,
    )


def _slice(ds,start,end,symbols:set[str]):
    return ds[(ds.index>=start)&(ds.index<end)&(ds.symbol.isin(symbols))]


def score_frame(model,frame:pd.DataFrame)->pd.DataFrame:
    z=frame[["symbol","gross_return","net_return","stop_frac","tp_frac","entry_time","exit_time","exit_reason","setup_type"]].copy()
    z["pred_rank"]=model.predict(frame[R11_FEATURES]); return z


def apply_rule(frame:pd.DataFrame,*,top_k:int,min_rank_z:float)->pd.DataFrame:
    if frame.empty:return frame.assign(selected=False,rank_z=np.nan)
    parts=[]
    for ts,g in frame.groupby(level=0,sort=True):
        q=g.copy().sort_values("pred_rank",ascending=False)
        med=float(q.pred_rank.median()); sd=float(q.pred_rank.std(ddof=0)); den=sd if np.isfinite(sd) and sd>1e-9 else 1.0
        q["rank_z"]=(q.pred_rank-med)/den
        take=np.zeros(len(q),dtype=bool); take[:min(top_k,len(q))]=True
        q["selected"]=take & (q.rank_z.to_numpy()>=min_rank_z)
        parts.append(q)
    return pd.concat(parts).sort_index()


def signal_stats(frame:pd.DataFrame)->dict:
    z=frame[frame.selected]
    if z.empty:return {"n":0,"symbols":0,"precision":None,"avg":None,"pf":None,"max_share":None,"positive_blocks":0,"blocks":0}
    vc=z.symbol.value_counts(); pf=_profit_factor(z.net_return)
    base=z.index.min().floor("D"); bid=((z.index-base)/pd.Timedelta(days=10)).astype(int)
    blocks=z.groupby(bid).net_return.mean()
    return {"n":int(len(z)),"symbols":int(vc.size),"precision":float((z.net_return>0).mean()),"avg":float(z.net_return.mean()),"pf":pf,"max_share":float(vc.iloc[0]/len(z)),"positive_blocks":int((blocks>0).sum()),"blocks":int(len(blocks))}


def passes(st:dict,stage:str)->bool:
    if stage=="select":
        return st["n"]>=20 and st["symbols"]>=6 and st["avg"] is not None and st["avg"]>=0.0008 and st["pf"] is not None and st["pf"]>=1.10 and st["precision"]>=0.44 and st["max_share"]<=0.25 and st["positive_blocks"]>=2
    return st["n"]>=8 and st["symbols"]>=4 and st["avg"] is not None and st["avg"]>0 and st["pf"] is not None and st["pf"]>=1.05 and st["precision"]>=0.42 and st["max_share"]<=0.35


def choose_rule(sel:pd.DataFrame,ver:pd.DataFrame)->tuple[dict|None,dict]:
    grid=[]
    for top_k in (1,2):
        for rz in (.50,.75,1.00,1.25,1.50,1.75,2.00):
            ss=signal_stats(apply_rule(sel,top_k=top_k,min_rank_z=rz))
            rec={"top_k":top_k,"min_rank_z":rz,"select":ss}
            if passes(ss,"select"):
                pf=ss["pf"] if ss["pf"] is not None and np.isfinite(ss["pf"]) else 10.0
                rec["score"]=ss["avg"]*100*math.sqrt(ss["n"])+math.log(max(pf,1e-6))+0.03*ss["symbols"]-ss["max_share"]
            else: rec["score"]=-1e9
            grid.append(rec)
    viable=sorted([r for r in grid if r["score"]>-1e8],key=lambda r:r["score"],reverse=True)
    verification=[]
    for r in viable:
        vs=signal_stats(apply_rule(ver,top_k=r["top_k"],min_rank_z=r["min_rank_z"]))
        rr={**r,"verify":vs}; verification.append(rr)
        if passes(vs,"verify"): return rr,{"grid":grid,"verification":verification}
    return None,{"grid":grid,"verification":verification}


def walk_forward(ds:pd.DataFrame,cfg:R11Config,*,development_symbols:Sequence[str],test_symbols:Sequence[str]|None=None):
    dev=set(development_symbols); tst=set(test_symbols) if test_symbols is not None else dev
    if test_symbols is not None and dev&tst: raise ValueError("dev/test overlap")
    start=ds.index.min().floor("D"); end=ds.index.max().ceil("D")
    cursor=start+pd.Timedelta(days=cfg.train_days+cfg.calibration_days); purge=cfg.expected_bar_delta*cfg.purge_bars
    preds=[]; folds=[]
    while cursor+pd.Timedelta(days=cfg.test_days)<=end:
        test0=cursor; test1=cursor+pd.Timedelta(days=cfg.test_days); cal0=test0-pd.Timedelta(days=cfg.calibration_days); train0=cal0-pd.Timedelta(days=cfg.train_days); verify0=test0-pd.Timedelta(days=cfg.calibration_verify_days)
        tr=_slice(ds,train0,cal0-purge,dev); sel=_slice(ds,cal0,verify0-purge,dev); ver=_slice(ds,verify0,test0-purge,dev); te=_slice(ds,test0,test1,tst)
        base={"test_start":str(test0),"train_rows":len(tr),"select_rows":len(sel),"verify_rows":len(ver),"test_rows":len(te)}
        if len(tr)<cfg.min_training_rows or len(sel)<100 or len(ver)<40 or len(te)==0:
            folds.append({**base,"status":"NO_TRADE_INSUFFICIENT_DATA"}); cursor=test1; continue
        m=rank_model(cfg); m.fit(tr[R11_FEATURES],tr.target_rank)
        s=score_frame(m,sel); v=score_frame(m,ver); t=score_frame(m,te)
        rule,_=choose_rule(s,v)
        if rule is None:
            folds.append({**base,"status":"NO_TRADE_NESTED_R11_CALIBRATION"}); cursor=test1; continue
        picked=apply_rule(t,top_k=rule["top_k"],min_rank_z=rule["min_rank_z"])
        picked["meta_score"]=picked.rank_z; picked["threshold"]=rule["min_rank_z"]; picked["fold_test_start"]=test0
        preds.append(picked); st=signal_stats(picked)
        folds.append({**base,"status":"TRADE_GATE_OPEN" if st["n"] else "NO_TRADE_TEST","selected":st["n"],"precision":st["precision"],"avg_net_return":st["avg"],"profit_factor":st["pf"],"symbols":st["symbols"],"top_k":rule["top_k"],"min_rank_z":rule["min_rank_z"],"select_stats":str(rule["select"]),"verify_stats":str(rule["verify"])})
        cursor=test1
    return (pd.concat(preds).sort_index() if preds else pd.DataFrame(),pd.DataFrame(folds))
