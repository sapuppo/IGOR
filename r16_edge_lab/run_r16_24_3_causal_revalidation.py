#!/usr/bin/env python3
"""R16.24.3 causal revalidation of frozen R16.24.2 geometry.
Fixes known look-ahead, source-geometry, exposure/cost and open-risk defects.
This stage measures surviving edge; it does not optimize return.
"""
from __future__ import annotations
from pathlib import Path
import importlib.util,json,math,numpy as np,pandas as pd
START_CAP=10000.;PER=.40
MONTHS=pd.period_range("2021-01","2026-06",freq="M").astype(str)
RISK={"CORE":.0075,"REV1H":.01,"REV15M":.015};MAXPOS={e:5 for e in RISK}
STOP={"CORE":3.0,"REV1H":3.0,"REV15M":1.5}
COST={"base":(.0032,.0001),"stress":(.0042,.0002)}
OUT=Path("r16_edge_lab/r16_24_3_causal_revalidation");OUT.mkdir(parents=True,exist_ok=True)
INP=Path("r16_edge_lab/r16_243_inputs");PRE=Path("r16_edge_lab/pre2024_history");PRE15=Path("r16_edge_lab/pre2024_history_15m");POST=Path("r15_regime_lab/history")
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
R14=mod("r16_edge_lab/run_r16_14_extreme_reversion.py","r14");R16=mod("r16_edge_lab/run_r16_16_intraday_reversion.py","r16")
def ff(root,name):
 h=list(root.rglob(name))
 if not h:raise FileNotFoundError(f"{name} under {root}")
 return h[0]
def sel(root):
 x=json.loads(ff(root,"summary.json").read_text()).get("selected",{}).get("LONG")
 if not x:raise RuntimeError(f"no selected LONG in {root}")
 return x
def geom(s):
 v=str(s).strip().strip("()").split(",");return float(v[0]),float(v[1]),int(float(v[2]))
def first3(x,ch):
 """Causal replacement for hindsight top-3 ranking over a completed future cluster."""
 if x.empty:return x.copy()
 x=x.sort_values(["signal_time","symbol"]).copy();cnt={};last={};keep=[];w=int(ch*3600000)
 for i,r in x.iterrows():
  cl=int(r.signal_time)//w*w
  if cnt.get(cl,0)>=3 or int(r.entry_time)<=last.get(str(r.symbol),-1):continue
  keep.append(i);cnt[cl]=cnt.get(cl,0)+1;last[str(r.symbol)]=int(r.exit_time)
 return x.loc[keep].sort_values(["entry_time","symbol"]).reset_index(drop=True)
def rev1():
 c=sel(INP/"rev1h");g=geom(c["geom"]);F={s:R14.load_pair(PRE,POST,s) for s in R14.SYMBOLS}
 x=R14.raw_events(F,"LONG",g,0.,0.);m=(x.ret6<=-float(c["move"]))&(x.volz48>=float(c["volz"]))&(x.rsi14<=35)&(x.body_pos>=float(c["body"]))
 return first3(x[m].copy(),int(c["cluster_h"])),c,g
def rev15():
 c=sel(INP/"rev15m");g=geom(c["geom"]);hb=int(c["horizon_bars"]);F={s:R16.load(s) for s in R16.SYMBOLS}
 x=R16.raw_for(F,"LONG",hb,g,0.,0.);m=(x.move_ret<=-float(c["move"]))&(x.volz>=float(c["volz"]))&(x.rsi<=35)&(x.body>=float(c["body"]))
 return first3(x[m].copy(),int(c["cluster_h"])),c,g
def core():
 x=pd.read_csv(ff(INP/"core","base_core_trades.csv.gz"));return x[["symbol","entry_time"]].drop_duplicates().sort_values(["entry_time","symbol"])
