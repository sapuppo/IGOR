#!/usr/bin/env python3
import json, math, urllib.request, urllib.parse, datetime, statistics, time
from pathlib import Path

UA="Mozilla/5.0 V09-live-paper/1.0"
def get(base,path,params):
    url=base+path+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=30) as r: return json.loads(r.read())

today=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
cmc=get("https://api.coinmarketcap.com","/data-api/v3/cryptocurrency/listings/historical",
        {"date":today,"start":1,"limit":300,"convert":"USD"})
rows=cmc["data"]
ranked={str(x.get("symbol","")).upper():{"rank":int(x["cmcRank"]),"name":x.get("name","")} for x in rows if 101<=int(x.get("cmcRank",0))<=300}

ex=get("https://fapi.binance.com","/fapi/v1/exchangeInfo",{})
symbols={}
for s in ex["symbols"]:
    if s.get("contractType")=="PERPETUAL" and s.get("quoteAsset")=="USDT" and s.get("status")=="TRADING":
        symbols[s["symbol"]]=s

def klines(sym,limit=80):
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

btc=klines("BTCUSDT")
# use only completed candles: newest kline can be open
nowms=int(datetime.datetime.now(datetime.timezone.utc).timestamp()*1000)
btc=[b for b in btc if int(b[6])<nowms]
btc_cl=[float(b[4]) for b in btc]
btc_trend=1 if btc_cl[-1]>ema(btc_cl[-40:],12)>ema(btc_cl[-40:],26) else (-1 if btc_cl[-1]<ema(btc_cl[-40:],12)<ema(btc_cl[-40:],26) else 0)

aliases={"SHIB":"1000SHIB","BONK":"1000BONK","PEPE":"1000PEPE","FLOKI":"1000FLOKI","LUNC":"1000LUNC","XEC":"1000XEC","SATS":"1000SATS","RATS":"1000RATS","CAT":"1000CAT","CHEEMS":"1000CHEEMS","WHY":"1000WHY"}
cands=[]
for cs,meta in ranked.items():
    bases=[cs,aliases.get(cs,"")]
    fs=None
    for b in bases:
        if b and b+"USDT" in symbols: fs=b+"USDT";break
    if not fs: continue
    try:
        b=klines(fs)
        b=[x for x in b if int(x[6])<nowms]
        if len(b)<35: continue
        closes=[float(x[4]) for x in b]; vols=[float(x[7]) for x in b]
        # align by open time with BTC
        btcmap={int(x[0]):float(x[4]) for x in btc}
        pairs=[(float(x[4]),btcmap[int(x[0])]) for x in b if int(x[0]) in btcmap]
        if len(pairs)<25:continue
        ratios=[a/z for a,z in pairs]
        cur=ratios[-1]; prev=ratios[-21:-1]
        rs_up=cur/max(prev)-1; rs_dn=min(prev)/cur-1
        vm=vols[-1]/(sum(vols[-21:-1])/20) if sum(vols[-21:-1])>0 else 0
        q24=sum(vols[-6:])
        a=atr(b[-40:])
        direction="LONG" if btc_trend==1 else ("SHORT" if btc_trend==-1 else "FLAT")
        breakout=(rs_up>0 if direction=="LONG" else (rs_dn>0 if direction=="SHORT" else False))
        exact=bool(breakout and vm>=1.5 and q24>=5_000_000 and a)
        rs=rs_up if direction=="LONG" else rs_dn
        # near-signal score prioritizes RS, volume multiple, liquidity
        score=(max(-0.2,min(rs,0.2))*100)+(min(vm,5)*2)+(min(math.log10(max(q24,1)),10))
        px=closes[-1]
        stop=(px-2*a if direction=="LONG" else px+2*a) if a and direction!="FLAT" else None
        cands.append({"rank":meta["rank"],"cmc_symbol":cs,"symbol":fs,"name":meta["name"],"direction":direction,
          "price":px,"atr14":a,"stop_2atr":stop,"volume_multiple_4h":vm,"quote_volume_24h":q24,
          "rs_breakout_pct":rs*100,"exact_v09_signal":exact,"score":score,
          "last_closed_4h_open_ms":int(b[-1][0])})
    except Exception as e:
        pass

exact=[x for x in cands if x["exact_v09_signal"]]
pool=sorted(exact,key=lambda x:x["score"],reverse=True)
if len(pool)<5:
    seen={x["symbol"] for x in pool}
    pool+= [x for x in sorted(cands,key=lambda x:x["score"],reverse=True) if x["symbol"] not in seen][:5-len(pool)]
out={"asof_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"cmc_date":today,"btc_regime":btc_trend,
     "eligible_rank_101_300_futures":len(cands),"exact_signal_count":len(exact),"selected":pool[:5],
     "top20":sorted(cands,key=lambda x:x["score"],reverse=True)[:20]}
Path("v09_live").mkdir(exist_ok=True)
Path("v09_live/scan.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps(out,indent=2))
