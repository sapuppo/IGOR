#!/usr/bin/env python3
"""R15.3 - Build causal multi-timeframe market-structure dataset.

Inputs: R15.2 history/<tf>/<symbol>.csv.gz
Base decision clock: 15m candle close.
Higher-timeframe features become available only AFTER their candle closes.
Future-derived labels are generated only for development periods; outer holdout
(>= 2026-07-01 UTC) remains unlabeled/sealed.
"""
from __future__ import annotations
import json, zlib
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path("r15_regime_lab/history")
OUT=Path("r15_regime_lab/processed")
TFS={"15m":900_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000}
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']
OUTER_HOLDOUT=pd.Timestamp("2026-07-01T00:00:00Z")

def read(sym,tf):
    p=ROOT/tf/f"{sym}.csv.gz"
    if not p.exists(): return None
    x=pd.read_csv(p)
    x["open_time"]=pd.to_numeric(x.open_time,errors="coerce").astype("Int64")
    for c in ["open","high","low","close","volume","quote_volume","trades","taker_buy_base_volume","taker_buy_quote_volume"]:
        if c in x: x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna(subset=["open_time","open","high","low","close"]).sort_values("open_time").drop_duplicates("open_time")
    x["open_time"]=x.open_time.astype("int64")
    x["available_time"]=x.open_time+TFS[tf]
    return x

