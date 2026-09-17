#!/usr/bin/env python3
import csv, io, json, gzip, re, time, urllib.request, urllib.error, zipfile, pathlib, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

VISION='https://data.binance.vision/data'
CMC='https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical'
H=3600000; H4=4*H
HDR={'User-Agent':'Mozilla/5.0 V09-PIT-Research/1.0','Accept':'*/*'}
OUT=pathlib.Path('v09_vision'); OUT.mkdir(exist_ok=True)
CACHE=pathlib.Path('/tmp/v09_vision_cache'); CACHE.mkdir(exist_ok=True)
WINDOWS=[
 ('2026-02','2026-02-01','2026-01-25','2026-02-01','2026-03-01'),
 ('2026-03','2026-03-01','2026-02-22','2026-03-01','2026-03-29'),
 ('2026-04','2026-04-05','2026-03-29','2026-04-05','2026-05-03'),
 ('2026-05','2026-05-03','2026-04-26','2026-05-03','2026-05-31'),
 ('2026-06','2026-06-07','2026-05-31','2026-06-07','2026-07-05'),
 ('2026-07','2026-07-05','2026-06-28','2026-07-05','2026-08-02')]
ALIASES={'SHIB':['1000SHIBUSDT'],'BONK':['1000BONKUSDT'],'FLOKI':['1000FLOKIUSDT'],'LUNC':['1000LUNCUSDT'],'XEC':['1000XECUSDT'],'BTTC':['1000BTTCUSDT'],'SATS':['1000SATSUSDT'],'PEPE':['1000PEPEUSDT'],'CHEEMS':['1000CHEEMSUSDT'],'CAT':['1000CATUSDT'],'WHY':['1000WHYUSDT'],'RATS':['1000RATSUSDT'],'MOG':['1000000MOGUSDT'],'BOB':['1000000BOBUSDT'],'BABYDOGE':['1MBABYDOGEUSDT'],'MOGCOIN':['1000000MOGUSDT']}