def px(sym,iv):
 roots=[PRE15,POST] if iv=="15m" else [PRE,POST];fs=[]
 for root in roots:
  p=root/iv/f"{sym}.csv.gz"
  if p.exists():fs.append(pd.read_csv(p,usecols=["open_time","open","high","low","close"]))
 if not fs:return pd.DataFrame()
 x=pd.concat(fs).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
 for c in ["open_time","open","high","low","close"]:x[c]=pd.to_numeric(x[c],errors="coerce")
 pc=x.close.shift();tr=pd.concat([x.high-x.low,(x.high-pc).abs(),(x.low-pc).abs()],axis=1).max(axis=1);x["atr"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean();return x
def rebuild(ent,e,iv,bar,hold,target,stop,cost,fund):
 cache={};rows=[]
 for r in ent.sort_values(["entry_time","symbol"]).itertuples(index=False):
  sym=str(r.symbol)
  if sym not in cache:cache[sym]=px(sym,iv)
  z=cache[sym]
  if z.empty:continue
  a=z.open_time.to_numpy(np.int64);ei=int(np.searchsorted(a,int(r.entry_time)))
  if ei>=len(z) or int(a[ei])!=int(r.entry_time):continue
  atr=float(z.atr.iloc[max(0,ei-1)]);en=float(z.open.iloc[ei])
  if not np.isfinite(atr) or atr<=0 or en<=0:continue
  sp=en-stop*atr;tp=en+target*atr;end=min(ei+hold-1,len(z)-1);xp=float(z.close.iloc[end]);xi=end;reason="TIME"
  for j in range(ei,end+1):
   hs=float(z.low.iloc[j])<=sp;ht=float(z.high.iloc[j])>=tp
   if hs and ht:xp=sp;xi=j;reason="STOP_AMBIGUOUS";break
   if hs:xp=sp;xi=j;reason="STOP";break
   if ht:xp=tp;xi=j;reason="TARGET";break
  ex=int(z.open_time.iloc[xi])+bar;hours=max(bar/3600000,(ex-int(r.entry_time))/3600000);fd=math.ceil(hours/8)*fund
  marks=[(int(z.open_time.iloc[j])+bar,float(z.close.iloc[j])/en-1) for j in range(ei,xi+1)]
  rows.append({"engine":e,"symbol":sym,"entry_time":int(r.entry_time),"exit_time":ex,"stop_pct":stop*atr/en,
   "gross_pct":xp/en-1,"trade_cost":cost,"funding_drag":fd,"net_pct":xp/en-1-cost-fd,"reason":reason,"marks":marks})
 return pd.DataFrame(rows)
def scores(F,t,lb=6):
 mo=pd.to_datetime(t,unit="ms",utc=True).to_period("M");st=int((mo-lb).start_time.tz_localize("UTC").timestamp()*1000);o={}
 for e,d in F.items():
  q=d[(d.exit_time<=t)&(d.exit_time>=st)];o[e]=float(q.net_pct.mean()) if len(q) else 0.
 return o
def sim(F,hot=1.5,cold=.5,gh=1.,gc=.6,brake=.10):
 E=[]
 for e,d in F.items():
  for i,r in d.iterrows():E.append((int(r.entry_time),e,i))
 pri={"CORE":0,"REV15M":1,"REV1H":2};E.sort(key=lambda q:(q[0],pri[q[1]],str(F[q[1]].iloc[q[2]].symbol)))
 marks={}
 for e,d in F.items():
  for i,r in d.iterrows():
   for t,v in r.marks:marks.setdefault(int(t),[]).append((e,i,float(v)))
   marks.setdefault(int(r.exit_time),[])
 times=sorted(set([q[0] for q in E]+list(marks)));be={}
 for q in E:be.setdefault(q[0],[]).append(q)
 realized=START_CAP;peak=START_CAP;gross=0.;active={};held=set();acc={e:0 for e in F}
 rej={k:0 for k in ["regime","engine_maxpos","symbol_held","gross_cap","min_size"]};monthly={};maxdd=maxrisk=maxgross=0.
 def mtm():
  nonlocal peak,maxdd,maxrisk,maxgross
  un=sum(p["notional"]*p.get("mark",0.) for p in active.values());val=realized+un;risk=sum(p["risk"] for p in active.values())
  peak=max(peak,val);maxdd=max(maxdd,1-val/max(peak,1e-12));maxrisk=max(maxrisk,risk/max(val,1e-12));maxgross=max(maxgross,gross/max(val,1e-12));return val
 for t in times:
  for k in [k for k,p in active.items() if p["exit"]<=t]:
   p=active.pop(k);pnl=p["notional"]*p["net"];realized+=pnl;gross-=p["notional"];held.discard(p["symbol"])
   m=str(pd.to_datetime(p["exit"],unit="ms",utc=True).to_period("M"));monthly[m]=monthly.get(m,0.)+pnl
  for e,i,v in marks.get(t,[]):
   if (e,i) in active:active[(e,i)]["mark"]=v
  val=mtm()
  for _,e,i in be.get(t,[]):
   r=F[e].iloc[i];sv=scores(F,t);vs=np.array(list(sv.values()),float);hotreg=(len(vs)>0 and vs.mean()>0 and sum(v>0 for v in sv.values())>=2)
   mult=hot if hotreg else cold;cap=min(1.,gh if hotreg else gc)
   if sv.get(e,0)<0 and not(e=="CORE" and not hotreg):rej["regime"]+=1;continue
   dd=1-val/max(peak,1e-12)
   if dd>=brake:mult*=.5
   if sum(1 for p in active.values() if p["engine"]==e)>=MAXPOS[e]:rej["engine_maxpos"]+=1;continue
   if str(r.symbol) in held:rej["symbol_held"]+=1;continue
   desired=min(val*PER,val*RISK[e]*mult/max(float(r.stop_pct),1e-9));no=min(desired,max(0.,val*cap-gross))
   if no<=0:rej["gross_cap"]+=1;continue
   if no<val*.005:rej["min_size"]+=1;continue
   active[(e,i)]={"engine":e,"symbol":str(r.symbol),"exit":int(r.exit_time),"notional":no,"risk":no*float(r.stop_pct),"net":float(r.net_pct),"mark":0.}
   held.add(str(r.symbol));gross+=no;acc[e]+=1;val=mtm()
 vals=[];eq=START_CAP
 for m in MONTHS:
  p=monthly.get(m,0.);vals.append(p/eq if eq>0 else -1);eq+=p
 a=np.array(vals);am=a[a!=0];years={}
 for m,r in zip(MONTHS,a):years[m[:4]]=years.get(m[:4],1)*(1+r)
 years={y:v-1 for y,v in years.items()}
 def period(start):
  q=a[[i for i,m in enumerate(MONTHS) if m>=start]];ret=float(np.prod(1+q)-1);cm=float((1+ret)**(1/len(q))-1) if len(q) and ret>-1 else -1
  return {"return":ret,"compound_monthly":cm,"monthly_mean":float(q.mean()),"monthly_median":float(np.median(q)),"positive_month":float((q>0).mean()),"worst":float(q.min())}
 return {"return":realized/START_CAP-1,"dd_mtm":maxdd,"monthly_mean":float(a.mean()),"monthly_median":float(np.median(a)),
  "active_month_median":float(np.median(am)) if len(am) else 0.,"positive_month":float((a>0).mean()),"worst":float(a.min()),"best":float(a.max()),
  "years":years,"accepted":acc,"rejections":rej,"max_open_stop_risk_fraction":maxrisk,"max_gross_exposure_fraction":maxgross,"period_2022_2026":period("2022-01")}
def main():
 r1,c1,g1=rev1();r15,c15,g15=rev15();ce=core()
 cfg={"CORE":("4h",4*3600000,30,6.,ce),"REV1H":("1h",3600000,g1[2],g1[1],r1[["symbol","entry_time"]]),
      "REV15M":("15m",15*60000,g15[2],g15[1],r15[["symbol","entry_time"]])}
 res={};counts={}
 for scen,(cost,fund) in COST.items():
  F={}
  for e,(iv,bar,hold,tp,en) in cfg.items():
   F[e]=rebuild(en,e,iv,bar,hold,tp,STOP[e],cost,fund);counts[f"{scen}_{e}_candidates"]=len(F[e])
  res[scen]=sim(F)
  for e,d in F.items():d.drop(columns=["marks"]).to_csv(OUT/f"{scen}_{e.lower()}_trades.csv.gz",index=False,compression="gzip")
 s={"version":"R16.24.3","purpose":"causal revalidation of frozen R16.24.2; no return optimization","frozen_stops":STOP,
  "source_geometry":{"REV1H":g1,"REV15M":g15},"source_selected_names":{"REV1H":c1.get("name"),"REV15M":c15.get("name")},
  "execution":"USD-M futures; no leverage; <=100% gross; conservative funding every 8h",
  "fixes":["closed-trades-only regime","sequential first-3 reversal selection","source target/hold restored","MTM open-position drawdown","open stop risk measured","100% gross cap","consistent funding"],
  "trade_counts":counts,"base":res["base"],"stress":res["stress"],"status":"revalidated_not_promoted","target_20pct_monthly_is_not_a_selection_gate":True}
 (OUT/"summary.json").write_text(json.dumps(s,indent=2,default=float),encoding="utf-8");print(json.dumps(s,indent=2,default=float))
if __name__=="__main__":main()
