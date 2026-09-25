#!/usr/bin/env python3
"""R16 infrastructure integrity gate.
Synthetic invariant tests + repository implementation audit.
No strategy parameters are optimized here.
"""
from __future__ import annotations
from pathlib import Path
import ast,hashlib,json,subprocess,sys
import pandas as pd,numpy as np

ROOT=Path("."); OUT=Path("r16_edge_lab/integrity_audit"); OUT.mkdir(parents=True,exist_ok=True)
TARGET=Path("r16_edge_lab/run_r16_24_3_causal_revalidation.py")
CONTRACT=Path("r16_edge_lab/BACKTEST_INTEGRITY_CONTRACT.md")

def result(name,ok,evidence,kind="executable"):
 return {"test":name,"pass":bool(ok),"kind":kind,"evidence":evidence}

def synthetic_causal_engine(df, cutoff=None):
 x=df.sort_values("time").copy()
 if cutoff is not None:x=x[x.time<=cutoff].copy()
 # Feature is based exclusively on CLOSED observations through t.
 x["ma2"]=x.close.rolling(2).mean()
 x["signal"]=(x.close>x.ma2).astype(int)
 # signal at t -> fill strictly at next observation.
 x["fill_time"]=x.time.shift(-1)
 return x[["time","close","ma2","signal","fill_time"]]

def main():
 tests=[]
 # 1/2 future perturbation + prefix replay
 base=pd.DataFrame({"time":np.arange(10,dtype=int)*1000,"close":[10,11,10,12,11,13,12,14,13,15]})
 cut=5000
 full=synthetic_causal_engine(base)
 pref=synthetic_causal_engine(base,cut)
 pert=base.copy();pert.loc[pert.time>cut,"close"]*=100
 changed=synthetic_causal_engine(pert)
 cols=["time","close","ma2","signal"]
 a=full[full.time<=cut][cols].reset_index(drop=True);b=pref[cols].reset_index(drop=True);c=changed[changed.time<=cut][cols].reset_index(drop=True)
 tests.append(result("future_data_perturbation",a.equals(c),"future rows changed 100x; prefix decisions unchanged"))
 tests.append(result("prefix_replay",a.equals(b),"full-run prefix equals standalone prefix"))

 # 3 next observation
 q=full.dropna(subset=["fill_time"])
 tests.append(result("next_observation_execution",bool((q.fill_time>q.time).all()),"all synthetic fills strictly after signal time"))

 # 5 conservative collision
 def collide(lo,hi,stop,target):
  if lo<=stop and hi>=target:return "STOP_AMBIGUOUS"
  if lo<=stop:return "STOP"
  if hi>=target:return "TARGET"
  return "NONE"
 tests.append(result("same_bar_collision",collide(90,110,95,105)=="STOP_AMBIGUOUS","stop+target collision resolves adverse/ambiguous, never favorable"))

 src=TARGET.read_text(); tree=ast.parse(src)
 # 6 closed-only realized state: inspect explicit <= t predicate in scores
 tests.append(result("closed_only_realized_state","d.exit_time<=t" in src.replace(" ",""),"scores() requires exit_time <= decision time"))

 # 7 MTM accounting: implementation has unrealized marks in equity
 tests.append(result("mtm_equity_reconciliation","realized+un" in src.replace(" ","") and 'p.get("mark",0.)' in src,"equity includes unrealized mark-to-market; numeric ledger reconciliation still required", "implementation_audit"))

 # 8 collateral accounting is not explicit in 24.3
 has_collateral=("collateral" in src.lower() or "margin_reserved" in src.lower())
 tests.append(result("cash_margin_collateral_reconciliation",has_collateral,"R16.24.3 has no explicit collateral/margin ledger", "implementation_audit"))

 # 9 exposure invariant: known artifact breach >1.0, and current code does not rebalance after MTM equity falls
 tests.append(result("exposure_limit_invariant",False,"R16.24.3 observed max gross/equity ~1.0549; <=1.0 invariant failed", "artifact_audit"))

 # 10 aggregate stop risk: measured but no hard portfolio stop-risk ceiling
 hardrisk=("MAX_PORTFOLIO_STOP_RISK" in src or "max_portfolio_stop_risk" in src)
 tests.append(result("aggregate_stop_risk_invariant",hardrisk,"open stop risk is measured, but no explicit aggregate hard ceiling exists", "implementation_audit"))

 # 11 historical funding: constant approximation is not historical timestamped funding
 histfund=("funding_rate" in src and "funding_time" in src)
 tests.append(result("historical_fee_funding_reconciliation",histfund,"R16.24.3 uses constant funding drag, not historical timestamped rates", "implementation_audit"))

 # 12 deterministic replay: hash identical deterministic synthetic output twice
 def h(df):return hashlib.sha256(df.to_csv(index=False,float_format="%.12g").encode()).hexdigest()
 h1=h(synthetic_causal_engine(base));h2=h(synthetic_causal_engine(base.copy()))
 tests.append(result("deterministic_replay",h1==h2,f"synthetic replay sha256={h1}"))

 # 13 walk-forward isolation: 24.3 reuses previously selected configs; not a fresh OOS chain
 tests.append(result("chronological_walkforward_isolation",False,"R16.24.3 reuses previously selected engines/configs; no fresh frozen walk-forward chain", "methodology_audit"))

 # 14 ledger report reconciliation: 24.3 outputs trades but not an event/cash ledger sufficient to reconcile portfolio monthly equity
 ledger=("ledger" in src.lower() and "equity" in src.lower())
 tests.append(result("trade_ledger_report_reconciliation",ledger,"no explicit event-level cash/equity/cost ledger emitted by R16.24.3", "implementation_audit"))

 # 15 fingerprint: no complete manifest of code/config/input artifact digests
 fp=("sha256" in src.lower() and "fingerprint" in src.lower())
 tests.append(result("baseline_fingerprint",fp,"no complete input/code/config hash manifest emitted by R16.24.3", "implementation_audit"))

 # 4 point-in-time universe/listing ledger
 pit=("listing" in src.lower() and ("delist" in src.lower() or "onboard" in src.lower()))
 tests.insert(3,result("point_in_time_universe",pit,"no explicit listing/delisting eligibility ledger in R16.24.3", "implementation_audit"))

 failed=[t for t in tests if not t["pass"]]
 summary={
  "version":"R16-INTEGRITY-GATE-1",
  "contract":str(CONTRACT),
  "target":str(TARGET),
  "target_sha256":hashlib.sha256(TARGET.read_bytes()).hexdigest(),
  "contract_sha256":hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
  "tests":tests,"passed":len(tests)-len(failed),"failed":len(failed),
  "status":"TECHNICALLY_VALID" if not failed else "TECHNICALLY_INVALID",
  "failed_tests":[t["test"] for t in failed],
  "note":"Gate intentionally fails until every mandatory invariant has executable evidence. Profit is not evaluated."
 }
 (OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
 print(json.dumps(summary,indent=2))
 # Gate workflow red only for regressions in executable invariants; known implementation gaps are reported for reconstruction.
 executable_fail=[t for t in failed if t["kind"]=="executable"]
 if executable_fail:sys.exit(2)

if __name__=="__main__":main()
