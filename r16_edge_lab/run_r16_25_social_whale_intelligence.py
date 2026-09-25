#!/usr/bin/env python3
"""R16.25A Social + Whale Intelligence collector and causal event contract.

Stage A goals:
- collect live public Hyperliquid leaderboard + open positions + recent fills;
- expose readiness for optional Nansen/CryptoQuant/X backfill providers;
- normalize all future external signals into one causal event schema;
- DO NOT feed current snapshots into historical portfolio metrics.

External event schema:
event_time,symbol,source_type,source_id,direction,confidence,magnitude,novelty,raw_ref
"""
from __future__ import annotations
import os,json,time,hashlib,math
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import pandas as pd
import numpy as np

OUT=Path("r16_edge_lab/r16_25_social_whale");OUT.mkdir(parents=True,exist_ok=True)
HL_LEADERBOARD="https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
HL_INFO="https://api.hyperliquid.xyz/info"
TOP_N=int(os.getenv("R16_25_TOP_WALLETS","40"))
TIMEOUT=25

def http_json(url, method="GET", body=None, headers=None):
    h={"User-Agent":"IGOR-R16.25/1.0","Accept":"application/json"}
    if headers:h.update(headers)
    data=None
    if body is not None:
        data=json.dumps(body).encode()
        h["Content-Type"]="application/json"
    req=Request(url,data=data,headers=h,method=method)
    with urlopen(req,timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())

def num(x,default=0.0):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except Exception:return default

def addr(x):
    if not isinstance(x,dict):return None
    for k in ("ethAddress","address","user","wallet","trader_address"):
        v=x.get(k)
        if isinstance(v,str) and v.startswith("0x") and len(v)>=20:return v.lower()
    return None

def leaderboard_rows(obj):
    # Endpoint is undocumented; accept common response shapes defensively.
    candidates=[]
    if isinstance(obj,list):candidates=obj
    elif isinstance(obj,dict):
        for k in ("leaderboardRows","rows","data","leaderboard"):
            v=obj.get(k)
            if isinstance(v,list):candidates=v;break
            if isinstance(v,dict):
                for kk in ("rows","data"):
                    if isinstance(v.get(kk),list):candidates=v[kk];break
    out=[]
    for x in candidates:
        if not isinstance(x,dict):continue
        a=addr(x)
        if not a:continue
        # Hyperliquid has changed field names over time; retain raw and map known ones.
        pnl=num(x.get("pnl",x.get("totalPnl",x.get("windowPnl",0))))
        roi=num(x.get("roi",x.get("windowRoi",0)))
        av=num(x.get("accountValue",x.get("account_value",x.get("equity",0))))
        vol=num(x.get("vlm",x.get("volume",x.get("windowVolume",0))))
        out.append({"address":a,"pnl":pnl,"roi":roi,"account_value":av,"volume":vol,"raw":x})
    return out

def hl_state(address):
    return http_json(HL_INFO,"POST",{"type":"clearinghouseState","user":address})

def hl_fills(address):
    return http_json(HL_INFO,"POST",{"type":"userFills","user":address,"aggregateByTime":True})

def pos_rows(address,state,quality):
    rows=[]
    aps=state.get("assetPositions",[]) if isinstance(state,dict) else []
    for z in aps:
        p=z.get("position",z) if isinstance(z,dict) else {}
        coin=str(p.get("coin","")).upper()
        szi=num(p.get("szi"))
        if not coin or szi==0:continue
        entry=num(p.get("entryPx"))
        value=abs(num(p.get("positionValue")))
        lev=p.get("leverage",{})
        leverage=num(lev.get("value") if isinstance(lev,dict) else lev,1)
        upnl=num(p.get("unrealizedPnl"))
        side=1 if szi>0 else -1
        rows.append({"address":address,"symbol":coin,"side":side,"size":szi,"entry_price":entry,
                     "position_value":value,"leverage":leverage,"unrealized_pnl":upnl,**quality})
    return rows

def fill_summary(address,fills):
    if not isinstance(fills,list):return {"address":address,"fills":0,"closed_pnl":0.0,"buy_notional":0.0,"sell_notional":0.0}
    cp=bn=sn=0.;n=0
    for x in fills:
        if not isinstance(x,dict):continue
        n+=1;cp+=num(x.get("closedPnl"))
        px=num(x.get("px"));sz=abs(num(x.get("sz")));notional=px*sz
        side=str(x.get("side","")).upper()
        if side in ("B","BUY"):bn+=notional
        elif side in ("A","S","SELL"):sn+=notional
    return {"address":address,"fills":n,"closed_pnl":cp,"buy_notional":bn,"sell_notional":sn}