def rma(s,n):
    return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def feat(x,tf):
    z=x.copy()
    c,h,l,v=z.close,z.high,z.low,z.volume
    prev=c.shift()
    tr=pd.concat([h-l,(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff(); dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.0),14)/atr
    minus=100*rma(dn.where((dn>up)&(dn>0),0.0),14)/atr
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    adx=rma(dx,14)
    logret=np.log(c/c.shift())
    hi20=h.shift(1).rolling(20,min_periods=20).max()
    lo20=l.shift(1).rolling(20,min_periods=20).min()
    width=hi20-lo20; mid=(hi20+lo20)/2
    ema20=c.ewm(span=20,adjust=False,min_periods=20).mean()
    ema50=c.ewm(span=50,adjust=False,min_periods=50).mean()
    eff=(c-c.shift(20)).abs()/c.diff().abs().rolling(20,min_periods=20).sum().replace(0,np.nan)
    pos=(c-lo20)/width.replace(0,np.nan)
    center_cross=((c-mid)*(c.shift()-mid.shift())<0).astype(float).rolling(20,min_periods=20).sum()
    edge_touch=((pos<.15)|(pos>.85)).astype(float).rolling(20,min_periods=20).sum()
    atrp=atr/c.replace(0,np.nan)
    vol_med=atrp.rolling(60,min_periods=40).median()
    volstd=v.rolling(40,min_periods=30).std().replace(0,np.nan)
    q=pd.DataFrame({"available_time":z.available_time.astype("int64")})
    p=tf+"_"
    q[p+"ret1"]=logret
    q[p+"ret4"]=np.log(c/c.shift(4))
    q[p+"atr_pct"]=atrp
    q[p+"rv20"]=logret.rolling(20,min_periods=20).std()*np.sqrt(20)
    q[p+"adx14"]=adx
    q[p+"di_spread"]=plus-minus
    q[p+"eff20"]=eff
    q[p+"range_width_atr"]=width/atr.replace(0,np.nan)
    q[p+"range_pos"]=pos
    q[p+"ema20_slope5"]=(ema20/ema20.shift(5)-1)/5
    q[p+"ema_sep_atr"]=(ema20-ema50)/atr.replace(0,np.nan)
    q[p+"volume_z40"]=(v-v.rolling(40,min_periods=30).mean())/volstd
    q[p+"compression60"]=atrp/vol_med.replace(0,np.nan)
    q[p+"center_cross20"]=center_cross
    q[p+"edge_touch20"]=edge_touch
    q[p+"break_up_atr"]=(c-hi20)/atr.replace(0,np.nan)
    q[p+"break_dn_atr"]=(lo20-c)/atr.replace(0,np.nan)
    q[p+"dist_high20_atr"]=(hi20-c)/atr.replace(0,np.nan)
    q[p+"dist_low20_atr"]=(c-lo20)/atr.replace(0,np.nan)
    if "quote_volume" in z:
        q[p+"quote_vol_log"]=np.log1p(z.quote_volume.clip(lower=0))
    if "taker_buy_base_volume" in z:
        q[p+"taker_buy_ratio"]=z.taker_buy_base_volume/z.volume.replace(0,np.nan)
    return q

def causal_join(sym):
    base=read(sym,"15m")
    if base is None or base.empty:return None,None
    raw=base[["open_time","available_time","open","high","low","close","volume"]].copy()
    raw["ts"]=pd.to_datetime(raw.available_time,unit="ms",utc=True)
    merged=feat(base,"15m")
    # merge_asof on availability time prevents using an unfinished HTF candle.
    for tf in ["1h","4h","1d"]:
        x=read(sym,tf)
        if x is None or x.empty:continue
        f=feat(x,tf).sort_values("available_time")
        merged=pd.merge_asof(merged.sort_values("available_time"),f,on="available_time",direction="backward",allow_exact_matches=True)
    out=pd.concat([raw.reset_index(drop=True),merged.drop(columns=["available_time"]).reset_index(drop=True)],axis=1)
    return out,base

def add_current_state(d):
    adx=d["15m_adx14"]; eff=d["15m_eff20"]; sep=d["15m_ema_sep_atr"].abs()
    br=(d["15m_break_up_atr"]>=.35)|(d["15m_break_dn_atr"]>=.35)
    stable=(adx<22)&(eff<.28)&d["15m_range_width_atr"].between(3,10)&(d["15m_center_cross20"]>=2)
    deterior=(adx.between(18,30))&(eff.between(.20,.42))&(d["15m_edge_touch20"]>=4)&(~br)
    trend=(adx>=25)&(eff>=.32)&(sep>=.35)
    exhaust=(adx>=25)&(d["15m_compression60"]>1.15)&(d["15m_volume_z40"]<0)&(eff<eff.shift(5))
    s=np.full(len(d),"UNCERTAIN",object)
    s[stable.fillna(False).values]="RANGE_STABLE"
    s[deterior.fillna(False).values]="RANGE_DERIORATING"
    s[trend.fillna(False).values]="TREND"
    s[exhaust.fillna(False).values]="EXHAUSTION"
    s[br.fillna(False).values]="BREAKOUT"
    d["state_heuristic"]=s
    return d

def forward_extreme(s,n,kind):
    # strictly future bars t+1..t+n
    rev=s.shift(-1)[::-1]
    if kind=="max": out=rev.rolling(n,min_periods=n).max()[::-1]
    else: out=rev.rolling(n,min_periods=n).min()[::-1]
    return out

def add_labels(d):
    c=d.close.astype(float); h=d.high.astype(float); l=d.low.astype(float)
    atr=(d["15m_atr_pct"]*c).replace(0,np.nan)
    for n,name in [(16,"4h"),(32,"8h"),(96,"24h")]:
        fc=c.shift(-n)
        fh=forward_extreme(h,n,"max"); fl=forward_extreme(l,n,"min")
        d[f"y_ret_{name}_atr"]=(fc-c)/atr
        d[f"y_mfe_{name}_atr"]=(fh-c)/atr
        d[f"y_mae_{name}_atr"]=(c-fl)/atr
    # Current pre-existing 20-bar range boundaries reconstructed from feature distances.
    hi20=c+d["15m_dist_high20_atr"]*atr
    lo20=c-d["15m_dist_low20_atr"]*atr
    fhi=forward_extreme(h,32,"max"); flo=forward_extreme(l,32,"min"); fc=c.shift(-32)
    up_break=(fhi>hi20+.35*atr)&(fc>hi20+.15*atr)
    dn_break=(flo<lo20-.35*atr)&(fc<lo20-.15*atr)
    range_hold=(fhi<=hi20+.20*atr)&(flo>=lo20-.20*atr)&((fc-c).abs()<=.75*atr)
    tr=d["y_ret_8h_atr"]
    trend_up=(tr>=1.5)&(d["y_mae_8h_atr"]<=.8)
    trend_dn=(tr<=-1.5)&(d["y_mfe_8h_atr"]<=.8)
    both=(d["y_mfe_8h_atr"]>=1.25)&(d["y_mae_8h_atr"]>=1.25)&(tr.abs()<1.0)
    y=np.full(len(d),"UNCERTAIN",object)
    y[range_hold.fillna(False).values]="RANGE_HOLD"
    y[both.fillna(False).values]="EXPANSION_CHOP"
    y[up_break.fillna(False).values]="BREAKOUT_UP"
    y[dn_break.fillna(False).values]="BREAKOUT_DOWN"
    y[trend_up.fillna(False).values]="TREND_UP"
    y[trend_dn.fillna(False).values]="TREND_DOWN"
    d["target_path_8h"]=y
    # Seal outer holdout: never expose future outcome labels there.
    mask=d.ts>=OUTER_HOLDOUT
    labelcols=[c for c in d.columns if c.startswith("y_")]+["target_path_8h"]
    d.loc[mask,labelcols]=np.nan
    return d

def split_name(ts):
    if ts< pd.Timestamp("2026-01-01T00:00:00Z"): return "TRAIN"
    if ts< pd.Timestamp("2026-04-01T00:00:00Z"): return "CALIB"
    if ts< OUTER_HOLDOUT: return "TEST"
    return "OUTER_HOLDOUT"

def downcast(d):
    for c in d.select_dtypes("float64").columns:d[c]=pd.to_numeric(d[c],downcast="float")
    for c in d.select_dtypes("int64").columns:
        if c not in ("open_time","available_time"): d[c]=pd.to_numeric(d[c],downcast="integer")
    return d

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"symbols").mkdir(exist_ok=True)
    audits=[]; state_counts=[]; target_counts=[]
    btc_context=None
    # Build BTC context first; only causal features are copied.
    btc,_=causal_join("BTCUSDT")
    if btc is not None:
        btc_context=btc[["available_time","15m_ret4","15m_atr_pct","15m_adx14","15m_eff20","4h_ret4","4h_adx14"]].copy()
        btc_context=btc_context.rename(columns={c:"btc_"+c for c in btc_context.columns if c!="available_time"})
    for i,sym in enumerate(SYMBOLS,1):
        d,_=causal_join(sym)
        if d is None: continue
        if btc_context is not None and sym!="BTCUSDT":
            d=pd.merge_asof(d.sort_values("available_time"),btc_context.sort_values("available_time"),on="available_time",direction="backward")
        elif btc_context is not None:
            for c in btc_context.columns:
                if c!="available_time": d[c]=btc_context[c].values[:len(d)]
        d=add_current_state(d)
        d=add_labels(d)
        d["symbol"]=sym
        d["split"]=[split_name(x) for x in d.ts]
        d["asset_fold"]=zlib.crc32(sym.encode())%5
        feature_cols=[c for c in d.columns if c[0:3] in ("15m","1h_","4h_","1d_","btc")]
        complete=d[feature_cols].notna().mean(axis=1)
        d["feature_coverage"]=complete.astype("float32")
        audits.append({"symbol":sym,"rows":len(d),"start":str(d.ts.min()),"end":str(d.ts.max()),
                       "feature_columns":len(feature_cols),"median_feature_coverage":float(complete.median()),
                       "outer_holdout_rows":int((d["split"]=="OUTER_HOLDOUT").sum())})
        for k,v in d.state_heuristic.value_counts().items():state_counts.append({"symbol":sym,"state":k,"rows":int(v)})
        for k,v in d.loc[d.split!="OUTER_HOLDOUT","target_path_8h"].value_counts().items():target_counts.append({"symbol":sym,"target":k,"rows":int(v)})
        cols=["symbol","ts","open_time","available_time","split","asset_fold","feature_coverage","state_heuristic","target_path_8h"]+feature_cols+[c for c in d.columns if c.startswith("y_")]
        downcast(d[cols]).to_parquet(OUT/"symbols"/f"{sym}.parquet",index=False,compression="zstd")
        print(f"[{i:02d}/{len(SYMBOLS)}] {sym}: {len(d):,} rows",flush=True)
    A=pd.DataFrame(audits); S=pd.DataFrame(state_counts); T=pd.DataFrame(target_counts)
    A.to_csv(OUT/"dataset_audit.csv",index=False); S.to_csv(OUT/"state_counts.csv",index=False); T.to_csv(OUT/"target_counts.csv",index=False)
    summary={
      "symbols":int(len(A)),"rows_15m_decisions":int(A.rows.sum()),"outer_holdout_start":str(OUTER_HOLDOUT),
      "outer_holdout_rows":int(A.outer_holdout_rows.sum()),"feature_columns_median":float(A.feature_columns.median()),
      "median_feature_coverage":float(A.median_feature_coverage.median()),
      "state_totals":S.groupby("state").rows.sum().astype(int).to_dict() if len(S) else {},
      "target_totals_dev_only":T.groupby("target").rows.sum().astype(int).to_dict() if len(T) else {},
      "leakage_policy":"HTF features become available at candle close; merge_asof backward only. Future labels blank for outer holdout.",
      "asset_fold_policy":"crc32(symbol) % 5 for later cross-asset holdout experiments"
    }
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    (OUT/"feature_manifest.json").write_text(json.dumps({
      "base_clock":"15m close","source":"Binance Spot public klines","timeframes":["15m","1h","4h","1d"],
      "outer_holdout_start":"2026-07-01T00:00:00Z","future_label_horizons":["4h","8h","24h"],
      "symbols":SYMBOLS},indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2),flush=True)

if __name__=="__main__": main()
