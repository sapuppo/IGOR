#!/usr/bin/env python3
"""R16.27 frozen-strategy integration with Integrity Core 2.

No alpha parameter is changed. Candidate trades are rebuilt by R16.24.3 exactly as
before; only portfolio accounting/allocation is replaced by the event ledger.
Historical funding is NOT fabricated: until a real funding dataset is supplied,
this integration records the declared 24.3 funding approximation as a diagnostic
and cannot be promoted beyond integration validation.
"""
from __future__ import annotations
from pathlib import Path
import importlib.util,json,hashlib,math
import pandas as pd,numpy as np
from r16_sim_core import PortfolioLedger

def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
R=load("r16_edge_lab/run_r16_24_3_causal_revalidation.py","r243")
OUT=Path("r16_edge_lab/r16_27_core2_integration");OUT.mkdir(parents=True,exist_ok=True)
MAX_STOP_RISK=.06

def score(F,t,lb=6):
 return R.scores(F,t,lb)

def run(F):
 ev=[]
 for e,d in F.items():
  for i,r in d.iterrows():
   ev.append((int(r.entry_time),1,e,i))
   for t,v in r.marks:ev.append((int(t),0,e,i,float(v)))
   ev.append((int(r.exit_time),2,e,i))
 ev.sort(key=lambda x:(x[0],x[1],x[2],x[3]))
 L=PortfolioLedger(R.START_CAP,leverage=1.0,max_stop_risk_fraction=MAX_STOP_RISK)
 active={}; accepted={e:0 for e in F};rej={}
 # Keep original 24.3 allocation/risk geometry. Ledger is the authority on collateral/risk.
 peak=R.START_CAP
 for item in ev:
  t,typ,e,i,*rest=item;r=F[e].iloc[i];key=f"{e}:{i}"
  if typ==0:
   if key in active:
    # mark return in 24.3 is relative to entry; reconstruct mark price with normalized entry=1.
    L.mark(t,str(r.symbol),1.0+float(rest[0]))
    peak=max(peak,L.equity())
   continue
  if typ==2:
   if key in active:
    # Candidate net_pct contains old aggregate cost/funding. For integration accounting,
    # close on gross price only and keep costs explicit; historical funding is pending.
    px=1.0+float(r.gross_pct)
    L.close(t,key,px,exit_fee_rate=0.0,reason=str(r.reason),reference_price=px)
    del active[key];peak=max(peak,L.equity())
   continue
  # entry
  sv=score(F,t);vs=np.array(list(sv.values()),float);hot=(len(vs)>0 and vs.mean()>0 and sum(v>0 for v in sv.values())>=2)
  mult=1.5 if hot else .5
  if sv.get(e,0)<0 and not(e=="CORE" and not hot):
   rej["regime"]=rej.get("regime",0)+1;continue
  if sum(1 for x in active if x.startswith(e+":"))>=R.MAXPOS[e]:
   rej["engine_maxpos"]=rej.get("engine_maxpos",0)+1;continue
  if any(p.symbol==str(r.symbol) for p in L.positions.values()):
   rej["symbol_held"]=rej.get("symbol_held",0)+1;continue
  eq=L.equity(); risk_cash=eq*R.RISK[e]*mult
  stop_pct=float(r.stop_pct)
  desired=min(eq*R.PER,risk_cash/max(stop_pct,1e-12))
  # 1x collateral sizing is explicit. Fee is zero here because 24.3 candidate gross/cost
  # decomposition did not preserve commission vs slippage. We refuse to invent it.
  max_by_coll=max(0.0,L.available_collateral())
  notional=min(desired,max_by_coll)
  if notional<eq*.005:
   rej["collateral_or_min_size"]=rej.get("collateral_or_min_size",0)+1;continue
  qty=notional
  ok,why=L.open(t,key,e,str(r.symbol),1,qty,1.0,max(1e-9,1.0-stop_pct),0.0,0.0,1.0)
  if not ok:
   rej[why]=rej.get(why,0)+1;continue
  active[key]=True;accepted[e]+=1;peak=max(peak,L.equity())
 # force no silent open positions at end: diagnostic only
 L.assert_reconciles()
 L.write_jsonl(OUT/"ledger.jsonl")
 return L,accepted,rej

def main():
 r1,c1,g1=R.rev1();r15,c15,g15=R.rev15();ce=R.core()
 cfg={"CORE":("4h",4*3600000,30,6.,ce),"REV1H":("1h",3600000,g1[2],g1[1],r1[["symbol","entry_time"]]),
      "REV15M":("15m",15*60000,g15[2],g15[1],r15[["symbol","entry_time"]])}
 # Stress candidates rebuilt with exactly frozen 24.3 candidate economics.
 cost,fund=R.COST["stress"];F={}
 for e,(iv,bar,hold,tp,en) in cfg.items():F[e]=R.rebuild(en,e,iv,bar,hold,tp,R.STOP[e],cost,fund)
 L,acc,rej=run(F)
 source_hashes={}
 for p in ["r16_edge_lab/run_r16_24_3_causal_revalidation.py","r16_edge_lab/r16_sim_core.py","r16_edge_lab/BACKTEST_INTEGRITY_CONTRACT.md"]:
  source_hashes[p]=hashlib.sha256(Path(p).read_bytes()).hexdigest()
 s={"version":"R16.27","purpose":"frozen R16.24.3 strategy integrated with Integrity Core 2; no alpha optimization",
    "status":"INTEGRATION_VALID_NOT_PROMOTABLE","accepted":acc,"rejections":rej,
    "ledger":L.manifest(),"source_sha256":source_hashes,
    "frozen":{"stops":R.STOP,"rev1h_geometry":g1,"rev15m_geometry":g15},
    "blocking":["historical USD-M funding dataset not yet integrated",
                "commission vs spread/slippage decomposition unavailable in frozen R16.24.3 candidates",
                "point-in-time listing/delisting universe not yet proven",
                "fresh chronological walk-forward/OOS not yet executed"],
    "profit_metrics_suppressed":True}
 (OUT/"summary.json").write_text(json.dumps(s,indent=2,default=float),encoding="utf-8")
 print(json.dumps(s,indent=2,default=float))
if __name__=="__main__":main()
