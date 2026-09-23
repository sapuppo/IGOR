#!/usr/bin/env python3
"""R15.1 - causal market-regime data audit and feature builder.

Reads existing OHLCV CSVs (currently r12_2_data = 4h), audits data quality,
builds causal structural features, and emits provisional regime states.
No trading/backtest logic is changed by this program.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

REGIMES=["RANGE_STABLE","RANGE_DERIORATING","BREAKOUT","TREND","EXHAUSTION","UNCERTAIN"]

def infer_interval_ms(t):
    d=pd.Series(t).sort_values().diff().dropna()
    return int(d.median()) if len(d) else 0

def load_csv(p:Path):
    x=pd.read_csv(p)
    need={"open_time","open","high","low","close","volume"}
    if not need.issubset(x.columns): raise ValueError(f"{p}: missing {need-set(x.columns)}")
    x=x.copy()
    x["open_time"]=pd.to_numeric(x["open_time"],errors="coerce")
    for c in ["open","high","low","close","volume"]:
        x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna(subset=["open_time","open","high","low","close"]).sort_values("open_time")
    x["ts"]=pd.to_datetime(x.open_time,unit="ms",utc=True)
    return x

def audit(symbol,x):
    iv=infer_interval_ms(x.open_time)
    dif=x.open_time.sort_values().diff()
    gaps=int((dif>iv*1.5).sum()) if iv else 0
    missing=int(np.maximum(np.rint(dif.dropna()/iv)-1,0).sum()) if iv else 0
    bad=((x.high<x[["open","close","low"]].max(axis=1)) | (x.low>x[["open","close","high"]].min(axis=1)))
    return dict(symbol=symbol,rows=len(x),start=str(x.ts.min()),end=str(x.ts.max()),
        interval_ms=iv,interval_hours=iv/3_600_000 if iv else None,
        duplicates=int(x.open_time.duplicated().sum()),gap_events=gaps,estimated_missing=missing,
        bad_ohlc=int(bad.sum()),zero_volume=int((x.volume<=0).sum()))

def rma(s,n):
    return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def features(x):
    z=x.copy().set_index("ts")
    c,h,l,o,v=z.close,z.high,z.low,z.open,z.volume
    prev=c.shift(1)
    tr=pd.concat([(h-l),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff(); dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.0),14)/atr
    minus=100*rma(dn.where((dn>up)&(dn>0),0.0),14)/atr
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    adx=rma(dx,14)
    ret=np.log(c/c.shift(1))
    rv=ret.rolling(20).std()*np.sqrt(20)
    hi20=h.shift(1).rolling(20).max(); lo20=l.shift(1).rolling(20).min()
    mid=(hi20+lo20)/2; width=(hi20-lo20)
    atrp=atr/c
    width_atr=width/atr.replace(0,np.nan)
    pos=(c-lo20)/width.replace(0,np.nan)
    eff20=(c-c.shift(20)).abs()/c.diff().abs().rolling(20).sum().replace(0,np.nan)
    ema20=c.ewm(span=20,adjust=False).mean(); ema50=c.ewm(span=50,adjust=False).mean()
    slope20=(ema20/ema20.shift(5)-1)/5
    volz=(v-v.rolling(40).mean())/v.rolling(40).std().replace(0,np.nan)
    compression=atrp/atrp.rolling(60).median()
    cross=((c-mid)*(c.shift(1)-mid.shift(1))<0).astype(float).rolling(20).sum()
    near_edge=((pos<.15)|(pos>.85)).astype(float).rolling(20).sum()
    break_up=(c-hi20)/atr.replace(0,np.nan); break_dn=(lo20-c)/atr.replace(0,np.nan)
    out=pd.DataFrame(index=z.index)
    out["close"]=c; out["ret1"]=ret; out["atr_pct"]=atrp; out["rv20"]=rv
    out["adx14"]=adx; out["di_spread"]=(plus-minus)
    out["range_width_atr"]=width_atr; out["range_pos"]=pos
    out["efficiency20"]=eff20; out["ema20_slope5"]=slope20
    out["ema_sep_atr"]=(ema20-ema50)/atr.replace(0,np.nan)
    out["volume_z40"]=volz; out["compression60"]=compression
    out["center_cross20"]=cross; out["edge_touch20"]=near_edge
    out["break_up_atr"]=break_up; out["break_dn_atr"]=break_dn
    # causal provisional state: every input above uses current/past data only.
    trend=(adx>=25)&(eff20>=.32)&(out.ema_sep_atr.abs()>=.35)
    breakout=((break_up>=.35)|(break_dn>=.35))&(out.volume_z40>=0)
    stable=(adx<22)&(eff20<.28)&(width_atr.between(3,10))&(cross>=2)
    deteriorating=(adx.between(18,30))&(eff20.between(.20,.42))&(near_edge>=4)&(~breakout)
    exhaustion=(adx>=25)&(compression>1.15)&(out.volume_z40<0)&(eff20<eff20.shift(5))
    state=np.full(len(out),"UNCERTAIN",dtype=object)
    # precedence matters
    state[stable.fillna(False).values]="RANGE_STABLE"
    state[deteriorating.fillna(False).values]="RANGE_DERIORATING"
    state[trend.fillna(False).values]="TREND"
    state[exhaustion.fillna(False).values]="EXHAUSTION"
    state[breakout.fillna(False).values]="BREAKOUT"
    out["regime_provisional"]=state
    return out.reset_index()

def transition_table(f):
    a=f.regime_provisional
    q=pd.DataFrame({"from":a.shift(1),"to":a}).dropna()
    q=q[q["from"]!=q["to"]]
    return q.value_counts().rename("count").reset_index()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",default="r12_2_data")
    ap.add_argument("--output",default="r15_regime_lab/output")
    args=ap.parse_args()
    inp=Path(args.input); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    audits=[]; regimes=[]; trans=[]
    for p in sorted(inp.glob("*.csv")):
        sym=p.stem.upper(); x=load_csv(p); audits.append(audit(sym,x))
        f=features(x); f.insert(0,"symbol",sym)
        f.to_csv(out/f"{sym}_features.csv",index=False)
        vc=f.regime_provisional.value_counts()
        for k,n in vc.items(): regimes.append({"symbol":sym,"regime":k,"bars":int(n)})
        t=transition_table(f); t.insert(0,"symbol",sym); trans.append(t)
    A=pd.DataFrame(audits); R=pd.DataFrame(regimes)
    T=pd.concat(trans,ignore_index=True) if trans else pd.DataFrame()
    A.to_csv(out/"data_audit.csv",index=False); R.to_csv(out/"regime_counts.csv",index=False)
    T.to_csv(out/"regime_transitions.csv",index=False)
    summary={"symbols":len(A),"rows":int(A.rows.sum()) if len(A) else 0,
      "interval_hours":sorted(A.interval_hours.dropna().unique().tolist()) if len(A) else [],
      "gap_events":int(A.gap_events.sum()) if len(A) else 0,
      "estimated_missing":int(A.estimated_missing.sum()) if len(A) else 0,
      "bad_ohlc":int(A.bad_ohlc.sum()) if len(A) else 0,
      "duplicates":int(A.duplicates.sum()) if len(A) else 0,
      "regime_totals":R.groupby("regime").bars.sum().astype(int).to_dict() if len(R) else {}}
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))

if __name__=="__main__": main()
