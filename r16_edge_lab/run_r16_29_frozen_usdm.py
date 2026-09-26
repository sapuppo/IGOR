#!/usr/bin/env python3
"""R16.29 frozen USD-M rebuild. No alpha optimization."""
from __future__ import annotations
from pathlib import Path
import importlib.util,json,hashlib,math
from functools import lru_cache
import pandas as pd,numpy as np
from r16_sim_core import PortfolioLedger

ROOT=Path("r16_edge_lab/usdm_history")
OUT=Path("r16_edge_lab/r16_29_frozen_usdm");OUT.mkdir(parents=True,exist_ok=True)
START_CAP=10000.;PER=.40
RISK={"CORE":.0075,"REV1H":.01,"REV15M":.015};MAXPOS={e:5 for e in RISK}
STOP={"CORE":3.0,"REV1H":3.0,"REV15M":1.5}
TAKER=.0004;SLIP=.0002;MAX_STOP_RISK=.06
MONTHS=pd.period_range("2021-01","2026-06",freq="M").astype(str)

def loadmod(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
R14=loadmod("r16_edge_lab/run_r16_14_extreme_reversion.py","r14")
R16=loadmod("r16_edge_lab/run_r16_16_intraday_reversion.py","r16")
R243=loadmod("r16_edge_lab/run_r16_24_3_causal_revalidation.py","r243")

@lru_cache(maxsize=None)
def kline(sym,iv):
 p=ROOT/"klines"/iv/f"{sym}.csv.gz"
 if not p.exists():return pd.DataFrame()
 x=pd.read_csv(p)
 for c in ["open_time","open","high","low","close","volume"]:x[c]=pd.to_numeric(x[c],errors="coerce")
 x=x.dropna(subset=["open_time","open","high","low","close"]).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
 h,l,cl,v=x.high,x.low,x.close,x.volume;pc=cl.shift()
 tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
 rma=lambda s,n:s.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
 x["atr"]=rma(tr,14)
 gain=rma(cl.diff().clip(lower=0),14);loss=rma((-cl.diff()).clip(lower=0),14)
 x["rsi14"]=100-(100/(1+gain/loss.replace(0,np.nan)))
 x["body_pos"]=(cl-l)/(h-l).replace(0,np.nan)
 if iv=="1h":
  x["ret6"]=cl.pct_change(6)
  x["volz48"]=(v-v.rolling(48,min_periods=36).mean())/v.rolling(48,min_periods=36).std().replace(0,np.nan)
 if iv=="15m":
  x["volz96"]=(v-v.rolling(96,min_periods=72).mean())/v.rolling(96,min_periods=72).std().replace(0,np.nan)
  for hb in [4,8,16]:x[f"ret{hb}"]=cl.pct_change(hb)
 return x

@lru_cache(maxsize=None)
def funding(sym):
 p=ROOT/"funding"/f"{sym}.csv.gz"
 return pd.read_csv(p) if p.exists() else pd.DataFrame(columns=["fundingTime","fundingRate"])

FROZEN_REV1H={"name":"LONG_M8_V15_B60_G1_C3","move":0.08,"volz":1.5,"body":0.60,"cluster_h":3,"geom":(1.5,3.0,24)}
FROZEN_REV15M={"name":"LONG_H4_M6_V15_B60_G0_C3","move":0.06,"volz":1.5,"body":0.60,"cluster_h":3,"horizon_bars":16,"geom":(1.25,2.5,16)}
FROZEN_CONFIG_SHA256=hashlib.sha256(json.dumps({"stops":STOP,"rev1h":FROZEN_REV1H,"rev15m":FROZEN_REV15M},sort_keys=True,default=list).encode()).hexdigest()

def frozen_entries():
 c1=FROZEN_REV1H;g1=c1["geom"];c15=FROZEN_REV15M;g15=c15["geom"]
 F1={}
 for s in R14.SYMBOLS:
  z=kline(s,"1h")
  if not z.empty:F1[s]=z
 x1=R14.raw_events(F1,"LONG",g1,0.,0.)
 m=(x1.ret6<=-c1["move"])&(x1.volz48>=c1["volz"])&(x1.rsi14<=35)&(x1.body_pos>=c1["body"])
 r1=R243.first3(x1[m].copy(),c1["cluster_h"])[["symbol","entry_time"]]
 F15={}
 for s in R16.SYMBOLS:
  z=kline(s,"15m")
  if not z.empty:F15[s]=z
 x15=R16.raw_for(F15,"LONG",c15["horizon_bars"],g15,0.,0.)
 m=(x15.move_ret<=-c15["move"])&(x15.volz>=c15["volz"])&(x15.rsi<=35)&(x15.body>=c15["body"])
 r15=R243.first3(x15[m].copy(),c15["cluster_h"])[["symbol","entry_time"]]
 # CORE signal timestamps remain frozen from the preserved R16.24.3 artifact and are materialized by workflow.
 p=Path("r16_edge_lab/r16_29_inputs/core_entries.csv.gz")
 if not p.exists(): raise FileNotFoundError("materialized frozen CORE entries missing")
 ce=pd.read_csv(p)[["symbol","entry_time"]].drop_duplicates().sort_values(["entry_time","symbol"])
 return ce,r1,r15,g1,g15

def rebuild(ent,e,iv,bar,hold,target,stop):
 cache={};rows=[]
 for r in ent.sort_values(["entry_time","symbol"]).itertuples(index=False):
  sym=str(r.symbol)
  if sym not in cache:cache[sym]=kline(sym,iv)
  z=cache[sym]
  if z.empty:continue
  a=z.open_time.to_numpy(np.int64);signal=int(r.entry_time)
  # next-observation fill: signal timestamp cannot fill on same observation.
  ei=int(np.searchsorted(a,signal,side="right"))
  if ei>=len(z):continue
  atr=float(z.atr.iloc[ei-1]);ref=float(z.open.iloc[ei])
  if not np.isfinite(atr) or atr<=0 or ref<=0:continue
  fill=ref*(1+SLIP);sp=fill-stop*atr;tp=fill+target*atr;end=min(ei+hold-1,len(z)-1)
  xp=float(z.close.iloc[end]);xi=end;reason="TIME"
  for j in range(ei,end+1):
   hs=float(z.low.iloc[j])<=sp;ht=float(z.high.iloc[j])>=tp
   if hs and ht:xp=sp;xi=j;reason="STOP_AMBIGUOUS";break
   if hs:xp=sp;xi=j;reason="STOP";break
   if ht:xp=tp;xi=j;reason="TARGET";break
  ex=int(z.open_time.iloc[xi])+bar
  marks=[(int(z.open_time.iloc[j])+bar,float(z.close.iloc[j])) for j in range(ei,xi+1)]
  rows.append({"engine":e,"symbol":sym,"signal_time":signal,"entry_time":int(z.open_time.iloc[ei]),"exit_time":ex,
   "entry_ref":ref,"entry_fill":fill,"exit_ref":xp,"stop_price":sp,"stop_pct":max(1e-9,(fill-sp)/fill),
   "reason":reason,"marks":marks})
 return pd.DataFrame(rows)

def score(closed,t,lb=6):
 mo=pd.to_datetime(t,unit="ms",utc=True).to_period("M");st=int((mo-lb).start_time.tz_localize("UTC").timestamp()*1000)
 out={}
 for e,d in closed.items():
  q=d[(d.exit_time<=t)&(d.exit_time>=st)]
  out[e]=float(q.net_pct.mean()) if len(q) else 0.
 return out

def chronological_events(F):
 # At an equal timestamp: mark -> funding -> close -> open.
 # Existing positions pay funding at their exit timestamp; a new open does not.
 ev=[];bounds={}
 for e,d in F.items():
  for i,r in d.iterrows():
   ev.append((int(r.entry_time),3,e,i))
   for t,p in r.marks:ev.append((int(t),0,e,i,float(p)))
   ev.append((int(r.exit_time),2,e,i))
   lo,hi=bounds.get(str(r.symbol),(int(r.entry_time),int(r.exit_time)))
   bounds[str(r.symbol)]=(min(lo,int(r.entry_time)),max(hi,int(r.exit_time)))
 for sym,(lo,hi) in bounds.items():
  fd=funding(sym)
  for r in fd[(fd.fundingTime>lo)&(fd.fundingTime<=hi)].itertuples():
   ev.append((int(r.fundingTime),1,sym,0,float(r.fundingRate)))
 return sorted(ev,key=lambda x:(x[0],x[1],x[2],x[3]))

def main():
 ce,r1,r15,g1,g15=frozen_entries()
 cfg={"CORE":("4h",14400000,30,6.,ce),"REV1H":("1h",3600000,g1[2],g1[1],r1),"REV15M":("15m",900000,g15[2],g15[1],r15)}
 F={e:rebuild(en,e,iv,bar,hold,tp,STOP[e]) for e,(iv,bar,hold,tp,en) in cfg.items()}
 # Precompute gross/net for causal regime scoring using actual fees+slippage+historical funding at unit notional.
 for e,d in F.items():
  nets=[]
  for r in d.itertuples():
   fd=funding(r.symbol); q=fd[(fd.fundingTime>r.entry_time)&(fd.fundingTime<=r.exit_time)]
   fr=float(q.fundingRate.sum()) if len(q) else 0.
   gross=float(r.exit_ref/r.entry_fill-1); nets.append(gross-2*TAKER-fr)
  d["net_pct"]=nets
 ev=chronological_events(F)
 L=PortfolioLedger(START_CAP,1.0,MAX_STOP_RISK);active={};acc={e:0 for e in F};rej={};peak=START_CAP
 for item in ev:
  t,typ,e,i,*rest=item
  if typ==1:
   if any(p.symbol==e for p in L.positions.values()):L.funding_event(t,e,float(rest[0]))
   continue
  r=F[e].iloc[i];key=f"{e}:{i}"
  if typ==0:
   if key in active:L.mark(t,str(r.symbol),float(rest[0]))
   continue
  if typ==2:
   if key in active:
    # exit reference receives adverse slippage.
    xp=float(r.exit_ref)*(1-SLIP)
    L.close(t,key,xp,exit_fee_rate=TAKER,reason=str(r.reason),reference_price=float(r.exit_ref))
    del active[key]
   continue
  sv=score(F,t);vs=np.array(list(sv.values()),float);hot=(len(vs)>0 and vs.mean()>0 and sum(v>0 for v in sv.values())>=2);mult=1.5 if hot else .5
  if sv.get(e,0)<0 and not(e=="CORE" and not hot):rej["regime"]=rej.get("regime",0)+1;continue
  if sum(1 for x in active if x.startswith(e+":"))>=MAXPOS[e]:rej["engine_maxpos"]=rej.get("engine_maxpos",0)+1;continue
  if any(p.symbol==str(r.symbol) for p in L.positions.values()):rej["symbol_held"]=rej.get("symbol_held",0)+1;continue
  eq=L.equity();desired=min(eq*PER,eq*RISK[e]*mult/max(float(r.stop_pct),1e-12));notional=min(desired,max(0,L.available_collateral()))
  if notional<eq*.005:rej["collateral_or_min_size"]=rej.get("collateral_or_min_size",0)+1;continue
  qty=notional/float(r.entry_fill)
  ok,why=L.open(t,key,e,str(r.symbol),1,qty,float(r.entry_fill),float(r.stop_price),TAKER,TAKER,float(r.entry_ref))
  if not ok:rej[why]=rej.get(why,0)+1;continue
  active[key]=True;acc[e]+=1
 # chronological event invariant: all positions should have closed.
 L.assert_reconciles();L.write_jsonl(OUT/"ledger.jsonl")
 m=L.manifest();ret=m["final"]["equity"]/START_CAP-1
 s={"version":"R16.29.1","status":"TECHNICALLY_INVALID","blocking_reasons":["CORE entries still originate from Spot","full integrity and OOS gates pending"],"event_priority":["MARK","FUNDING","CLOSE","OPEN"],"venue":"Binance USD-M Futures","dataset_manifest_sha256":"a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041",
 "frozen":{"stops":STOP,"rev1h":FROZEN_REV1H,"rev15m":FROZEN_REV15M,"config_sha256":FROZEN_CONFIG_SHA256},"accepted":acc,"rejections":rej,"ledger":m,"return":ret,
 "costs":{"commission_rate_each_side":TAKER,"slippage_each_side":SLIP,"funding":"historical archive"}}
 (OUT/"summary.json").write_text(json.dumps(s,indent=2,default=float));print(json.dumps(s,indent=2,default=float))
if __name__=="__main__":main()
