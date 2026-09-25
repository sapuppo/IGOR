#!/usr/bin/env python3
"""R16.25B causal historical/forward validation.

Consumes the immutable R16.25A event contract and the frozen R16.24.2 baseline.
Rules:
- never rewrite event_time;
- never use observations at/before event_time as forward outcomes;
- never credit live snapshots to pre-event historical performance;
- historical rows are accepted only when their source timestamp is independently archived.
"""
from pathlib import Path
import json, hashlib, time
from urllib.request import Request, urlopen
import pandas as pd
import numpy as np

ROOT=Path("r16_edge_lab/r16_25b_inputs")
OUT=Path("r16_edge_lab/r16_25b_validation"); OUT.mkdir(parents=True,exist_ok=True)
SCHEMA=["event_time","symbol","source_type","source_id","direction","confidence","magnitude","novelty","raw_ref"]
HORIZONS={"15m":15*60_000,"1h":60*60_000,"4h":4*60*60_000,"24h":24*60*60_000}
HL_INFO="https://api.hyperliquid.xyz/info"

def ff(root,name):
    h=list(root.rglob(name))
    if not h: raise FileNotFoundError(f"{name} under {root}")
    return h[0]

def post(body):
    req=Request(HL_INFO,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","User-Agent":"IGOR-R16.25B/1.0"},method="POST")
    with urlopen(req,timeout=25) as r:return json.loads(r.read().decode())

def px_after(symbol,ts):
    # Candle open is timestamped at its interval start. Requiring t > event_time
    # guarantees the scored observation did not exist when the event was emitted.
    start=((int(ts)//60_000)+1)*60_000
    end=start+2*60_000
    z=post({"type":"candleSnapshot","req":{"coin":symbol,"interval":"1m","startTime":start,"endTime":end}})
    z=[x for x in z if int(x.get("t",0))>=start]
    return (float(z[0]["o"]),int(z[0]["t"])) if z else (None,None)

def outcome(symbol,event_time,h):
    target=int(event_time)+int(h)
    if int(time.time()*1000) < target+60_000:return None
    p0,t0=px_after(symbol,event_time)
    p1,t1=px_after(symbol,target)
    if p0 is None or p1 is None:return None
    assert t0>int(event_time), "look-ahead guard: entry observation must be strictly post-event"
    assert t1>target, "look-ahead guard: outcome observation must be strictly post-horizon"
    return {"entry_px":p0,"entry_obs_time":t0,"exit_px":p1,"exit_obs_time":t1,"raw_return":p1/p0-1}

events=pd.read_csv(ff(ROOT/"a","events_live.csv"))
missing=[c for c in SCHEMA if c not in events.columns]
if missing:raise ValueError(f"invalid R16.25A schema missing={missing}")
events=events[SCHEMA].copy()
for c in ["event_time","direction","confidence","magnitude","novelty"]:events[c]=pd.to_numeric(events[c],errors="raise")
if events.raw_ref.duplicated().any():raise ValueError("raw_ref must be unique")
if not events.direction.isin([-1,1]).all():raise ValueError("direction must be -1/+1")

baseline_path=ff(ROOT/"baseline","summary.json")
baseline_bytes=baseline_path.read_bytes()
baseline=json.loads(baseline_bytes)
if baseline.get("version")!="R16.24.2":raise ValueError("baseline is not R16.24.2")
baseline_sha=hashlib.sha256(baseline_bytes).hexdigest()

rows=[]
for e in events.itertuples(index=False):
    for label,h in HORIZONS.items():
        rec={"raw_ref":e.raw_ref,"event_time":int(e.event_time),"symbol":str(e.symbol),"source_type":e.source_type,
             "direction":int(e.direction),"confidence":float(e.confidence),"magnitude":float(e.magnitude),
             "horizon":label,"status":"pending"}
        try:o=outcome(str(e.symbol),int(e.event_time),h)
        except Exception as ex:o=None;rec["error"]=f"{type(ex).__name__}: {ex}"
        if o:
            rec.update(o);rec["signed_return"]=float(o["raw_return"])*int(e.direction);rec["hit"]=int(rec["signed_return"]>0);rec["status"]="matured"
        rows.append(rec)
R=pd.DataFrame(rows)
R.to_csv(OUT/"forward_event_validation.csv",index=False)

m=R[R.status=="matured"].copy()
metrics={}
for h,g in m.groupby("horizon"):
    metrics[h]={"n":int(len(g)),"mean_signed_return":float(g.signed_return.mean()),"median_signed_return":float(g.signed_return.median()),
                "hit_rate":float(g.hit.mean()),"confidence_weighted_return":float(np.average(g.signed_return,weights=np.maximum(g.confidence,1e-9)))}

summary={"version":"R16.25B","baseline_version":"R16.24.2","baseline_sha256":baseline_sha,
 "causal_schema":SCHEMA,"events_received":int(len(events)),"forward_rows":int(len(R)),"matured_rows":int(len(m)),
 "metrics":metrics,
 "historical_validation":{"status":"not_fabricated","accepted_rule":"Only independently timestamped archived events may enter historical validation.",
   "current_snapshot_backfill_allowed":False,
   "note":"R16.25A is a live snapshot. It is deliberately excluded from pre-event R16.24.2 history; future archived events can be appended causally."},
 "lookahead_guards":["event_time is immutable","entry observation timestamp > event_time","exit observation timestamp > event_time+horizon",
                     "R16.24.2 artifact is read-only baseline and fingerprinted by SHA-256"],
 "decision":"collect_forward" if len(m)<20 else "evaluate_edge"}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float))
