#!/usr/bin/env python3
"""R15.5.1 - Technical Intelligence Expansion.

Adds complementary, causal technical-analysis features to the R15 dataset.
No future candle is used in any feature. Higher-timeframe features become
available only after their candle closes.

Families:
- momentum: RSI, MACD, Stochastic, Williams %R, CCI, ROC
- volatility/channels: Bollinger, Keltner squeeze, Donchian
- volume/flow: rolling VWAP, OBV impulse, MFI, CMF, taker imbalance
- candle anatomy/patterns: body/wicks, inside/outside, engulfing, doji, hammer
- structure: confirmed swings, HH/HL/LH/LL, BOS, CHoCH, pivot distances
- divergence: causal price-vs-RSI/MACD disagreement

Output contains ONLY the added features keyed by symbol/available_time, so the
existing R15.3 dataset stays immutable and can be joined later.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("r15_regime_lab/history")
OUT=Path("r15_regime_lab/technical_expansion")
(OUT/"symbols").mkdir(parents=True,exist_ok=True)

TFS={"15m":900_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000}
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def read(sym,tf):
    p=ROOT/tf/f"{sym}.csv.gz"
    if not p.exists(): return None
    x=pd.read_csv(p)
    for c in ["open_time","open","high","low","close","volume","quote_volume","taker_buy_base_volume"]:
        if c in x: x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna(subset=["open_time","open","high","low","close"]).sort_values("open_time").drop_duplicates("open_time")
    x["open_time"]=x.open_time.astype("int64")
    x["available_time"]=x.open_time+TFS[tf]
    return x.reset_index(drop=True)

def rma(s,n):
    return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def rsi(c,n=14):
    d=c.diff(); up=d.clip(lower=0); dn=(-d).clip(lower=0)
    rs=rma(up,n)/rma(dn,n).replace(0,np.nan)
    return 100-(100/(1+rs))

def atr_series(h,l,c,n=14):
    pc=c.shift(1)
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return rma(tr,n),tr

def confirmed_swings(h,l,atr):
    # At time t, a pivot at t-2 is confirmed from bars t-4..t. Causal.
    ph=h.shift(2).eq(h.rolling(5,min_periods=5).max())
    pl=l.shift(2).eq(l.rolling(5,min_periods=5).min())
    cand_hi=h.shift(2).where(ph)
    cand_lo=l.shift(2).where(pl)
    last_hi=cand_hi.ffill(); last_lo=cand_lo.ffill()
    prev_hi=last_hi.where(ph).shift(1).ffill()
    prev_lo=last_lo.where(pl).shift(1).ffill()
    idx=np.arange(len(h),dtype=float)
    ih=pd.Series(np.where(ph,idx,np.nan),index=h.index).ffill()
    il=pd.Series(np.where(pl,idx,np.nan),index=l.index).ffill()
    bars_hi=pd.Series(idx,index=h.index)-ih
    bars_lo=pd.Series(idx,index=l.index)-il
    hi_delta=(last_hi-prev_hi)/atr.replace(0,np.nan)
    lo_delta=(last_lo-prev_lo)/atr.replace(0,np.nan)
    bullish=(hi_delta>0)&(lo_delta>0)
    bearish=(hi_delta<0)&(lo_delta<0)
    structure=np.select([bullish,bearish],[1.0,-1.0],default=0.0)
    return ph,pl,last_hi,last_lo,prev_hi,prev_lo,bars_hi,bars_lo,hi_delta,lo_delta,pd.Series(structure,index=h.index)

def build(x,tf):
    o,h,l,c,v=[x[k].astype(float) for k in ["open","high","low","close","volume"]]
    atr,tr=atr_series(h,l,c,14); atr0=atr.replace(0,np.nan)
    rr=(h-l).replace(0,np.nan); tp=(h+l+c)/3.0
    p=tf+"_ta_"
    q=pd.DataFrame({"available_time":x.available_time.astype("int64")})

    # Momentum
    r=rsi(c,14)
    ema12=c.ewm(span=12,adjust=False,min_periods=12).mean()
    ema26=c.ewm(span=26,adjust=False,min_periods=26).mean()
    macd=ema12-ema26; macds=macd.ewm(span=9,adjust=False,min_periods=9).mean(); hist=macd-macds
    ll14=l.rolling(14,min_periods=14).min(); hh14=h.rolling(14,min_periods=14).max()
    stoch=100*(c-ll14)/(hh14-ll14).replace(0,np.nan)
    stochd=stoch.rolling(3,min_periods=3).mean()
    willr=-100*(hh14-c)/(hh14-ll14).replace(0,np.nan)
    sma20=tp.rolling(20,min_periods=20).mean()
    mad20=tp.rolling(20,min_periods=20).apply(lambda a: np.mean(np.abs(a-np.mean(a))),raw=True)
    cci=(tp-sma20)/(0.015*mad20.replace(0,np.nan))
    q[p+"rsi14"]=r
    q[p+"macd_atr"]=macd/atr0; q[p+"macd_signal_atr"]=macds/atr0; q[p+"macd_hist_atr"]=hist/atr0
    q[p+"stoch_k14"]=stoch; q[p+"stoch_d3"]=stochd; q[p+"willr14"]=willr
    q[p+"cci20"]=cci
    q[p+"roc10"]=c/c.shift(10)-1; q[p+"roc20"]=c/c.shift(20)-1

    # Bollinger / Keltner / Donchian
    mid=c.rolling(20,min_periods=20).mean(); sd=c.rolling(20,min_periods=20).std()
    bb_u=mid+2*sd; bb_l=mid-2*sd
    ema20=c.ewm(span=20,adjust=False,min_periods=20).mean()
    kc_u=ema20+2*atr; kc_l=ema20-2*atr
    dc20_h=h.shift(1).rolling(20,min_periods=20).max(); dc20_l=l.shift(1).rolling(20,min_periods=20).min()
    dc55_h=h.shift(1).rolling(55,min_periods=55).max(); dc55_l=l.shift(1).rolling(55,min_periods=55).min()
    q[p+"bb_pctb20"]=(c-bb_l)/(bb_u-bb_l).replace(0,np.nan)
    q[p+"bb_bandwidth20"]=(bb_u-bb_l)/mid.replace(0,np.nan)
    q[p+"bb_z20"]=(c-mid)/sd.replace(0,np.nan)
    q[p+"keltner_pos20"]=(c-kc_l)/(kc_u-kc_l).replace(0,np.nan)
    q[p+"bb_kc_width_ratio"]=(bb_u-bb_l)/(kc_u-kc_l).replace(0,np.nan)
    q[p+"squeeze_on"]=((bb_u<kc_u)&(bb_l>kc_l)).astype(float)
    q[p+"donchian_pos20"]=(c-dc20_l)/(dc20_h-dc20_l).replace(0,np.nan)
    q[p+"donchian_pos55"]=(c-dc55_l)/(dc55_h-dc55_l).replace(0,np.nan)
    q[p+"donchian_break20_up_atr"]=(c-dc20_h)/atr0
    q[p+"donchian_break20_dn_atr"]=(dc20_l-c)/atr0

    # Volume / flow / VWAP
    pv=tp*v
    vwap20=pv.rolling(20,min_periods=20).sum()/v.rolling(20,min_periods=20).sum().replace(0,np.nan)
    vwap50=pv.rolling(50,min_periods=50).sum()/v.rolling(50,min_periods=50).sum().replace(0,np.nan)
    direction=np.sign(c.diff()).fillna(0)
    obv=(direction*v).cumsum()
    obv_imp=(obv-obv.shift(20))/v.rolling(20,min_periods=20).sum().replace(0,np.nan)
    rmf=tp*v; pos=rmf.where(tp.diff()>0,0.0); neg=rmf.where(tp.diff()<0,0.0)
    mfr=pos.rolling(14,min_periods=14).sum()/neg.rolling(14,min_periods=14).sum().replace(0,np.nan)
    mfi=100-(100/(1+mfr))
    mfm=((c-l)-(h-c))/rr
    cmf=(mfm*v).rolling(20,min_periods=20).sum()/v.rolling(20,min_periods=20).sum().replace(0,np.nan)
    q[p+"vwap20_dist_atr"]=(c-vwap20)/atr0; q[p+"vwap50_dist_atr"]=(c-vwap50)/atr0
    q[p+"obv_impulse20"]=obv_imp; q[p+"mfi14"]=mfi; q[p+"cmf20"]=cmf
    if "taker_buy_base_volume" in x:
        tb=x.taker_buy_base_volume.astype(float)
        imb=(2*tb/v.replace(0,np.nan))-1
        q[p+"taker_imbalance"]=imb
        q[p+"taker_imbalance_mean10"]=imb.rolling(10,min_periods=10).mean()

    # Candle anatomy / patterns
    body=c-o; absbody=body.abs()
    upper=h-np.maximum(o,c); lower=np.minimum(o,c)-l
    prev_o=o.shift(); prev_c=c.shift()
    q[p+"body_frac"]=body/rr
    q[p+"body_abs_frac"]=absbody/rr
    q[p+"upper_wick_frac"]=upper/rr; q[p+"lower_wick_frac"]=lower/rr
    q[p+"close_location"]=(c-l)/rr
    q[p+"range_atr"]=rr/atr0
    q[p+"doji"]=(absbody<=.10*rr).astype(float)
    q[p+"inside_bar"]=((h<h.shift())&(l>l.shift())).astype(float)
    q[p+"outside_bar"]=((h>h.shift())&(l<l.shift())).astype(float)
    bull_eng=(c>o)&(prev_c<prev_o)&(o<=prev_c)&(c>=prev_o)
    bear_eng=(c<o)&(prev_c>prev_o)&(o>=prev_c)&(c<=prev_o)
    q[p+"bull_engulf"]=bull_eng.astype(float); q[p+"bear_engulf"]=bear_eng.astype(float)
    q[p+"hammer"]=((lower>=2*absbody)&(upper<=absbody)&(body>0)).astype(float)
    q[p+"shooting_star"]=((upper>=2*absbody)&(lower<=absbody)&(body<0)).astype(float)

    # Confirmed market structure, BOS and CHoCH
    ph,pl,last_hi,last_lo,prev_hi,prev_lo,bars_hi,bars_lo,hi_delta,lo_delta,structure=confirmed_swings(h,l,atr)
    ref_hi=last_hi.shift(1); ref_lo=last_lo.shift(1)
    bos_up=(c>ref_hi)&(c.shift()<=ref_hi)
    bos_dn=(c<ref_lo)&(c.shift()>=ref_lo)
    q[p+"swing_high_dist_atr"]=(last_hi-c)/atr0
    q[p+"swing_low_dist_atr"]=(c-last_lo)/atr0
    q[p+"bars_since_swing_high"]=bars_hi.clip(upper=500)
    q[p+"bars_since_swing_low"]=bars_lo.clip(upper=500)
    q[p+"swing_high_delta_atr"]=hi_delta; q[p+"swing_low_delta_atr"]=lo_delta
    q[p+"structure_bias"]=structure
    q[p+"bos_up"]=bos_up.astype(float); q[p+"bos_down"]=bos_dn.astype(float)
    q[p+"choch_up"]=(bos_up&(structure.shift(1)<0)).astype(float)
    q[p+"choch_down"]=(bos_dn&(structure.shift(1)>0)).astype(float)

    # Causal divergence proxies
    p14=c/c.shift(14)-1; r14=r-r.shift(14); mh14=hist-hist.shift(14)
    q[p+"bull_rsi_div14"]=((p14<0)&(r14>5)).astype(float)
    q[p+"bear_rsi_div14"]=((p14>0)&(r14<-5)).astype(float)
    q[p+"bull_macd_div14"]=((p14<0)&(mh14>0)).astype(float)
    q[p+"bear_macd_div14"]=((p14>0)&(mh14<0)).astype(float)

    # Additional persistence/context
    q[p+"tr_median_ratio20"]=tr/tr.rolling(20,min_periods=20).median().replace(0,np.nan)
    q[p+"volume_price_corr20"]=c.pct_change().rolling(20,min_periods=20).corr(v.pct_change())
    return q

def build_symbol(sym):
    base=read(sym,"15m")
    if base is None or base.empty:return None
    merged=build(base,"15m").sort_values("available_time")
    for tf in ["1h","4h","1d"]:
        x=read(sym,tf)
        if x is None or x.empty:continue
        f=build(x,tf).sort_values("available_time")
        merged=pd.merge_asof(merged,f,on="available_time",direction="backward",allow_exact_matches=True)
    merged.insert(0,"symbol",sym)
    merged["ts"]=pd.to_datetime(merged.available_time,unit="ms",utc=True)
    for c in merged.select_dtypes("float64").columns:
        merged[c]=pd.to_numeric(merged[c],downcast="float")
    return merged

aud=[]; samples=[]
for i,sym in enumerate(SYMBOLS,1):
    d=build_symbol(sym)
    if d is None:continue
    featcols=[c for c in d.columns if "_ta_" in c]
    coverage=d[featcols].notna().mean(axis=1)
    aud.append({"symbol":sym,"rows":len(d),"new_features":len(featcols),
                "median_coverage":float(coverage.median()),
                "p05_coverage":float(coverage.quantile(.05)),
                "start":str(d.ts.min()),"end":str(d.ts.max())})
    d.to_parquet(OUT/"symbols"/f"{sym}.parquet",index=False,compression="zstd")
    s=d.iloc[::50][featcols].copy()
    if len(s)>2500:s=s.sample(2500,random_state=1551)
    samples.append(s)
    print(f"[{i:02d}/{len(SYMBOLS)}] {sym}: {len(d):,} rows, {len(featcols)} new features",flush=True)

A=pd.DataFrame(aud); A.to_csv(OUT/"audit.csv",index=False)
S=pd.concat(samples,ignore_index=True) if samples else pd.DataFrame()
redundant=[]
constant=[]
if not S.empty:
    nun=S.nunique(dropna=True)
    constant=nun[nun<=1].index.tolist()
    usable=[c for c in S.columns if c not in constant]
    corr=S[usable].corr().abs()
    arr=corr.to_numpy()
    names=corr.columns.tolist()
    iu=np.triu_indices_from(arr,k=1)
    for a,b in zip(iu[0],iu[1]):
        v=arr[a,b]
        if np.isfinite(v) and v>=.985:
            redundant.append({"feature_a":names[a],"feature_b":names[b],"abs_corr":float(v)})
pd.DataFrame(redundant).sort_values("abs_corr",ascending=False).to_csv(OUT/"high_correlation_pairs.csv",index=False)
summary={
  "version":"R15.5.1",
  "symbols":int(len(A)),
  "base_rows_15m":int(A.rows.sum()),
  "new_features_per_symbol":int(A.new_features.median()) if len(A) else 0,
  "median_feature_coverage":float(A.median_coverage.median()) if len(A) else None,
  "families":["momentum","bands_channels","volume_flow_vwap","candlestick_price_action","swings_bos_choch","divergence"],
  "constant_features_in_sample":constant,
  "high_corr_pairs_ge_0_985":int(len(redundant)),
  "causality":"All indicators use current/past completed candles only; 5-bar pivots are delayed two bars and become visible only when confirmed; HTF features are backward-asof joined at candle close.",
  "notes":"Expansion artifact contains only new features. R15.3 remains immutable."
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
