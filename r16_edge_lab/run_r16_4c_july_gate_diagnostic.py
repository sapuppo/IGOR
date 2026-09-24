#!/usr/bin/env python3
"""R16.4C - July opportunity diagnostics.

No strategy optimization. This only attributes where July 2026 candidate LONG breakouts
are rejected by the frozen R16.2 gates and reports nearby opportunity counts.
"""
from pathlib import Path
import json, numpy as np, pandas as pd

ROOT=Path("r15_regime_lab/history/4h")
OUT=Path("r16_edge_lab/r16_4c_july_gate_diagnostic")
OUT.mkdir(parents=True,exist_ok=True)
START=int(pd.Timestamp("2026-07-01T00:00:00Z").timestamp()*1000)
END=int(pd.Timestamp("2026-08-01T00:00:00Z").timestamp()*1000)
SYMBOLS=['BTCUSDT','ETHUSDT','BNBUSDT','XRPUSDT','SOLUSDT','TRXUSDT','ZECUSDT','DOGEUSDT','LINKUSDT','ADAUSDT','XLMUSDT','UNIUSDT','BCHUSDT','NEARUSDT','AVAXUSDT','LTCUSDT','SUIUSDT','HBARUSDT','TAOUSDT','AAVEUSDT','ENAUSDT','ONDOUSDT','DOTUSDT','ICPUSDT','WLDUSDT','ETCUSDT','POLUSDT','TONUSDT','FILUSDT','ATOMUSDT','INJUSDT','APTUSDT','FETUSDT','RENDERUSDT','PEPEUSDT','ALGOUSDT','VETUSDT','GRTUSDT','RUNEUSDT']

def rma(s,n): return s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def load(sym):
    x=pd.read_csv(ROOT/f"{sym}.csv.gz")
    for c in ["open_time","open","high","low","close","volume"]: x[c]=pd.to_numeric(x[c],errors="coerce")
    x=x.dropna().sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    h,l,c=x.high,x.low,x.close; pc=c.shift()
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr=rma(tr,14)
    up=h.diff();dn=-l.diff()
    plus=100*rma(up.where((up>dn)&(up>0),0.0),14)/atr.replace(0,np.nan)
    minus=100*rma(dn.where((dn>up)&(dn>0),0.0),14)/atr.replace(0,np.nan)
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    x["atr"]=atr;x["adx"]=rma(dx,14)
    x["ema50"]=c.ewm(span=50,adjust=False,min_periods=50).mean()
    x["ema200"]=c.ewm(span=200,adjust=False,min_periods=200).mean()
    x["ret42"]=c/c.shift(42)-1
    for d in [20,40,55,70]:
        x[f"hi{d}"]=h.shift(1).rolling(d,min_periods=d).max()
    return x

F={s:load(s) for s in SYMBOLS}
parts=[]
for sym,z in F.items():
    ser=pd.Series(np.where(z.ema200.notna(),(z.close>z.ema200).astype(float),np.nan),
                  index=z.open_time.astype("int64"),name=sym)
    parts.append(ser[~ser.index.duplicated()])
breadth=pd.concat(parts,axis=1).mean(axis=1,skipna=True)
btc=F["BTCUSDT"].set_index("open_time")
btc_up=((btc.close>btc.ema200)&(btc.ema50>btc.ema200)&(btc.ret42>0))
CTX=pd.DataFrame({"breadth":breadth,"btc_up":btc_up.reindex(breadth.index).fillna(False)})

rows=[]
for sym,z in F.items():
    for don in [20,40,55,70]:
        hi=z[f"hi{don}"]; c=z.close; prev=c.shift()
        breakout=(c>hi)&(prev<=hi.shift())
        trend=(z.ema50>z.ema200)
        for i in np.flatnonzero(np.asarray((breakout & trend).fillna(False))):
            ts=int(z.open_time.iloc[i])
            if not (START<=ts<END) or ts not in CTX.index: continue
            rows.append({
              "symbol":sym,"don":don,"ts":ts,"adx":float(z.adx.iloc[i]),
              "breadth":float(CTX.loc[ts,"breadth"]),"btc_up":bool(CTX.loc[ts,"btc_up"])
            })
R=pd.DataFrame(rows)
R.to_csv(OUT/"july_candidates.csv",index=False)

summary={"period":"2026-07-01..2026-07-31 UTC"}
if R.empty:
    summary["candidates"]=0
else:
    d55=R[R.don.eq(55)].copy()
    summary["d55_breakout_trend_candidates"]=int(len(d55))
    summary["d55_by_gate"]={
      "adx_ge20":int((d55.adx>=20).sum()),
      "adx_ge25":int((d55.adx>=25).sum()),
      "adx_ge30":int((d55.adx>=30).sum()),
      "btc_up":int(d55.btc_up.sum()),
      "breadth_ge45":int((d55.breadth>=.45).sum()),
      "breadth_ge50":int((d55.breadth>=.50).sum()),
      "breadth_ge55":int((d55.breadth>=.55).sum()),
      "adx30_and_btc":int(((d55.adx>=30)&d55.btc_up).sum()),
      "adx30_and_breadth55":int(((d55.adx>=30)&(d55.breadth>=.55)).sum()),
      "btc_and_breadth55":int((d55.btc_up&(d55.breadth>=.55)).sum()),
      "all_frozen":int(((d55.adx>=30)&d55.btc_up&(d55.breadth>=.55)).sum())
    }
    grid=[]
    for don in [20,40,55,70]:
      q=R[R.don.eq(don)]
      for adx in [20,25,30]:
        for br in [.45,.50,.55]:
          n=int(((q.adx>=adx)&q.btc_up&(q.breadth>=br)).sum())
          grid.append({"don":don,"adx":adx,"breadth":br,"btc_up_required":True,"signals":n})
          n2=int(((q.adx>=adx)&(q.breadth>=br)).sum())
          grid.append({"don":don,"adx":adx,"breadth":br,"btc_up_required":False,"signals":n2})
    G=pd.DataFrame(grid).sort_values("signals",ascending=False)
    G.to_csv(OUT/"nearby_gate_counts.csv",index=False)
    summary["top_nearby_counts"]=G.head(20).to_dict("records")
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2),flush=True)
