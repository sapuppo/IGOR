#!/usr/bin/env python3
import json, math, urllib.request, urllib.parse, datetime, csv
from pathlib import Path
UA="Mozilla/5.0 V09-live-paper/2.0"

def get(base,path,params):
    url=base+path+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r: return json.loads(r.read())

now=datetime.datetime.now(datetime.timezone.utc)
nowms=int(now.timestamp()*1000)
# Point-in-time ranking for latest completed UTC date.
cmc_date=(now.date()-datetime.timedelta(days=1)).isoformat()
cmc=get("https://api.coinmarketcap.com","/data-api/v3/cryptocurrency/listings/historical",
        {"date":cmc_date,"start":1,"limit":300,"convert":"USD"})
rows=cmc.get("data") or []\nPath("v09_live").mkdir(exist_ok=True)\nPath("v09_live/cmc_rank101_300.json").write_text(json.dumps([x for x in rows if 101<=int(x.get("cmcRank",0))<=300],indent=2),encoding="utf-8")
ranked={str(x.get("symbol","")).upper():{"rank":int(x["cmcRank"]),"name":x.get("name",""),
        "mcap":float(((x.get("quotes") or [{}])[0]).get("marketCap") or 0)}
        for x in rows if 101<=int(x.get("cmcRank",0))<=300}

ex=get("https://fapi.binance.com","/fapi/v1/exchangeInfo",{})
symbols={}
for s in ex["symbols"]:
    if s.get("contractType")=="PERPETUAL" and s.get("quoteAsset")=="USDT" and s.get("status")=="TRADING":
        symbols[s["symbol"]]=s

def klines(sym,limit=220):
    return get("https://fapi.binance.com","/fapi/v1/klines",{"symbol":sym,"interval":"4h","limit":limit})
def ema(vals,n):
    a=2/(n+1); e=vals[0]
    for x in vals[1:]: e=a*x+(1-a)*e
    return e
def atr(bars,n=14):
    trs=[]
    for i in range(1,len(bars)):
        h=float(bars[i][2]); l=float(bars[i][3]); pc=float(bars[i-1][4])
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    if len(trs)<n:return None
    a=sum(trs[:n])/n
    for x in trs[n:]: a=(a*(n-1)+x)/n
    return a
def pct(cur,old):
    return (cur/old-1)*100 if old else None

btc=[b for b in klines("BTCUSDT") if int(b[6])<nowms]
btc_cl=[float(b[4]) for b in btc]
btc_e12=ema(btc_cl[-60:],12); btc_e26=ema(btc_cl[-60:],26)
btc_trend=1 if btc_cl[-1]>btc_e12>btc_e26 else (-1 if btc_cl[-1]<btc_e12<btc_e26 else 0)
btcmap={int(x[0]):float(x[4]) for x in btc}