def ms(s): return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp()*1000)
def month_keys(a,b):
 d=dt.datetime.fromtimestamp(a/1000,dt.timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0); out=[]
 while int(d.timestamp()*1000)<b:
  out.append((d.year,d.month)); d=(d.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
 return out

def http_bytes(url):
 req=urllib.request.Request(url,headers=HDR)
 with urllib.request.urlopen(req,timeout=45) as r: return r.read()
def http_json(url): return json.loads(http_bytes(url))
def zip_csv(url, cache_key):
 p=CACHE/(re.sub(r'[^A-Za-z0-9_.-]','_',cache_key)+'.zip')
 if not p.exists():
  try: p.write_bytes(http_bytes(url))
  except urllib.error.HTTPError as e:
   if e.code==404: return None
   raise
 try:
  with zipfile.ZipFile(p) as z:
   name=z.namelist()[0]; text=z.read(name).decode('utf-8-sig','replace')
 except Exception:
  p.unlink(missing_ok=True); raise
 rows=list(csv.reader(io.StringIO(text)))
 return rows

def norm_ts(x):
 n=int(float(x)); return n//1000 if n>100_000_000_000_000 else n

def future_month(symbol,kind,interval,y,m):
 mm=f'{m:02d}'
 if kind=='fundingRate':
  fn=f'{symbol}-fundingRate-{y}-{mm}.zip'; url=f'{VISION}/futures/um/monthly/fundingRate/{symbol}/{fn}'
 else:
  fn=f'{symbol}-{interval}-{y}-{mm}.zip'; url=f'{VISION}/futures/um/monthly/{kind}/{symbol}/{interval}/{fn}'
 return zip_csv(url,f'um_{kind}_{symbol}_{interval}_{y}_{mm}')
def spot_month(symbol,interval,y,m):
 mm=f'{m:02d}'; fn=f'{symbol}-{interval}-{y}-{mm}.zip'; url=f'{VISION}/spot/monthly/klines/{symbol}/{interval}/{fn}'
 return zip_csv(url,f'spot_{symbol}_{interval}_{y}_{mm}')

def parse_k(rows,a,b,spot=False):
 if rows is None: return []
 out=[]
 for r in rows:
  if not r: continue
  try: t=norm_ts(r[0])
  except: continue
  if a<=t<b:
   rr=list(r); rr[0]=t; rr[6]=norm_ts(rr[6]); out.append(rr)
 by={int(r[0]):r for r in out}; return [by[x] for x in sorted(by)]
def load_future(symbol,kind,interval,a,b):
 allr=[]
 for y,m in month_keys(a,b):
  z=future_month(symbol,kind,interval,y,m)
  if z: allr.extend(parse_k(z,a,b))
 by={int(r[0]):r for r in allr}; return [by[x] for x in sorted(by)]
def load_spot(symbol,interval,a,b):
 allr=[]
 for y,m in month_keys(a,b):
  z=spot_month(symbol,interval,y,m)
  if z: allr.extend(parse_k(z,a,b,True))
 by={int(r[0]):r for r in allr}; return [by[x] for x in sorted(by)]
def load_funding(symbol,a,b):
 allr=[]; header=None
 for y,m in month_keys(a,b):
  z=future_month(symbol,'fundingRate','-',y,m)
  if not z: continue
  if z and z[0] and not str(z[0][0]).replace('.','',1).isdigit():
   header=[str(x).strip() for x in z[0]]; z=z[1:]
  for r in z:
   if not r: continue
   try: t=norm_ts(r[0])
   except: continue
   if a<=t<b: allr.append(r)
 return {'header':header,'rows':allr}
def complete(rows,a,b,step): return [int(r[0]) for r in rows]==list(range(a,b,step))
def candidates(s):
 x=re.sub(r'[^A-Z0-9]','',s.upper()); return list(dict.fromkeys([x+'USDT']+ALIASES.get(x,[]))) if x else []
def cmc(date):
 z=http_json(f'{CMC}?date={date}&start=1&limit=300&convert=USD')['data']
 return [{'rank':int(x['cmcRank']),'cmc_symbol':str(x.get('symbol') or '').upper(),'name':x.get('name'),'cmc_id':x.get('id')} for x in z[:300]]

def four(rows): return [[int(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5]),float(r[7])] for r in rows]
def ema(vals,n):
 a=2/(n+1); out=[]; e=None
 for v in vals: e=v if e is None else a*v+(1-a)*e; out.append(e)
 return out
def feature_map(F):
 out={}; tr=[]; atr=None
 for i,b in enumerate(F):
  if i==0: continue
  tr.append(max(b[2]-b[3],abs(b[2]-F[i-1][4]),abs(b[3]-F[i-1][4])))
  if i==14: atr=sum(tr[-14:])/14
  elif i>14: atr=(atr*13+tr[-1])/14
  if i<20 or atr is None or atr<=0: continue
  prev=F[i-20:i]; av=sum(x[5] for x in prev)/20; vr=b[5]/av if av else 0
  side=1 if b[4]>max(x[2] for x in prev) else -1 if b[4]<min(x[3] for x in prev) else 0
  if vr<1.5: side=0
  out[b[0]+H4]={'side':side,'vr':vr,'quote24':sum(x[6] for x in F[max(0,i-5):i+1]),'atr':atr,'close':b[4]}
 return out
