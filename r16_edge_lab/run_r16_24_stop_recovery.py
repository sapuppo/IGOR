#!/usr/bin/env python3
"""R16.24 Stop & Recovery Map.
Frozen entries from R16.22 engines. No entry tuning.
Path study: MAE/MFE and recovery after adverse excursions; then stop-only/time-exit
counterfactuals for fixed and volatility-adaptive stops. This is a diagnostic:
target logic is intentionally excluded from the counterfactual so widening a stop
cannot be falsely credited for changing another exit rule.
Period 2021-01-01..2026-06-30. September 2026 untouched.
"""
from pathlib import Path
import json, numpy as np, pandas as pd

ROOT=Path("r16_edge_lab/r16_24_inputs"); OUT=Path("r16_edge_lab/r16_24_stop_recovery"); OUT.mkdir(parents=True,exist_ok=True)
START_CAP=10000.; SEED=16240
ENG={
 "CORE":{"src":"core","file":"base_core_trades.csv.gz","iv":"4h","bar_ms":4*3600000,"hold":30},
 "REV1H":{"src":"rev1h","file":"selected_long_base.csv.gz","iv":"1h","bar_ms":3600000,"hold":24},
 "REV15M":{"src":"rev15m","file":"selected_long_base.csv.gz","iv":"15m","bar_ms":15*60000,"hold":24},
}
HIST={"4h":[ROOT/"pre2024",ROOT/"post"],"1h":[ROOT/"pre2024",ROOT/"post"],"15m":[ROOT/"pre2024_15m",ROOT/"post"]}
COSTS={"base":.0032,"stress":.0042}
TH=[.02,.03,.04,.05,.07]
FIXED=[.02,.03,.04,.05,.07]
ATR_MULT=[1.25,1.5,2.,2.5,3.]

def ff(root,name):
 h=list(root.rglob(name))
 if not h: raise FileNotFoundError(f"{root}: {name}")
 return h[0]

def load_entries(cfg):
 x=pd.read_csv(ff(ROOT/cfg["src"],cfg["file"]))
 for c in ["entry_time","exit_time","stop_pct"]: x[c]=pd.to_numeric(x[c],errors="coerce")
 return x.dropna(subset=["entry_time","symbol"]).sort_values("entry_time")

