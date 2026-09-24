#!/usr/bin/env python3
"""R16.23 Independent Edge Factory: satellite risk-budget study.
Frozen R16.19B momentum signal family, tested as a small satellite rather than standalone.
No new signal optimization. Evaluate risk scaling of period returns and strict distribution gates.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path("r16_edge_lab/r16_23_inputs"); OUT=Path("r16_edge_lab/r16_23_edge_factory");OUT.mkdir(parents=True,exist_ok=True)
SEED=16230

def find(name):
 h=list(ROOT.rglob(name))
 if not h: raise FileNotFoundError(name)
 return h[0]
def load(name):
 x=pd.read_csv(find(name))
 for c in ["entry_time","exit_time","ret"]: x[c]=pd.to_numeric(x[c],errors="coerce")
 return x.dropna(subset=["entry_time","ret"]).sort_values("entry_time")
def boot(x,n=4000):
 dt=pd.to_datetime(x.entry_time,unit="ms",utc=True);z=x.copy();z["w"]=(dt-dt.dt.weekday.astype("timedelta64[D]")).dt.floor("D")
 w=z.groupby("w").scaled.sum().to_numpy(float)
 if len(w)<20:return 0.
 rng=np.random.default_rng(SEED);v=np.array([rng.choice(w,len(w),replace=True).mean() for _ in range(n)])
 return float((v>0).mean())
def met(x):
 if x.empty or "scaled" not in x.columns:
  return {"periods":0,"pf":0.0,"bootstrap":0.0,"return":0.0,"dd":0.0,"monthly_mean":0.0,"monthly_median":0.0,"positive_month_rate":0.0,"m10":0,"m20":0,"best":0.0,"worst":0.0,"positive_quarter_rate":0.0,"positive_year_rate":0.0,"yearly":{}}
 r=x.scaled.to_numpy(float);dt=pd.to_datetime(x.entry_time,unit="ms",utc=True);z=x.copy()
 z["y"]=dt.dt.year;z["q"]=dt.dt.to_period("Q").astype(str);z["m"]=dt.dt.to_period("M").astype(str)
 yr=z.groupby("y").scaled.apply(lambda s:(1+s).prod()-1);qr=z.groupby("q").scaled.apply(lambda s:(1+s).prod()-1);mr=z.groupby("m").scaled.apply(lambda s:(1+s).prod()-1)
 eq=np.cumprod(1+r);pk=np.maximum.accumulate(eq);dd=eq/pk-1;gp=r[r>0].sum();gl=-r[r<0].sum()
 return {"periods":len(z),"pf":float(gp/gl) if gl else None,"bootstrap":boot(z),"return":float(eq[-1]-1),"dd":float(-dd.min()),
 "monthly_mean":float(mr.mean()),"monthly_median":float(mr.median()),"positive_month_rate":float((mr>0).mean()),
 "m10":int((mr>=.10).sum()),"m20":int((mr>=.20).sum()),"best":float(mr.max()),"worst":float(mr.min()),
 "positive_quarter_rate":float((qr>0).mean()),"positive_year_rate":float((yr>0).mean()),"yearly":{str(int(k)):float(v) for k,v in yr.items()}}
try:
 B=load("selected_base.csv");S=load("selected_stress.csv")
except FileNotFoundError:
 # R16.19B had no strict standalone pass, so it intentionally wrote no selected streams.
 # Rebuild the highest-ranked frozen candidate from its momentum_map using the original
 # R16.19B implementation; this changes no signal parameter and avoids cherry-picking here.
 mp=pd.read_csv(find("momentum_map.csv"))
 best=mp.iloc[0]
 import importlib.util
 src=Path("r16_edge_lab/run_r16_19b_cross_momentum.py")
 spec=importlib.util.spec_from_file_location("r1619b",src); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
 B=mod.run(int(best["lb"]),int(best["hold"]),int(best["k"]),str(best["regime"]),float(best["minmom"]),mod.BASE)
 S=mod.run(int(best["lb"]),int(best["hold"]),int(best["k"]),str(best["regime"]),float(best["minmom"]),mod.STRESS)
 if B.empty or S.empty:
  raise RuntimeError(f"Frozen candidate produced no trades: base={len(B)} stress={len(S)}. Historical source data required for reconstruction is missing from checkout.")
 print("Rebuilt frozen R16.19B candidate:",best["name"],flush=True)
rows=[];cache={}
for scale in [.10,.15,.20,.25,.30,.40,.50]:
 for cap in [.03,.05,.075,.10]:
  b=B.copy();s=S.copy()
  b["scaled"]=np.clip(b.ret*scale,-cap,cap);s["scaled"]=np.clip(s.ret*scale,-cap,cap)
  mb=met(b);ms=met(s)
  passed=bool(ms["pf"]>=1.15 and ms["bootstrap"]>=.95 and ms["return"]>0 and ms["dd"]<=.20 and ms["worst"]>=-.12 and
              ms["positive_year_rate"]>=.80 and ms["positive_quarter_rate"]>=.60)
  rows.append({"scale":scale,"period_cap":cap,**{f"base_{k}":v for k,v in mb.items()},**{f"stress_{k}":v for k,v in ms.items()},"passes":passed})
  cache[(scale,cap)]=(b,s,mb,ms)
R=pd.DataFrame(rows);R["score"]=R.passes.astype(int)*1000+R.stress_monthly_median*100+R.stress_monthly_mean*30-R.stress_dd*10
R=R.sort_values(["passes","score"],ascending=[False,False]);R.to_csv(OUT/"satellite_grid.csv",index=False)
sel=R.iloc[0];b,s,mb,ms=cache[(float(sel.scale),float(sel.period_cap))]
b.to_csv(OUT/"selected_base.csv",index=False);s.to_csv(OUT/"selected_stress.csv",index=False)
summary={"version":"R16.23","family":"cross-sectional momentum satellite","selected":sel.to_dict(),"selected_base":mb,"selected_stress":ms,
"strict_pass_count":int(R.passes.sum()),"notes":["Signal frozen from R16.19B selected stream.","Satellite sizing only; no signal tuning.","Designed for later correlation/portfolio test with R16.22.","September 2026 untouched."]}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float));print(json.dumps(summary,indent=2,default=float))