def quality_score(r):
    # Live discovery score only; not a backtested alpha score.
    pnl=np.sign(r["pnl"])*np.log1p(abs(r["pnl"]))/20
    av=np.log1p(max(r["account_value"],0))/20
    roi=np.tanh(r["roi"] if abs(r["roi"])<5 else r["roi"]/100)
    return float(np.clip(.5*pnl+.3*roi+.2*av,-1,1))

now_ms=int(time.time()*1000)
status={"timestamp_ms":now_ms,"hyperliquid_leaderboard":False,"hyperliquid_info":False,
        "nansen_key":bool(os.getenv("NANSEN_API_KEY")),
        "cryptoquant_key":bool(os.getenv("CRYPTOQUANT_API_KEY")),
        "x_bearer_token":bool(os.getenv("X_BEARER_TOKEN")),
        "warnings":[]}
leaders=[];positions=[];fillsums=[]
try:
    raw=http_json(HL_LEADERBOARD)
    leaders=leaderboard_rows(raw)
    status["hyperliquid_leaderboard"]=len(leaders)>0
    if not leaders:status["warnings"].append("Leaderboard reachable but no recognized wallet rows.")
except Exception as e:
    status["warnings"].append(f"Leaderboard unavailable: {type(e).__name__}: {e}")

# Rank by a conservative blend, not raw PnL alone.
for r in leaders:r["quality_discovery"]=quality_score(r)
leaders=sorted(leaders,key=lambda x:(x["quality_discovery"],x["account_value"]),reverse=True)[:TOP_N]

for r in leaders:
    a=r["address"];q={k:r[k] for k in ("pnl","roi","account_value","volume","quality_discovery")}
    try:
        st=hl_state(a);positions.extend(pos_rows(a,st,q));status["hyperliquid_info"]=True
    except Exception as e:status["warnings"].append(f"state {a[:10]}: {type(e).__name__}")
    try:fillsums.append(fill_summary(a,hl_fills(a)))
    except Exception as e:status["warnings"].append(f"fills {a[:10]}: {type(e).__name__}")

L=pd.DataFrame([{k:v for k,v in r.items() if k!="raw"} for r in leaders])
P=pd.DataFrame(positions);F=pd.DataFrame(fillsums)
L.to_csv(OUT/"leaderboard_snapshot.csv",index=False)
P.to_csv(OUT/"positions_snapshot.csv",index=False)
F.to_csv(OUT/"fills_snapshot.csv",index=False)

# Build current consensus events. These are for forward logging only, never historical leakage.
events=[];consensus=[]
if not P.empty:
    for sym,g in P.groupby("symbol"):
        w=np.maximum(g["position_value"].to_numpy(float),1.0)*(0.25+0.75*np.maximum(g["quality_discovery"].to_numpy(float),0))
        sides=g["side"].to_numpy(float)
        net=float(np.sum(w*sides));gross=float(np.sum(w));score=net/gross if gross else 0.
        longv=float(g.loc[g.side>0,"position_value"].sum());shortv=float(g.loc[g.side<0,"position_value"].sum())
        confidence=float(min(1,abs(score))*min(1,len(g)/8))
        consensus.append({"symbol":sym,"wallets":len(g),"long_value":longv,"short_value":shortv,
                          "net_consensus":score,"confidence":confidence})
        if abs(score)>=.15 and len(g)>=2:
            raw_ref=hashlib.sha256(f"{now_ms}|{sym}|{score:.8f}".encode()).hexdigest()[:16]
            events.append({"event_time":now_ms,"symbol":sym,"source_type":"whale_hyperliquid",
                           "source_id":"hl_top_wallet_consensus","direction":1 if score>0 else -1,
                           "confidence":confidence,"magnitude":abs(score),"novelty":1.0,"raw_ref":raw_ref})
C=pd.DataFrame(consensus).sort_values("confidence",ascending=False) if consensus else pd.DataFrame()
E=pd.DataFrame(events)
C.to_csv(OUT/"whale_consensus_snapshot.csv",index=False)
E.to_csv(OUT/"events_live.csv",index=False)

status["leaders_recognized"]=len(L);status["positions_recognized"]=len(P);status["events_emitted"]=len(E)
status["stage"]="LIVE_COLLECTION_ONLY"
status["causal_rule"]="Current snapshots may only be scored on returns strictly after event_time; they are not backfilled into prior portfolio returns."
(OUT/"source_readiness.json").write_text(json.dumps(status,indent=2),encoding="utf-8")
summary={"version":"R16.25A","status":status,
         "top_consensus":C.head(15).to_dict("records") if not C.empty else [],
         "notes":["Hyperliquid leaderboard is an undocumented public endpoint; health-check separately.",
                  "Official Hyperliquid info endpoint is used for wallet positions/fills.",
                  "Nansen/CryptoQuant/X adapters are gated by credentials and will be used for historical backfill/independent validation.",
                  "No current whale/social signal is credited to historical R16.24.2 performance."]}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float),encoding="utf-8")
print(json.dumps(summary,indent=2,default=float))
