#!/usr/bin/env python3
"""R15.7.1 - Economic Failure Audit.

Pure diagnostic stage. Does NOT tune or alter the R15.7 strategy.
Audits executed TEST trades from R15.7 against raw 15m candles to explain losses.

Questions:
- which event types / symbols / directions lose money?
- is confidence monotonic with realized PnL?
- how much MFE existed before stops/timeouts?
- did trades move favorably first then reverse?
- are stops too tight relative to realized path?
- are there subsets with positive expectancy without parameter optimization?
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd

BT=Path("r15_regime_lab/backtest_r15_7")
RAW=Path("r15_regime_lab/history/15m")
OUT=Path("r15_regime_lab/audit_r15_7_1")
OUT.mkdir(parents=True,exist_ok=True)

FILES=[
 "ai_directional_base_trades.csv",
 "ai_long_only_spot_trades.csv",
 "ai_directional_stress_trades.csv",
 "ai_long_only_spot_stress_trades.csv",
]
BAR_MS=900_000

CACHE={}
def raw(sym):
    if sym not in CACHE:
        p=RAW/f"{sym}.csv.gz"
        x=pd.read_csv(p,usecols=["open_time","open","high","low","close","volume"])
        for c in x.columns:
            x[c]=pd.to_numeric(x[c],errors="coerce")
        CACHE[sym]=x.dropna().sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    return CACHE[sym]

def path_metrics(row):
    x=raw(row.symbol)
    ot=x.open_time.to_numpy()
    a=np.searchsorted(ot,int(row.entry_time))
    b=np.searchsorted(ot,int(row.exit_time-BAR_MS))
    if a>=len(x) or b>=len(x) or a>b:return {}
    w=x.iloc[a:b+1]
    direction=int(row.direction)
    entry=float(row.entry)
    atr=float(row.atr_abs)
    if atr<=0:return {}
    if direction>0:
        favorable=(w.high-entry)/atr
        adverse=(entry-w.low)/atr
        close_path=(w.close-entry)/atr
    else:
        favorable=(entry-w.low)/atr
        adverse=(w.high-entry)/atr
        close_path=(entry-w.close)/atr
    fav=np.asarray(favorable,float); adv=np.asarray(adverse,float); cp=np.asarray(close_path,float)
    mfe=float(np.nanmax(fav)); mae=float(np.nanmax(adv))
    i_mfe=int(np.nanargmax(fav)); i_mae=int(np.nanargmax(adv))
    # favorable excursion before the bar where the trade exits
    mfe_before_exit=float(np.nanmax(fav[:-1])) if len(fav)>1 else 0.0
    mae_before_exit=float(np.nanmax(adv[:-1])) if len(adv)>1 else 0.0
    bars=len(w)
    first_pos=int(np.argmax(cp>0)) if np.any(cp>0) else -1
    first_half_atr=int(np.argmax(fav>=0.5)) if np.any(fav>=0.5) else -1
    first_one_atr=int(np.argmax(fav>=1.0)) if np.any(fav>=1.0) else -1
    # max favorable then final result indicates giveback
    exit_atr=float(cp[-1])
    giveback=max(0.0,mfe-exit_atr)
    return {
      "bars_held":bars,
      "mfe_atr":mfe,
      "mae_atr":mae,
      "mfe_before_exit_atr":mfe_before_exit,
      "mae_before_exit_atr":mae_before_exit,
      "mfe_bar":i_mfe,
      "mae_bar":i_mae,
      "exit_atr":exit_atr,
      "giveback_atr":giveback,
      "ever_positive":bool(np.any(cp>0)),
      "hit_0_5_atr_before_exit":bool(np.any(fav[:-1]>=0.5)) if len(fav)>1 else False,
      "hit_1_0_atr_before_exit":bool(np.any(fav[:-1]>=1.0)) if len(fav)>1 else False,
      "first_positive_bar":first_pos,
      "first_0_5_atr_bar":first_half_atr,
      "first_1_0_atr_bar":first_one_atr,
      "close_path_vol_atr":float(np.nanstd(cp)) if len(cp)>1 else 0.0
    }

def pf(s):
    s=np.asarray(s,float)
    gp=s[s>0].sum(); gl=-s[s<0].sum()
    return float(gp/gl) if gl>0 else None

def stats(g):
    r=g.net_pct.astype(float)
    return pd.Series({
      "trades":len(g),
      "win_rate":float((r>0).mean()),
      "avg_net_pct":float(r.mean()),
      "median_net_pct":float(r.median()),
      "profit_factor":pf(r),
      "avg_mfe_atr":float(g.mfe_atr.mean()),
      "median_mfe_atr":float(g.mfe_atr.median()),
      "avg_mae_atr":float(g.mae_atr.mean()),
      "median_mae_atr":float(g.mae_atr.median()),
      "avg_giveback_atr":float(g.giveback_atr.mean()),
      "ever_positive_rate":float(g.ever_positive.mean()),
      "hit_0_5_before_exit_rate":float(g.hit_0_5_atr_before_exit.mean()),
      "hit_1_0_before_exit_rate":float(g.hit_1_0_atr_before_exit.mean()),
      "target_rate":float(g.exit_reason.eq("TARGET").mean()),
      "stop_rate":float(g.exit_reason.str.startswith("STOP").mean()),
      "time_rate":float(g.exit_reason.eq("TIME").mean()),
    })

def audit_file(fn):
    p=BT/fn
    if not p.exists():return None
    d=pd.read_csv(p)
    paths=[]
    for i,row in d.iterrows():
        m=path_metrics(row)
        paths.append(m)
    P=pd.DataFrame(paths)
    d=pd.concat([d.reset_index(drop=True),P.reset_index(drop=True)],axis=1)
    name=fn.replace("_trades.csv","")
    d.to_parquet(OUT/f"{name}_audited.parquet",index=False,compression="zstd")
    d.to_csv(OUT/f"{name}_audited.csv",index=False)

    # Group audits
    group_specs={
      "event_type":["event_type"],
      "symbol":["symbol"],
      "direction":["direction"],
      "exit_reason":["exit_reason"],
      "event_direction":["event_type","direction"],
    }
    for suf,cols in group_specs.items():
        g=d.groupby(cols,dropna=False).apply(stats,include_groups=False).reset_index()
        g.sort_values(["profit_factor","avg_net_pct"],ascending=False).to_csv(OUT/f"{name}_by_{suf}.csv",index=False)

    # Confidence deciles: should be monotonic if model confidence is economically useful.
    try:
        d["p_follow_decile"]=pd.qcut(d.p_follow,10,labels=False,duplicates="drop")
        d.groupby("p_follow_decile").apply(stats,include_groups=False).reset_index().to_csv(OUT/f"{name}_by_confidence_decile.csv",index=False)
    except Exception:
        pass

    # Entry timing / time-of-day
    ts=pd.to_datetime(d.entry_time,unit="ms",utc=True)
    d["hour_utc"]=ts.dt.hour
    d["weekday"]=ts.dt.day_name()
    d.groupby("hour_utc").apply(stats,include_groups=False).reset_index().to_csv(OUT/f"{name}_by_hour_utc.csv",index=False)
    d.groupby("weekday").apply(stats,include_groups=False).reset_index().to_csv(OUT/f"{name}_by_weekday.csv",index=False)

    # Diagnostic buckets that do NOT optimize exits.
    d["mfe_bucket"]=pd.cut(d.mfe_atr,[-np.inf,0,.5,1,1.5,2,3,np.inf],
                           labels=["<=0","0-.5",".5-1","1-1.5","1.5-2","2-3",">3"])
    d["mae_bucket"]=pd.cut(d.mae_atr,[-np.inf,.5,1,1.25,1.5,2,3,np.inf],
                           labels=["<=.5",".5-1","1-1.25","1.25-1.5","1.5-2","2-3",">3"])
    d.groupby("mfe_bucket",observed=True).apply(stats,include_groups=False).reset_index().to_csv(OUT/f"{name}_by_mfe_bucket.csv",index=False)
    d.groupby("mae_bucket",observed=True).apply(stats,include_groups=False).reset_index().to_csv(OUT/f"{name}_by_mae_bucket.csv",index=False)

    losers=d[d.net_pct<=0].copy()
    winners=d[d.net_pct>0].copy()
    stop=d[d.exit_reason.str.startswith("STOP")].copy()
    time=d[d.exit_reason.eq("TIME")].copy()

    summary={
      "scenario":name,
      "overall":stats(d).to_dict(),
      "losers":{
        "n":int(len(losers)),
        "ever_positive_before_exit_rate":float(losers.ever_positive.mean()) if len(losers) else None,
        "hit_0_5_atr_before_exit_rate":float(losers.hit_0_5_atr_before_exit.mean()) if len(losers) else None,
        "hit_1_0_atr_before_exit_rate":float(losers.hit_1_0_atr_before_exit.mean()) if len(losers) else None,
        "median_mfe_atr":float(losers.mfe_atr.median()) if len(losers) else None,
        "median_mae_atr":float(losers.mae_atr.median()) if len(losers) else None,
        "median_giveback_atr":float(losers.giveback_atr.median()) if len(losers) else None,
      },
      "stops":{
        "n":int(len(stop)),
        "ever_positive_rate":float(stop.ever_positive.mean()) if len(stop) else None,
        "hit_0_5_before_stop_rate":float(stop.hit_0_5_atr_before_exit.mean()) if len(stop) else None,
        "hit_1_0_before_stop_rate":float(stop.hit_1_0_atr_before_exit.mean()) if len(stop) else None,
        "median_mfe_before_stop_atr":float(stop.mfe_before_exit_atr.median()) if len(stop) else None,
        "median_bars_held":float(stop.bars_held.median()) if len(stop) else None,
      },
      "timeouts":{
        "n":int(len(time)),
        "positive_rate":float((time.net_pct>0).mean()) if len(time) else None,
        "median_mfe_atr":float(time.mfe_atr.median()) if len(time) else None,
        "median_giveback_atr":float(time.giveback_atr.median()) if len(time) else None,
      }
    }
    return d,summary

summaries={}
main=None
for fn in FILES:
    res=audit_file(fn)
    if res is None:continue
    d,s=res
    summaries[s["scenario"]]=s
    if s["scenario"]=="ai_directional_base":main=d

# Focused root-cause report on main AI directional test.
root={}
if main is not None:
    # Long/short asymmetry
    ds=main.groupby("direction").apply(stats,include_groups=False).reset_index()
    root["direction"]=ds.to_dict("records")

    # Best/worst descriptive groups with >=10 trades. This is DIAGNOSTIC, not a strategy recommendation.
    ge=main.groupby("event_type").apply(stats,include_groups=False).reset_index()
    ge10=ge[ge.trades>=10].copy()
    root["event_types_descriptive"]=ge10.sort_values("avg_net_pct",ascending=False).to_dict("records")

    gs=main.groupby("symbol").apply(stats,include_groups=False).reset_index()
    gs10=gs[gs.trades>=10].copy()
    root["symbols_descriptive"]=gs10.sort_values("avg_net_pct",ascending=False).to_dict("records")

    # Confidence relationship
    try:
        q=main.groupby("p_follow_decile").apply(stats,include_groups=False).reset_index()
        root["confidence_deciles"]=q.to_dict("records")
        root["confidence_net_spearman"]=float(main[["p_follow","net_pct"]].corr(method="spearman").iloc[0,1])
    except Exception:
        root["confidence_net_spearman"]=None

    # Failure pattern taxonomy
    stop=main[main.exit_reason.str.startswith("STOP")]
    root["failure_patterns"]={
      "stop_after_never_positive":int((~stop.ever_positive).sum()),
      "stop_after_positive":int(stop.ever_positive.sum()),
      "stop_after_0_5ATR_favorable":int(stop.hit_0_5_atr_before_exit.sum()),
      "stop_after_1ATR_favorable":int(stop.hit_1_0_atr_before_exit.sum()),
      "time_exits":int(main.exit_reason.eq("TIME").sum()),
      "targets":int(main.exit_reason.eq("TARGET").sum()),
      "ambiguous_stop_same_bar":int(main.exit_reason.eq("STOP_AMBIGUOUS").sum())
    }

summary={
  "version":"R15.7.1",
  "purpose":"economic failure audit only; no strategy tuning",
  "scenarios":summaries,
  "root_cause_main":root,
  "outer_holdout_opened":False,
  "notes":[
    "No strategy parameters were changed.",
    "All audit conclusions are descriptive on the already-used TEST period.",
    "Any subgroup that looks profitable here must be revalidated on a future calibration/validation design before use.",
    "Outer holdout remains sealed."
  ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