def rs_signals(C,B):
 cf=feature_map(C); cc={x[0]+H4:x[4] for x in C}; bc={x[0]+H4:x[4] for x in B}; times=sorted(set(cc)&set(bc)); ratio={t:cc[t]/bc[t] for t in times if bc[t]>0}; pos={t:i for i,t in enumerate(times)}
 cl=[x[4] for x in B]; e12=ema(cl,12); e26=ema(cl,26); regime={x[0]+H4:(0 if i<25 else (1 if cl[i]>e12[i]>e26[i] else -1 if cl[i]<e12[i]<e26[i] else 0)) for i,x in enumerate(B)}
 out=[]
 for t,f in sorted(cf.items()):
  side=f['side']; i=pos.get(t,-1)
  if not side or i<20 or regime.get(t)!=side or f['quote24']<5_000_000: continue
  prev=[ratio[x] for x in times[i-20:i] if x in ratio]
  if len(prev)<20: continue
  r=ratio[t]
  if side==1 and r<=max(prev): continue
  if side==-1 and r>=min(prev): continue
  out.append({'time':t,'side':side,'volume_multiple':f['vr'],'quote24':f['quote24'],'atr':f['atr'],'close':f['close'],'rs_ratio':r})
 return out

def probe(row,a,b):
 for s in candidates(row['cmc_symbol']):
  try:
   z=load_future(s,'klines','4h',a,b)
   if complete(z,a,b,H4): return row,s,'full',z
   ts=[int(x[0]) for x in z]
   if ts and min(ts)<=a+7*24*H and max(ts)<b-H4: return row,s,'partial',z
  except Exception as e: pass
 return row,None,'none',[]

manifest=[]
for wid,snap,warm_s,start_s,end_s in WINDOWS:
 warm,start,end=ms(warm_s),ms(start_s),ms(end_s); rows=cmc(snap); target=[r for r in rows if 101<=r['rank']<=300]
 btc=load_future('BTCUSDT','klines','4h',warm,end)
 if not complete(btc,warm,end,H4): raise SystemExit(f'{wid}: BTC 4h incomplete')
 B=four(btc); mapped=[]; partial=[]
 with ThreadPoolExecutor(max_workers=20) as ex:
  fs=[ex.submit(probe,r,warm,end) for r in target]
  for i,f in enumerate(as_completed(fs),1):
   r,s,status,z=f.result()
   if status=='full': mapped.append((r,s,z))
   elif status=='partial': partial.append({**r,'symbol':s})
   if i%25==0: print(wid,'probe',i,'/200',flush=True)
 mapped.sort(key=lambda q:q[0]['rank']); pres={}; sig=[]
 for r,s,z in mapped:
  got=[x for x in rs_signals(four(z),B) if start<=x['time']<end]; pres[s]=got
  sig += [{**x,'symbol':s,'rank':r['rank'],'name':r['name']} for x in got]
 signal_symbols=sorted({x['symbol'] for x in sig}|{'BTCUSDT'})
 exact={}
 for i,s in enumerate(signal_symbols,1):
  f1=load_future(s,'klines','1h',warm,end); mk=load_future(s,'markPriceKlines','1h',warm,end); fr=load_funding(s,warm,end)
  exact[s]={'future_1h':f1,'mark_1h':mk,'funding_raw':fr}
  print(wid,'exact',i,'/',len(signal_symbols),s,len(f1),len(mk),len(fr['rows']),flush=True)
 fx=load_spot('USDTBRL','1h',warm,end)
 payload={'window_id':wid,'snapshot':snap,'warmup':warm,'start':start,'end':end,'target_count':len(target),'mapped':[{'rank':r['rank'],'cmc_symbol':r['cmc_symbol'],'name':r['name'],'symbol':s} for r,s,z in mapped],'critical_partial':partial,'signals':sig,'prescreen':pres,'signal_symbols':signal_symbols,'exact':exact,'fx_1h':fx,'source':'official_binance_data_vision_monthly_archives'}
 p=OUT/f'{wid}_101_300.json.gz'
 with gzip.open(p,'wt',encoding='utf-8') as f: json.dump(payload,f,separators=(',',':'))
 m={'window':wid,'mapped':len(mapped),'partial':len(partial),'signals':len(sig),'signal_symbols':signal_symbols,'artifact_bytes':p.stat().st_size}; manifest.append(m); print('DONE',m,flush=True)
pathlib.Path(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(manifest,indent=2))