def load_px(sym,iv):
 fs=[]
 for root in HIST[iv]:
  p=root/iv/f"{sym}.csv.gz"
  if p.exists(): fs.append(pd.read_csv(p,usecols=["open_time","open","high","low","close"]))
 if not fs:return pd.DataFrame()
 x=pd.concat(fs,ignore_index=True)
 for c in ["open_time","open","high","low","close"]:x[c]=pd.to_numeric(x[c],errors="coerce")
 x=x.dropna().drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
 pc=x.close.shift(); tr=pd.concat([x.high-x.low,(x.high-pc).abs(),(x.low-pc).abs()],axis=1).max(axis=1)
 x["atr"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
 return x

def path_rows(eng,cfg,entries):
 cache={}; rows=[]
 for r in entries.itertuples(index=False):
  sym=str(r.symbol)
  if sym not in cache: cache[sym]=load_px(sym,cfg["iv"])
  z=cache[sym]
  if z.empty:continue
  a=z.open_time.to_numpy(np.int64); ei=int(np.searchsorted(a,int(r.entry_time)))
  if ei>=len(z) or int(a[ei])!=int(r.entry_time):continue
  end=min(ei+cfg["hold"]-1,len(z)-1); w=z.iloc[ei:end+1]
  entry=float(z.open.iloc[ei]); atr=float(z.atr.iloc[max(0,ei-1)])
  if not np.isfinite(entry) or entry<=0:continue
  lows=w.low.to_numpy(float); highs=w.high.to_numpy(float); closes=w.close.to_numpy(float)
  adverse=lows/entry-1; favorable=highs/entry-1
  row={"engine":eng,"symbol":sym,"entry_time":int(r.entry_time),"entry":entry,
       "atr_pct":atr/entry if np.isfinite(atr) else np.nan,
       "mae":float(adverse.min()),"mfe":float(favorable.max()),"time_ret":float(closes[-1]/entry-1)}
  for t in TH:
   hit=np.flatnonzero(adverse<=-t)
   if len(hit):
    j=int(hit[0]); future_hi=float(np.max(highs[j:])/entry-1); future_close=float(closes[-1]/entry-1)
    row[f"hit_{int(t*100)}"]=1; row[f"recover0_{int(t*100)}"]=int(future_hi>=0)
    row[f"recover1_{int(t*100)}"]=int(future_hi>=.01); row[f"finalpos_{int(t*100)}"]=int(future_close>0)
   else:
    row[f"hit_{int(t*100)}"]=0; row[f"recover0_{int(t*100)}"]=0; row[f"recover1_{int(t*100)}"]=0; row[f"finalpos_{int(t*100)}"]=0
  # Counterfactual stop-only/time exit, same frozen entry and horizon.
  for t in FIXED:
   hit=np.flatnonzero(adverse<=-t); gross=-t if len(hit) else float(closes[-1]/entry-1)
   row[f"fixed_{int(t*100)}"]=gross
  if np.isfinite(row["atr_pct"]) and row["atr_pct"]>0:
   for m in ATR_MULT:
    sp=m*row["atr_pct"]; hit=np.flatnonzero(adverse<=-sp); row[f"atr_{str(m).replace('.','p')}"]=-sp if len(hit) else float(closes[-1]/entry-1)
  rows.append(row)
 return pd.DataFrame(rows)

def pf(r):
 r=np.asarray(r,float); gp=r[r>0].sum(); gl=-r[r<0].sum(); return float(gp/gl) if gl else None
def metrics(x,col,cost):
 z=x[["entry_time",col]].dropna().copy(); z["ret"]=z[col]-cost
 dt=pd.to_datetime(z.entry_time,unit="ms",utc=True);z["m"]=dt.dt.to_period("M").astype(str);z["y"]=dt.dt.year
 r=z.ret.to_numpy(); mr=z.groupby("m").ret.apply(lambda s:(1+s).prod()-1);yr=z.groupby("y").ret.apply(lambda s:(1+s).prod()-1)
 eq=np.cumprod(1+r); pk=np.maximum.accumulate(eq); dd=eq/pk-1
 return {"trades":len(z),"return":float(eq[-1]-1),"pf":pf(r),"win_rate":float((r>0).mean()),"avg":float(r.mean()),
 "dd":float(-dd.min()),"monthly_mean":float(mr.mean()),"monthly_median":float(mr.median()),"positive_month":float((mr>0).mean()),
 "worst_month":float(mr.min()),"yearly":{str(int(k)):float(v) for k,v in yr.items()}}

allp=[]; recovery=[]; grids=[]
for eng,cfg in ENG.items():
 e=load_entries(cfg); p=path_rows(eng,cfg,e); p.to_csv(OUT/f"{eng.lower()}_paths.csv.gz",index=False,compression="gzip"); allp.append(p)
 rec={"engine":eng,"trades":len(p),"mae_median":float(p.mae.median()),"mae_p75":float(p.mae.quantile(.25)),
      "mae_p90":float(p.mae.quantile(.10)),"mfe_median":float(p.mfe.median())}
 for t in TH:
  n=int(p[f"hit_{int(t*100)}"].sum());rec[f"hit_{int(t*100)}"]=n
  rec[f"recover0_rate_after_hit_{int(t*100)}"]=float(p.loc[p[f"hit_{int(t*100)}"].eq(1),f"recover0_{int(t*100)}"].mean()) if n else None
  rec[f"recover1_rate_after_hit_{int(t*100)}"]=float(p.loc[p[f"hit_{int(t*100)}"].eq(1),f"recover1_{int(t*100)}"].mean()) if n else None
  rec[f"final_positive_rate_after_hit_{int(t*100)}"]=float(p.loc[p[f"hit_{int(t*100)}"].eq(1),f"finalpos_{int(t*100)}"].mean()) if n else None
 recovery.append(rec)
 for scenario,cost in COSTS.items():
  for t in FIXED:
   m=metrics(p,f"fixed_{int(t*100)}",cost);grids.append({"engine":eng,"scenario":scenario,"stop_type":"fixed","stop":t,**m})
  for a in ATR_MULT:
   col=f"atr_{str(a).replace('.','p')}";m=metrics(p,col,cost);grids.append({"engine":eng,"scenario":scenario,"stop_type":"atr","stop":a,**m})

P=pd.concat(allp,ignore_index=True); R=pd.DataFrame(recovery); G=pd.DataFrame(grids)
R.to_csv(OUT/"recovery_map.csv",index=False);G.to_csv(OUT/"stop_grid.csv",index=False)
# Selection is diagnostic only: stress PF/median/DD balance, separately by engine.
sel={}
for eng in ENG:
 z=G[(G.engine==eng)&(G.scenario=="stress")].copy()
 z["score"]=z.pf.fillna(0)*2+z.monthly_median*20+z.monthly_mean*10-z.dd*2
 q=z.sort_values("score",ascending=False).iloc[0];sel[eng]=q.to_dict()
summary={"version":"R16.24","study":"Stop & Recovery Map","period":"2021-01-01..2026-06-30",
 "recovery":R.to_dict("records"),"diagnostic_best_stress":sel,
 "notes":["Frozen entries from the current three-engine stack; no entry tuning.",
 "MAE/MFE use full post-entry path over each engine horizon.",
 "Counterfactual grid is stop-only plus time exit; it intentionally does not claim to replace the production target logic.",
 "Fixed stops: 2/3/4/5/7%. ATR stops: 1.25/1.5/2/2.5/3 ATR.",
 "Base/stress include round-trip cost assumptions 0.32%/0.42%.","September 2026 untouched."]}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float),flush=True)