aliases={"SHIB":"1000SHIB","BONK":"1000BONK","PEPE":"1000PEPE","FLOKI":"1000FLOKI","LUNC":"1000LUNC","XEC":"1000XEC","SATS":"1000SATS","RATS":"1000RATS","CAT":"1000CAT","CHEEMS":"1000CHEEMS","WHY":"1000WHY"}
cands=[]
for cs,meta in ranked.items():
    fs=None
    for base in [cs,aliases.get(cs,"")]:
        if base and base+"USDT" in symbols: fs=base+"USDT"; break
    if not fs: continue
    try:
        b=[x for x in klines(fs) if int(x[6])<nowms]
        if len(b)<190: continue
        closes=[float(x[4]) for x in b]; qvol=[float(x[7]) for x in b]
        aligned=[(float(x[4]),btcmap[int(x[0])]) for x in b if int(x[0]) in btcmap]
        if len(aligned)<30: continue
        ratios=[a/z for a,z in aligned]
        cur_ratio=ratios[-1]; prior_ratio=ratios[-21:-1]
        rs_up=cur_ratio/max(prior_ratio)-1
        rs_dn=min(prior_ratio)/cur_ratio-1
        vm=qvol[-1]/(sum(qvol[-21:-1])/20) if sum(qvol[-21:-1])>0 else 0
        q24=sum(qvol[-6:])
        a=atr(b[-60:])
        direction="LONG" if btc_trend==1 else ("SHORT" if btc_trend==-1 else "FLAT")
        # V09 breakout proxies on the latest completed 4h bar
        prior_high=max(float(x[2]) for x in b[-21:-1])
        prior_low=min(float(x[3]) for x in b[-21:-1])
        price_break=(closes[-1]>prior_high if direction=="LONG" else closes[-1]<prior_low if direction=="SHORT" else False)
        rs_break=(rs_up>0 if direction=="LONG" else rs_dn>0 if direction=="SHORT" else False)
        exact=bool(price_break and rs_break and vm>=1.5 and q24>=5_000_000 and a)
        rs=rs_up if direction=="LONG" else rs_dn if direction=="SHORT" else -1
        dist_price=((closes[-1]/prior_high-1)*100 if direction=="LONG" else (prior_low/closes[-1]-1)*100 if direction=="SHORT" else -999)
        # near-signal ranking: regime/price+RS breakout proximity, volume acceleration and liquidity
        score=(25 if price_break else max(-20,min(dist_price,0))*1.5)+(25 if rs_break else max(-20,min(rs*100,0))*1.5)+min(vm,5)*5+min(max(math.log10(max(q24,1))-6,0),4)*3
        px=closes[-1]
        stop=(px-2*a if direction=="LONG" else px+2*a) if a and direction!="FLAT" else None
        rec={"rank":meta["rank"],"cmc_symbol":cs,"symbol":fs,"name":meta["name"],"market_cap_usd":meta["mcap"],
          "direction":direction,"price":px,"pct_24h":pct(px,closes[-7]),"pct_7d":pct(px,closes[-43]),"pct_30d":pct(px,closes[-181]),
          "atr14":a,"stop_2atr":stop,"volume_multiple_4h":vm,"quote_volume_24h":q24,
          "rs_breakout_pct":rs*100 if direction!="FLAT" else None,"price_breakout_distance_pct":dist_price,
          "price_breakout":price_break,"rs_breakout":rs_break,"exact_v09_signal":exact,"score":score,
          "last_closed_4h_open_ms":int(b[-1][0])}
        cands.append(rec)
    except Exception:
        pass
exact=sorted([x for x in cands if x["exact_v09_signal"]],key=lambda x:x["score"],reverse=True)
near=sorted(cands,key=lambda x:x["score"],reverse=True)
pool=list(exact[:5])
seen={x["symbol"] for x in pool}
for x in near:
    if len(pool)>=5: break
    if x["symbol"] not in seen:
        pool.append(x); seen.add(x["symbol"])
out={"asof_utc":now.isoformat(),"cmc_snapshot_date":cmc_date,"btc_regime":btc_trend,
     "btc_close":btc_cl[-1],"btc_ema12":btc_e12,"btc_ema26":btc_e26,
     "ranked_101_300_count":len(ranked),"eligible_rank_101_300_futures":len(cands),
     "exact_signal_count":len(exact),"selected_for_2h_paper":pool,
     "exact_signals":exact,"top20":near[:20]}
Path("v09_live").mkdir(exist_ok=True)
Path("v09_live/scan.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
cols=["rank","cmc_symbol","symbol","name","market_cap_usd","direction","price","pct_24h","pct_7d","pct_30d","volume_multiple_4h","quote_volume_24h","rs_breakout_pct","price_breakout_distance_pct","price_breakout","rs_breakout","exact_v09_signal","score","stop_2atr"]
with open("v09_live/rank101_300.csv","w",newline="",encoding="utf-8") as fh:
    w=csv.DictWriter(fh,fieldnames=cols); w.writeheader()
    for x in sorted(cands,key=lambda z:z["rank"]): w.writerow({k:x.get(k) for k in cols})
print(json.dumps(out,indent=2))
