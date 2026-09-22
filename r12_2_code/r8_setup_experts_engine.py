"""V10 R8 — True Setup Experts + Nested Calibration + Cross-Sectional Context.

Research-only. Binance Spot/USDT, long-only, 1h, no leverage.
Default action is NO_TRADE.

Key methodological fixes inherited from R7 plus R8:
- signal at bar close, execution only at next bar open (no exact-close fill assumption);
- setup-specific ATR-normalized barriers/horizons;
- event sampling / cooldown to reduce serially duplicated hourly labels;
- mutually-exclusive TREND_PULLBACK / BREAKOUT / RANGE setups;
- setup-specific threshold calibration using realized NET return, PF and temporal stability;
- calibration metrics use ALL selected signals (no dropping sparse losing symbols);
- risk engine is actually simulated: one position/symbol, concurrency, pair correlation,
  risk-based sizing, daily loss circuit breaker and portfolio drawdown stop;
- execution-cost stress re-prices the SAME frozen OOS trades; it does not retrain.
- separate model per setup (true experts, no shared classifier domination);
- threshold chosen on calibration-selection and independently verified on later calibration data;
- cross-sectional ranks versus the broad development universe and explicit market-regime flags.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence
import math
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

SETUPS = ("TREND_PULLBACK", "BREAKOUT", "RANGE")

FEATURES = [
    "ret_1h", "ret_4h", "ret_12h", "ret_24h", "ret_72h",
    "rel_btc_24h", "rel_btc_72h",
    "atr_pct", "volatility_24h", "ema20_dist", "ema50_dist", "ema200_dist",
    "ema50_slope_24h", "rsi14", "adx14", "bb_width", "vol_z_24h",
    "range_overlap_72h", "range_pos_72h", "breakout_48h", "corr_btc_72h",
    "btc_ret_24h", "btc_ema200_dist", "btc_adx14", "btc_risk_off",
    "market_breadth_ema200", "market_breadth_ret24_pos",
    "market_risk_on", "market_range", "market_recovery",
    "cs_ret24_rank", "cs_ret72_rank", "cs_rel_btc24_rank", "cs_ema200_rank", "cs_vol_z_rank",
    "setup_trend_pullback", "setup_breakout", "setup_range",
    "roundtrip_cost", "move_to_cost",
]


@dataclass(frozen=True)
class Config:
    bar_interval: str = "1h"
    interval_tolerance_minutes: int = 5

    fee_side: float = 0.0010
    slippage_side: float = 0.0005
    spread_side: float = 0.0001

    # Event generation / trade economics.
    cooldown_bars: int = 12
    min_quote_volume_24h: float = 10_000_000.0
    min_move_to_cost: float = 3.0

    # Vol-normalized stop bounds and setup-specific reward/horizon.
    atr_stop_mult: float = 1.20
    min_stop_frac: float = 0.007
    max_stop_frac: float = 0.018
    trend_rr: float = 1.70
    breakout_rr: float = 1.90
    range_rr: float = 1.35
    trend_horizon_bars: int = 48
    breakout_horizon_bars: int = 36
    range_horizon_bars: int = 24

    # Walk-forward.
    train_days: int = 180
    calibration_days: int = 60
    test_days: int = 30
    purge_bars: int = 48
    min_training_rows: int = 1200
    min_training_rows_per_setup: int = 350

    # Setup-specific calibration gate.
    min_score: float = 0.50
    max_score: float = 0.88
    threshold_step: float = 0.01
    min_calibration_signals: int = 40
    min_calibration_symbols: int = 8
    min_signals_per_symbol_for_median: int = 2
    max_signal_share_per_symbol: float = 0.20
    min_calibration_precision: float = 0.50
    min_calibration_avg_net: float = 0.0010
    min_calibration_pf: float = 1.15
    min_median_symbol_net: float = 0.0
    calibration_blocks: int = 3
    calibration_verify_days: int = 20
    min_positive_blocks: int = 2
    min_block_signals: int = 5
    worst_block_avg_floor: float = -0.006

    # Portfolio risk. These are now enforced in simulation.
    initial_equity: float = 10_000.0
    risk_fraction: float = 0.003
    max_position_fraction: float = 0.20
    max_concurrent: int = 3
    max_pair_corr: float = 0.80
    corr_lookback_bars: int = 72
    daily_loss_limit: float = 0.02
    max_drawdown: float = 0.08

    random_state: int = 73117

    @property
    def roundtrip_cost(self) -> float:
        return 2 * (self.fee_side + self.slippage_side + self.spread_side)

    @property
    def expected_bar_delta(self) -> pd.Timedelta:
        return pd.Timedelta(self.bar_interval)

    @property
    def max_horizon_bars(self) -> int:
        return max(self.trend_horizon_bars, self.breakout_horizon_bars, self.range_horizon_bars)


def validate_bar_interval(df: pd.DataFrame, cfg: Config, *, symbol: str = "UNKNOWN") -> None:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"{symbol}: index must be DatetimeIndex")
    idx = df.index.sort_values().unique()
    if len(idx) < 3:
        raise ValueError(f"{symbol}: insufficient rows to validate timeframe")
    delta = pd.Series(idx[1:] - idx[:-1]).median()
    tol = pd.Timedelta(minutes=cfg.interval_tolerance_minutes)
    if abs(delta - cfg.expected_bar_delta) > tol:
        raise ValueError(f"{symbol}: expected {cfg.bar_interval}, median={delta}")


def _wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy().sort_index()
    c, h, l, v = d.close, d.high, d.low, d.volume
    for n in (20, 50, 200):
        d[f"ema{n}"] = c.ewm(span=n, adjust=False, min_periods=n).mean()
    prev = c.shift(1)
    tr = pd.concat([(h-l), (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    d["atr14"] = _wilder(tr, 14)
    up, dn = h.diff(), -l.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    plus_di = 100 * _wilder(plus_dm, 14) / d.atr14
    minus_di = 100 * _wilder(minus_dm, 14) / d.atr14
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)
    d["adx14"] = _wilder(dx.fillna(0), 14)
    delta = c.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    rs = _wilder(gain, 14) / _wilder(loss, 14).replace(0, np.nan)
    d["rsi14"] = 100 - 100/(1+rs)
    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    d["bb_width"] = 4*sd20/ma20
    d["quote_volume"] = d.get("quote_volume", c*v)
    return d


def _range_overlap(h: pd.Series, l: pd.Series, look: int = 72) -> pd.Series:
    half = look//2
    hi1, lo1 = h.shift(1).rolling(half).max(), l.shift(1).rolling(half).min()
    hi0, lo0 = h.shift(1+half).rolling(half).max(), l.shift(1+half).rolling(half).min()
    inter = (pd.concat([hi1,hi0],axis=1).min(axis=1) - pd.concat([lo1,lo0],axis=1).max(axis=1)).clip(lower=0)
    denom = pd.concat([(hi1-lo1),(hi0-lo0)],axis=1).min(axis=1).replace(0,np.nan)
    return inter/denom


def build_features(symbol: str, df: pd.DataFrame, btc: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    validate_bar_interval(df, cfg, symbol=symbol)
    validate_bar_interval(btc, cfg, symbol="BTC_REFERENCE")
    d = add_indicators(df)
    b = add_indicators(btc).reindex(d.index).ffill()
    out = pd.DataFrame(index=d.index)
    out["symbol"] = symbol
    for h in (1,4,12,24,72):
        out[f"ret_{h}h"] = d.close.pct_change(h)
    out["rel_btc_24h"] = out.ret_24h - b.close.pct_change(24)
    out["rel_btc_72h"] = out.ret_72h - b.close.pct_change(72)
    out["atr_pct"] = d.atr14/d.close
    out["volatility_24h"] = d.close.pct_change().rolling(24).std(ddof=0)
    out["ema20_dist"] = d.close/d.ema20 - 1
    out["ema50_dist"] = d.close/d.ema50 - 1
    out["ema200_dist"] = d.close/d.ema200 - 1
    out["ema50_slope_24h"] = d.ema50/d.ema50.shift(24) - 1
    out["rsi14"] = d.rsi14/100
    out["adx14"] = d.adx14/100
    out["bb_width"] = d.bb_width
    q = np.log1p(d.quote_volume)
    out["vol_z_24h"] = (q-q.rolling(24).mean())/q.rolling(24).std(ddof=0)
    out["range_overlap_72h"] = _range_overlap(d.high,d.low,72)
    hi72, lo72 = d.high.shift(1).rolling(72).max(), d.low.shift(1).rolling(72).min()
    out["range_pos_72h"] = (d.close-lo72)/(hi72-lo72).replace(0,np.nan)
    hi48 = d.high.shift(1).rolling(48).max()
    out["breakout_48h"] = d.close/hi48 - 1
    out["corr_btc_72h"] = d.close.pct_change().rolling(72).corr(b.close.pct_change())

    out["btc_ret_24h"] = b.close.pct_change(24)
    out["btc_ema200_dist"] = b.close/b.ema200 - 1
    out["btc_adx14"] = b.adx14/100
    out["btc_risk_off"] = ((b.close < b.ema200) & (b.ema50 < b.ema200) & (b.adx14 >= 20)).astype(float)
    out["roundtrip_cost"] = cfg.roundtrip_cost
    amp = (d.high.shift(1).rolling(24).max()-d.low.shift(1).rolling(24).min())/d.close
    expected_move = pd.concat([1.5*out.atr_pct,0.35*amp],axis=1).max(axis=1)
    out["move_to_cost"] = expected_move/cfg.roundtrip_cost
    out["quote_volume_24h"] = d.quote_volume.shift(1).rolling(24).sum()

    # Mutually exclusive setup routing. Breakout gets priority, then range, then trend pullback.
    breakout = (
        (out.breakout_48h > 0)
        & (out.breakout_48h <= 1.5*out.atr_pct)
        & (out.vol_z_24h >= 0.5)
        & (out.adx14 >= 0.18)
        & ((d.ema50 > d.ema200) | (out.rel_btc_24h > 0))
        & (out.ret_1h > 0)
    )
    range_setup = (
        (out.range_overlap_72h >= 0.65)
        & (out.adx14 < 0.22)
        & (out.range_pos_72h <= 0.30)
        & (out.rsi14 <= 0.45)
        & (out.ret_1h > 0)
        & (~breakout)
    )
    trend = (
        (d.ema50 > d.ema200)
        & (out.ema50_slope_24h > 0)
        & (d.close >= 0.995*d.ema50)
        & (d.close <= 1.005*d.ema20)
        & (out.rsi14.between(0.38,0.60))
        & (out.adx14.between(0.15,0.42))
        & (out.ret_1h > 0)
        & (~breakout) & (~range_setup)
    )
    out["setup_breakout"] = breakout.astype(float)
    out["setup_range"] = range_setup.astype(float)
    out["setup_trend_pullback"] = trend.astype(float)
    out["setup_type"] = np.select([breakout,range_setup,trend], ["BREAKOUT","RANGE","TREND_PULLBACK"], default="NONE")

    out["market_breadth_ema200"] = np.nan
    out["market_breadth_ret24_pos"] = np.nan
    for c in ("open","high","low","close"):
        out[c] = d[c]
    return out.replace([np.inf,-np.inf],np.nan)


def _add_market_context(chunks: dict[str,pd.DataFrame], breadth_symbols: Sequence[str] | None=None) -> dict[str,pd.DataFrame]:
    """Breadth + cross-sectional ranks using development symbols only.

    For outer-holdout symbols, percentile features are measured against the development
    universe without allowing the holdout asset to influence the reference distribution.
    """
    breadth_set = set(breadth_symbols) if breadth_symbols is not None else set(chunks)
    missing = breadth_set-set(chunks)
    if missing:
        raise ValueError(f"Missing breadth symbols: {sorted(missing)}")
    dev_syms=[x for x in chunks if x in breadth_set]
    ema_mat=pd.concat({x:chunks[x].ema200_dist for x in dev_syms},axis=1)
    ret_mat=pd.concat({x:chunks[x].ret_24h for x in dev_syms},axis=1)
    breadth_ema=(ema_mat>0).where(ema_mat.notna()).mean(axis=1,skipna=True)
    breadth_ret=(ret_mat>0).where(ret_mat.notna()).mean(axis=1,skipna=True)
    metrics={
        "cs_ret24_rank":"ret_24h",
        "cs_ret72_rank":"ret_72h",
        "cs_rel_btc24_rank":"rel_btc_24h",
        "cs_ema200_rank":"ema200_dist",
        "cs_vol_z_rank":"vol_z_24h",
    }
    mats={src:pd.concat({x:chunks[x][src] for x in dev_syms},axis=1) for src in metrics.values()}
    ranks={src:mat.rank(axis=1,pct=True,method="average") for src,mat in mats.items()}
    out={}
    for sym,f in chunks.items():
        g=f.copy()
        g["market_breadth_ema200"]=breadth_ema.reindex(g.index)
        g["market_breadth_ret24_pos"]=breadth_ret.reindex(g.index)
        for dest,src in metrics.items():
            if sym in breadth_set:
                g[dest]=ranks[src][sym].reindex(g.index)
            else:
                m=mats[src].reindex(g.index)
                vals=g[src]
                g[dest]=m.le(vals,axis=0).mean(axis=1,skipna=True)
        g["market_risk_on"]=(
            (g.btc_ema200_dist>0)&(g.market_breadth_ema200>=0.55)&(g.market_breadth_ret24_pos>=0.50)
        ).astype(float)
        g["market_range"]=(
            (g.btc_adx14<0.22)&g.market_breadth_ema200.between(0.30,0.72)&(g.btc_risk_off==0)
        ).astype(float)
        g["market_recovery"]=(
            (g.btc_ret_24h>0)&(g.market_breadth_ret24_pos>=0.58)&(g.btc_risk_off==0)
        ).astype(float)
        out[sym]=g
    return out

def base_candidate_mask(f: pd.DataFrame, cfg: Config) -> pd.Series:
    liquid = f.quote_volume_24h >= cfg.min_quote_volume_24h
    economic = f.move_to_cost >= cfg.min_move_to_cost
    risk_ok = f.btc_risk_off == 0
    trend_ctx=(f.setup_type=="TREND_PULLBACK")&(f.cs_rel_btc24_rank>=0.45)&((f.market_risk_on>0)|(f.market_recovery>0))
    breakout_ctx=(f.setup_type=="BREAKOUT")&(f.cs_rel_btc24_rank>=0.60)&((f.market_risk_on>0)|(f.market_recovery>0))
    range_ctx=(f.setup_type=="RANGE")&(f.cs_rel_btc24_rank>=0.25)&((f.market_range>0)|(f.market_risk_on>0))
    return liquid & economic & risk_ok & (trend_ctx|breakout_ctx|range_ctx)

def event_sample_mask(f: pd.DataFrame, cfg: Config) -> pd.Series:
    """Keep sparse decision events without using future outcomes."""
    base = base_candidate_mask(f,cfg).fillna(False)
    keep = np.zeros(len(f),dtype=bool)
    last = -10**9
    setup = f.setup_type.to_numpy()
    prev_setup = "NONE"
    for i,is_base in enumerate(base.to_numpy()):
        if not is_base:
            prev_setup = setup[i]
            continue
        changed = setup[i] != prev_setup
        if changed or (i-last) >= cfg.cooldown_bars:
            keep[i]=True; last=i
        prev_setup=setup[i]
    return pd.Series(keep,index=f.index)


def _setup_trade_params(row: pd.Series, cfg: Config) -> tuple[float,float,int]:
    stop = float(np.clip(cfg.atr_stop_mult*row.atr_pct, cfg.min_stop_frac, cfg.max_stop_frac))
    if row.setup_type == "BREAKOUT": rr,h = cfg.breakout_rr,cfg.breakout_horizon_bars
    elif row.setup_type == "RANGE": rr,h = cfg.range_rr,cfg.range_horizon_bars
    else: rr,h = cfg.trend_rr,cfg.trend_horizon_bars
    tp = max(rr*stop, 2.5*cfg.roundtrip_cost)
    return stop,tp,h


def event_outcomes(f: pd.DataFrame, event_mask: pd.Series, cfg: Config) -> pd.DataFrame:
    """Next-bar-open execution with gap-aware, pessimistic OHLC barrier resolution."""
    n=len(f)
    result = pd.DataFrame(index=f.index, columns=[
        "label","gross_return","net_return","stop_frac","tp_frac","horizon_bars",
        "entry_time","exit_time","exit_bars","exit_reason"
    ])
    o,h,l,c = [f[x].to_numpy() for x in ("open","high","low","close")]
    idx=f.index
    cost=cfg.roundtrip_cost
    for i in np.flatnonzero(event_mask.to_numpy()):
        if i+1 >= n: continue
        row=f.iloc[i]
        stop_frac,tp_frac,horizon=_setup_trade_params(row,cfg)
        entry_i=i+1
        last_i=entry_i+horizon-1
        if last_i >= n: continue
        entry=float(o[entry_i])
        if not np.isfinite(entry) or entry<=0: continue
        stop_p=entry*(1-stop_frac); tp_p=entry*(1+tp_frac)
        gross=None; reason="HORIZON"; exit_i=last_i
        for j in range(entry_i,last_i+1):
            op=float(o[j]); hi=float(h[j]); lo=float(l[j])
            if not all(np.isfinite([op,hi,lo])): continue
            if op <= stop_p:
                gross=op/entry-1; reason="GAP_STOP"; exit_i=j; break
            if op >= tp_p:
                gross=op/entry-1; reason="GAP_TP"; exit_i=j; break
            hit_sl=lo<=stop_p; hit_tp=hi>=tp_p
            if hit_sl and hit_tp:
                gross=-stop_frac; reason="STOP_FIRST_COLLISION"; exit_i=j; break
            if hit_sl:
                gross=-stop_frac; reason="STOP"; exit_i=j; break
            if hit_tp:
                gross=tp_frac; reason="TAKE_PROFIT"; exit_i=j; break
        if gross is None:
            gross=float(c[last_i]/entry-1); exit_i=last_i
        net=float(gross-cost)
        result.loc[idx[i]]=[float(net>0),gross,net,stop_frac,tp_frac,horizon,idx[entry_i],idx[exit_i],exit_i-entry_i+1,reason]
    for cnum in ["label","gross_return","net_return","stop_frac","tp_frac","horizon_bars","exit_bars"]:
        result[cnum]=pd.to_numeric(result[cnum],errors="coerce")
    return result


def make_dataset(data: dict[str,pd.DataFrame], btc_symbol: str, cfg: Config, *, breadth_symbols: Sequence[str]|None=None) -> pd.DataFrame:
    if btc_symbol not in data: raise KeyError(f"BTC reference {btc_symbol} missing")
    btc=data[btc_symbol]
    feats={s:build_features(s,d,btc,cfg) for s,d in data.items()}
    feats=_add_market_context(feats,breadth_symbols)
    chunks=[]
    for s,f in feats.items():
        ev=event_sample_mask(f,cfg)
        outcomes=event_outcomes(f,ev,cfg)
        g=f.join(outcomes)
        g["candidate"]=ev
        chunks.append(g[g.candidate])
    if not chunks: return pd.DataFrame()
    x=pd.concat(chunks).sort_index()
    return x.dropna(subset=FEATURES+["label","net_return","entry_time","exit_time","stop_frac"])


def model(cfg: Config) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=0.035,max_iter=220,max_leaf_nodes=15,min_samples_leaf=45,
        l2_regularization=4.0,random_state=cfg.random_state,
    )


def _profit_factor(r: pd.Series) -> float|None:
    pos=float(r[r>0].sum()); neg=float(-r[r<0].sum())
    if neg<=0: return None if pos<=0 else math.inf
    return pos/neg


def _screen_stats(frame:pd.DataFrame, threshold:float, cfg:Config, *, stage:str)->dict|None:
    z=frame[frame.meta_score>=threshold].copy()
    if stage=="select":
        min_n,max_share,min_symbols,min_precision,min_avg,min_pf=25,0.25,6,0.48,0.0,1.05
    else:
        min_n,max_share,min_symbols,min_precision,min_avg,min_pf=10,0.30,5,0.50,0.0005,1.10
    if len(z)<min_n:return None
    counts=z.symbol.value_counts(); coverage=int((counts>=1).sum())
    if coverage<min_symbols:return None
    share=float(counts.iloc[0]/len(z))
    if share>max_share:return None
    precision=float(z.label.mean()); avg=float(z.net_return.mean()); pf=_profit_factor(z.net_return)
    if precision<min_precision or avg<min_avg:return None
    if pf is None or (not math.isinf(pf) and pf<min_pf):return None
    sym_avg=z.groupby("symbol").net_return.mean(); med=float(sym_avg.median())
    if stage=="verify" and med<0:return None
    return {"threshold":float(threshold),"selected":len(z),"symbols":coverage,"precision":precision,"avg_net_return":avg,"profit_factor":pf,"median_symbol_net":med,"max_signal_share":share}


def choose_threshold_on_selection(frame:pd.DataFrame,cfg:Config)->tuple[float|None,dict|None]:
    best=None
    for th in np.arange(cfg.min_score,cfg.max_score+1e-9,cfg.threshold_step):
        st=_screen_stats(frame,float(th),cfg,stage="select")
        if st is None:continue
        pf=st["profit_factor"]
        score=st["avg_net_return"]*100*math.sqrt(st["selected"])+(math.log(pf) if pf and not math.isinf(pf) else 1.5)+0.04*st["symbols"]-st["max_signal_share"]
        st["score"]=score
        if best is None or score>best["score"]:best=st
    return (None,None) if best is None else (best["threshold"],best)


def _slice(ds,start,end,symbols:set[str]):
    return ds[(ds.index>=start)&(ds.index<end)&(ds.symbol.isin(symbols))]


def walk_forward_cross_asset(ds: pd.DataFrame,cfg: Config,*,development_symbols:Sequence[str]|None=None,test_symbols:Sequence[str]|None=None):
    """True setup experts with nested calibration select -> verify -> untouched test."""
    if ds.empty:return pd.DataFrame(),pd.DataFrame()
    all_symbols=set(ds.symbol.unique());dev=set(development_symbols) if development_symbols is not None else all_symbols;tst=set(test_symbols) if test_symbols is not None else dev
    if test_symbols is not None and dev&tst:raise ValueError("development and test symbols must be disjoint")
    if not dev<=all_symbols:raise ValueError(f"Missing dev symbols {sorted(dev-all_symbols)}")
    if not tst<=all_symbols:raise ValueError(f"Missing test symbols {sorted(tst-all_symbols)}")
    start=ds.index.min().floor("D");end=ds.index.max().ceil("D")
    cursor=start+pd.Timedelta(days=cfg.train_days+cfg.calibration_days);purge=cfg.expected_bar_delta*cfg.purge_bars
    preds=[];folds=[]
    while cursor+pd.Timedelta(days=cfg.test_days)<=end:
        test0=cursor;test1=cursor+pd.Timedelta(days=cfg.test_days);cal0=test0-pd.Timedelta(days=cfg.calibration_days);train0=cal0-pd.Timedelta(days=cfg.train_days)
        verify0=test0-pd.Timedelta(days=cfg.calibration_verify_days)
        tr=_slice(ds,train0,cal0-purge,dev); ca_sel=_slice(ds,cal0,verify0-purge,dev); ca_ver=_slice(ds,verify0,test0-purge,dev); te=_slice(ds,test0,test1,tst)
        base={"test_start":str(test0),"test_end":str(test1),"train_rows":len(tr),"cal_select_rows":len(ca_sel),"cal_verify_rows":len(ca_ver),"test_rows":len(te),"development_symbols":len(dev),"test_symbols":len(tst)}
        if len(tr)<cfg.min_training_rows or len(te)==0:
            folds.append({**base,"status":"NO_TRADE_INSUFFICIENT_DATA"});cursor=test1;continue
        test_parts=[]; expert_info={}; aucs=[]
        for setup in SETUPS:
            tr_s=tr[tr.setup_type==setup]; sel_s=ca_sel[ca_sel.setup_type==setup]; ver_s=ca_ver[ca_ver.setup_type==setup]; te_s=te[te.setup_type==setup]
            if len(tr_s)<cfg.min_training_rows_per_setup or len(sel_s)<25 or len(ver_s)<10 or len(te_s)==0 or tr_s.label.nunique()<2:
                continue
            m=model(cfg);m.fit(tr_s[FEATURES],tr_s.label.astype(int))
            sel=sel_s[["symbol","label","net_return"]].copy();sel["meta_score"]=m.predict_proba(sel_s[FEATURES])[:,1]
            th,sel_stats=choose_threshold_on_selection(sel,cfg)
            if th is None:continue
            ver=ver_s[["symbol","label","net_return"]].copy();ver["meta_score"]=m.predict_proba(ver_s[FEATURES])[:,1]
            ver_stats=_screen_stats(ver,th,cfg,stage="verify")
            if ver_stats is None:continue
            pp=m.predict_proba(te_s[FEATURES])[:,1]
            tmp=te_s[["symbol","setup_type","label","gross_return","net_return","stop_frac","tp_frac","entry_time","exit_time","exit_reason","close"]].copy();tmp["meta_score"]=pp;tmp["threshold"]=th;tmp["selected"]=pp>=th;tmp["fold_test_start"]=test0
            test_parts.append(tmp)
            auc=float(roc_auc_score(te_s.label,pp)) if te_s.label.nunique()>1 else None
            if auc is not None:aucs.append(auc)
            expert_info[setup]={"threshold":th,"select":sel_stats,"verify":ver_stats,"test_selected":int(tmp.selected.sum()),"test_precision":float(tmp[tmp.selected].label.mean()) if tmp.selected.any() else None,"test_avg":float(tmp[tmp.selected].net_return.mean()) if tmp.selected.any() else None,"test_auc":auc}
        if not expert_info:
            folds.append({**base,"status":"NO_TRADE_NESTED_CALIBRATION"});cursor=test1;continue
        tmp=pd.concat(test_parts).sort_index() if test_parts else pd.DataFrame()
        if not tmp.empty:preds.append(tmp)
        selected=tmp[tmp.selected] if not tmp.empty else pd.DataFrame()
        folds.append({**base,"status":"TRADE_GATE_OPEN" if len(selected) else "NO_TRADE_TEST","enabled_setups":"|".join(sorted(expert_info)),"selected":len(selected),"precision":float(selected.label.mean()) if len(selected) else None,"avg_net_return":float(selected.net_return.mean()) if len(selected) else None,"profit_factor":_profit_factor(selected.net_return) if len(selected) else None,"mean_test_auc":float(np.mean(aucs)) if aucs else None,"experts_json":str(expert_info)})
        cursor=test1
    return (pd.concat(preds).sort_index() if preds else pd.DataFrame(),pd.DataFrame(folds))

def _rolling_corr(data:dict[str,pd.DataFrame],s1:str,s2:str,t:pd.Timestamp,lookback:int)->float|None:
    if s1 not in data or s2 not in data: return None
    a=data[s1].close.loc[:t].tail(lookback+1).pct_change().dropna(); b=data[s2].close.loc[:t].tail(lookback+1).pct_change().dropna()
    q=pd.concat([a,b],axis=1,join="inner").dropna()
    if len(q)<max(24,lookback//2): return None
    x=float(q.iloc[:,0].corr(q.iloc[:,1])); return x if np.isfinite(x) else None


def simulate_portfolio(selected:pd.DataFrame,data:dict[str,pd.DataFrame],cfg:Config,*,extra_roundtrip_cost:float=0.0)->tuple[pd.DataFrame,dict]:
    if selected.empty: return pd.DataFrame(),{"trades":0,"status":"NO_TRADES"}
    sig=selected[selected.selected].copy().sort_values(["entry_time","meta_score"],ascending=[True,False])
    if sig.empty: return pd.DataFrame(),{"trades":0,"status":"NO_TRADES"}
    equity=cfg.initial_equity; peak=equity; active=[]; accepted=[]; daily_realized={}; stopped=False
    rejects={"same_symbol":0,"max_concurrent":0,"correlation":0,"daily_loss":0,"drawdown_stop":0}

    def realize_until(t):
        nonlocal equity,peak,active
        done=[p for p in active if p["exit_time"]<=t]
        active=[p for p in active if p["exit_time"]>t]
        for p in sorted(done,key=lambda z:z["exit_time"]):
            equity += p["pnl_cash"]
            d=p["exit_time"].date(); daily_realized[d]=daily_realized.get(d,0.0)+p["pnl_cash"]
            peak=max(peak,equity)

    for ix,row in sig.iterrows():
        entry_time=pd.Timestamp(row.entry_time); exit_time=pd.Timestamp(row.exit_time)
        realize_until(entry_time)
        dd=1-equity/peak if peak>0 else 1
        if dd>=cfg.max_drawdown:
            rejects["drawdown_stop"]+=1; stopped=True; continue
        day_loss=-min(0.0,daily_realized.get(entry_time.date(),0.0))/max(equity,1e-9)
        if day_loss>=cfg.daily_loss_limit:
            rejects["daily_loss"]+=1; continue
        if any(p["symbol"]==row.symbol for p in active):
            rejects["same_symbol"]+=1; continue
        if len(active)>=cfg.max_concurrent:
            rejects["max_concurrent"]+=1; continue
        correlated=False
        for p in active:
            corr=_rolling_corr(data,row.symbol,p["symbol"],ix,cfg.corr_lookback_bars)
            if corr is not None and corr>=cfg.max_pair_corr:
                correlated=True; break
        if correlated:
            rejects["correlation"]+=1; continue
        stop=max(float(row.stop_frac),1e-6)
        pos_frac=min(cfg.max_position_fraction,cfg.risk_fraction/stop)
        gross=float(row.gross_return)
        net=gross-cfg.roundtrip_cost-extra_roundtrip_cost
        pnl_cash=equity*pos_frac*net
        rec={"signal_time":ix,"entry_time":entry_time,"exit_time":exit_time,"symbol":row.symbol,"setup_type":row.setup_type,"meta_score":float(row.meta_score),"threshold":float(row.threshold),"position_fraction":pos_frac,"gross_return":gross,"net_return":net,"stop_frac":stop,"pnl_cash":pnl_cash,"equity_at_entry":equity,"label":float(net>0)}
        accepted.append(rec); active.append(rec)
    if accepted:
        realize_until(max(p["exit_time"] for p in active) if active else max(pd.Timestamp(x["exit_time"]) for x in accepted))
    trades=pd.DataFrame(accepted)
    if trades.empty: return trades,{"trades":0,"status":"NO_ACCEPTED_TRADES","rejects":rejects}
    pnl=trades.pnl_cash
    # Equity curve by realized exits.
    q=trades.sort_values("exit_time").copy(); q["equity_after"]=cfg.initial_equity+q.pnl_cash.cumsum(); q["peak"]=q.equity_after.cummax(); q["dd"]=1-q.equity_after/q.peak
    gains=float(pnl[pnl>0].sum()); losses=float(-pnl[pnl<0].sum()); pf=(math.inf if losses<=0 and gains>0 else (gains/losses if losses>0 else None))
    symbol_profit=trades.groupby("symbol").pnl_cash.sum(); positive=symbol_profit[symbol_profit>0].sum(); concentration=float(symbol_profit.max()/positive) if positive>0 else None
    report={"trades":len(trades),"precision":float((trades.net_return>0).mean()),"avg_asset_net_return":float(trades.net_return.mean()),"profit_factor_cash":pf,"portfolio_return":float((cfg.initial_equity+pnl.sum())/cfg.initial_equity-1),"max_drawdown":float(q.dd.max()),"ending_equity":float(cfg.initial_equity+pnl.sum()),"symbols":trades.symbol.value_counts().to_dict(),"setups":trades.setup_type.value_counts().to_dict(),"largest_positive_symbol_profit_share":concentration,"rejects":rejects,"drawdown_stop_triggered":stopped}
    return trades,report


def selection_report(pred:pd.DataFrame)->dict:
    if pred.empty or "selected" not in pred: return {"selected":0,"status":"NO_TRADES"}
    s=pred[pred.selected]
    if s.empty: return {"selected":0,"status":"NO_TRADES"}
    return {"selected":len(s),"precision":float(s.label.mean()),"avg_net_return":float(s.net_return.mean()),"profit_factor":_profit_factor(s.net_return),"symbols":s.symbol.value_counts().to_dict(),"setups":s.setup_type.value_counts().to_dict(),"median_score":float(s.meta_score.median())}


def stress_extra_roundtrip(cfg:Config,slippage_multiplier:float)->float:
    stressed=2*(cfg.fee_side+cfg.slippage_side*slippage_multiplier+cfg.spread_side)
    return max(0.0,stressed-cfg.roundtrip_cost)

if __name__=="__main__":
    import json; print(json.dumps(asdict(Config()),indent=2))
