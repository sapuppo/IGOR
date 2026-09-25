#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from r16_sim_core import PortfolioLedger

OUT=Path("r16_edge_lab/integrity_core2");OUT.mkdir(parents=True,exist_ok=True)

def scenario():
 L=PortfolioLedger(10000,leverage=1.0,max_stop_risk_fraction=.06)
 # 60% long; entry commission is included in collateral check.
 ok,_=L.open(1000,"p1","TEST","BTCUSDT",1,6,1000,950,.0004,.0004,1000);assert ok
 L.mark(2000,"BTCUSDT",1020)
 # Second order is rejected if it exceeds remaining collateral.
 ok,why=L.open(3000,"p2","TEST","ETHUSDT",1,5,1000,950,.0004,.0004,1000)
 assert not ok and why=="collateral"
 # A smaller position is allowed if both collateral and stop-risk fit.
 ok,why=L.open(4000,"p3","TEST","ETHUSDT",1,2,1000,950,.0004,.0004,1000);assert ok,(ok,why)
 # Actual timestamped funding cashflow.
 L.funding_event(5000,"BTCUSDT",.0001)
 L.mark(6000,"ETHUSDT",980)
 L.close(7000,"p3",980,.0004,"STOP",980)
 L.close(8000,"p1",1020,.0004,"TARGET",1020)
 L.assert_reconciles()
 return L

def main():
 L=scenario();L.write_jsonl(OUT/"ledger.jsonl");m=L.manifest()
 # Deterministic independent replay.
 L2=scenario();assert m["ledger_sha256"]==L2.manifest()["ledger_sha256"]
 # Every accepted OPEN snapshot must have nonnegative available collateral.
 opens=[e for e in L.events if e["event"]=="OPEN"]
 assert all(e["available_collateral"]>=-1e-7 for e in opens)
 # Aggregate risk must be <= configured 6% at every accepted OPEN.
 assert all(e["open_stop_risk"]<=e["equity"]*.06+1e-7 for e in opens)
 # Ledger sequence and timestamps are monotonic.
 assert [e["seq"] for e in L.events]==list(range(1,len(L.events)+1))
 assert all(L.events[i]["timestamp"]<=L.events[i+1]["timestamp"] for i in range(len(L.events)-1))
 s={"version":"R16-INTEGRITY-CORE-2","status":"PASS",
    "checks":["cash/equity reconciliation","1x entry collateral invariant","aggregate stop-risk hard ceiling",
              "separate commissions/slippage/funding","timestamped funding event","deterministic ledger replay",
              "immutable monotonic event ledger"],
    **m}
 (OUT/"summary.json").write_text(json.dumps(s,indent=2),encoding="utf-8");print(json.dumps(s,indent=2))
if __name__=="__main__":main()
