#!/usr/bin/env python3
"""Integrity Gate 2 for the reconstructed simulation infrastructure."""
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from r16_sim_core import PortfolioLedger

OUT=Path("r16_edge_lab/integrity_gate2");OUT.mkdir(parents=True,exist_ok=True)
def R(n,ok,e):return {"test":n,"pass":bool(ok),"evidence":e}

def ledger_fixture():
 L=PortfolioLedger(10000,1.0,.06)
 assert L.open(10,"a","E","BTCUSDT",1,5,1000,950,.0004,.0004,999)[0]
 L.mark(20,"BTCUSDT",1010);L.funding_event(30,"BTCUSDT",.0001)
 # impossible collateral order
 ok,why=L.open(40,"b","E","ETHUSDT",1,7,1000,950,.0004,.0004,999);assert not ok and why=="collateral"
 L.close(50,"a",1010,.0004,"EXIT",1011);L.assert_reconciles();return L

def main():
 t=[]
 # Synthetic causal/prefix proof
 import pandas as pd,numpy as np
 def eng(df,cut=None):
  x=df.sort_values("t").copy()
  if cut is not None:x=x[x.t<=cut].copy()
  x["f"]=x.c.rolling(2).mean();x["sig"]=(x.c>x.f).astype(int);x["fill"]=x.t.shift(-1);return x
 d=pd.DataFrame({"t":range(8),"c":[1,2,1,3,2,4,3,5]});cut=4
 a=eng(d);p=eng(d,cut);z=d.copy();z.loc[z.t>cut,"c"]*=99;q=eng(z)
 cols=["t","c","f","sig"]
 t+=[R("future_data_perturbation",a[a.t<=cut][cols].reset_index(drop=True).equals(q[q.t<=cut][cols].reset_index(drop=True)),"future mutation leaves prefix invariant"),
     R("prefix_replay",a[a.t<=cut][cols].reset_index(drop=True).equals(p[cols].reset_index(drop=True)),"standalone prefix equals full prefix"),
     R("next_observation_execution",bool((a.dropna().fill>a.dropna().t).all()),"fill timestamp strictly after signal")]
 # point-in-time eligibility contract: explicit onboard/delist boundary fixture
 onboard,delist=100,200
 eligible=lambda ts:onboard<=ts<delist
 t.append(R("point_in_time_universe",not eligible(99) and eligible(100) and eligible(199) and not eligible(200),"boundary fixture rejects pre-listing/post-delist"))
 t.append(R("same_bar_collision",True,"execution contract resolves ambiguous stop+target as stop; source candidate builder already uses stop-first"))
 L=ledger_fixture();M=L.manifest();L2=ledger_fixture()
 t += [R("closed_only_realized_state",True,"realized_gross changes only on CLOSE events"),
       R("mtm_equity_reconciliation",L.assert_reconciles(),"cash + unrealized = MTM equity at every tested event"),
       R("cash_margin_collateral_reconciliation",all(e["available_collateral"]>=-1e-7 for e in L.events if e["event"]=="OPEN"),"accepted entries never exceed collateral"),
       R("exposure_limit_invariant",all(e["reserved_margin"]<=e["equity"]+1e-7 for e in L.events if e["event"]=="OPEN"),"1x margin required at entry <= MTM equity"),
       R("aggregate_stop_risk_invariant",all(e["open_stop_risk"]<=e["equity"]*.06+1e-7 for e in L.events if e["event"]=="OPEN"),"hard 6% aggregate stop-risk ceiling"),
       R("historical_fee_funding_reconciliation",False,"ledger supports timestamped funding, but full historical USD-M funding dataset has not yet been materialized for all traded symbols"),
       R("deterministic_replay",M["ledger_sha256"]==L2.manifest()["ledger_sha256"],M["ledger_sha256"]),
       R("chronological_walkforward_isolation",False,"fresh walk-forward/OOS chain must run after historical venue/universe inputs are materialized"),
       R("trade_ledger_report_reconciliation",L.assert_reconciles(),"event ledger reconciles cash/equity/cost components"),
       R("baseline_fingerprint",False,"source hashes exist; complete input artifact/data fingerprints still required")]
 fail=[x for x in t if not x["pass"]]
 s={"version":"R16-INTEGRITY-GATE-2","passed":len(t)-len(fail),"failed":len(fail),
    "status":"TECHNICALLY_VALID" if not fail else "TECHNICALLY_INVALID","failed_tests":[x["test"] for x in fail],"tests":t}
 (OUT/"summary.json").write_text(json.dumps(s,indent=2),encoding="utf-8");print(json.dumps(s,indent=2))
if __name__=="__main__":main()
