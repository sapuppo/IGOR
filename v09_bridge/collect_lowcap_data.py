#!/usr/bin/env python3
import json,gzip,time,urllib.request,urllib.parse,urllib.error,pathlib,datetime as dt,math,re
from concurrent.futures import ThreadPoolExecutor,as_completed

FAPI='https://fapi.binance.com'; SPOT='https://api.binance.com'
CMC='https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listings/historical'
H=3600000; FH=4*H
WINDOWS=[
 {'id':'2026-02','snapshot':'2026-02-01','warmup':'2026-01-25','start':'2026-02-01','end':'2026-03-01'},
 {'id':'2026-03','snapshot':'2026-03-01','warmup':'2026-02-22','start':'2026-03-01','end':'2026-03-29'},
 {'id':'2026-04','snapshot':'2026-04-05','warmup':'2026-03-29','start':'2026-04-05','end':'2026-05-03'},
 {'id':'2026-05','snapshot':'2026-05-03','warmup':'2026-04-26','start':'2026-05-03','end':'2026-05-31'},
 {'id':'2026-06','snapshot':'2026-06-07','warmup':'2026-05-31','start':'2026-06-07','end':'2026-07-05'},
 {'id':'2026-07','snapshot':'2026-07-05','warmup':'2026-06-28','start':'2026-07-05','end':'2026-08-02'}]
ALIASES={'SHIB':['1000SHIBUSDT'],'BONK':['1000BONKUSDT'],'FLOKI':['1000FLOKIUSDT'],'LUNC':['1000LUNCUSDT'],'XEC':['1000XECUSDT'],'BTTC':['1000BTTCUSDT'],'SATS':['1000SATSUSDT'],'PEPE':['1000PEPEUSDT'],'CHEEMS':['1000CHEEMSUSDT'],'CAT':['1000CATUSDT'],'WHY':['1000WHYUSDT'],'RATS':['1000RATSUSDT'],'MOG':['1000000MOGUSDT'],'BOB':['1000000BOBUSDT'],'BABYDOGE':['1MBABYDOGEUSDT']}
CFG={'breakout_bars':20,'volume_multiple':1.5,'atr_bars':14,'min_prior_24h_quote_volume':5000000}
HDR={'User-Agent':'Mozilla/5.0 V09-validation-data-only/1.0','Accept':'application/json'}
OUT=pathlib.Path('v09_market_data'); OUT.mkdir(exist_ok=True)

def ms(s): return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp()*1000)
def get(url,retries=6):
 last=None
 for i in range(retries):
  try:
   req=urllib.request.Request(url,headers=HDR)
   with urllib.request.urlopen(req,timeout=45) as r: return json.loads(r.read())
  except urllib.error.HTTPError as e:
   last=RuntimeError(f'HTTP {e.code} {url}: '+e.read().decode('utf-8','replace')[:300])
   if e.code in (418,429): time.sleep(5*(i+1)); continue
   raise last
  except Exception as e:
   last=e; time.sleep(1.5*(i+1))
 raise RuntimeError(f'GET failed {url}: {last}')
def api(base,path,params=None):
 u=base+path
 if params: u+='?'+urllib.parse.urlencode(params)
 return get(u)
def rows(symbol,interval,a,b,mark=False):
 path='/fapi/v1/markPriceKlines' if mark else '/fapi/v1/klines'; out=[]; cur=a; step=H if interval=='1h' else FH
 while cur<b:
  z=api(FAPI,path,{'symbol':symbol,'interval':interval,'startTime':cur,'endTime':b-1,'limit':1500})
  if not z: break
  out+=z; nxt=int(z[-1][0])+step
  if nxt<=cur: break
  cur=nxt
  if len(z)<1500: break
 by={int(x[0]):x for x in out if a<=int(x[0])<b}
 return [by[k] for k in sorted(by)]
def funding(symbol,a,b):
 z=api(FAPI,'/fapi/v1/fundingRate',{'symbol':symbol,'startTime':a,'endTime':b-1,'limit':1000})
 return [x for x in z if a<=int(x['fundingTime'])<b]
def candidates(sym):
 s=re.sub(r'[^A-Z0-9]','',sym.upper()); return list(dict.fromkeys([s+'USDT']+ALIASES.get(s,[]))) if s else []
def full(z,a,b): return [int(x[0]) for x in z]==list(range(a,b,FH))
def p4(z,a,b):
 if not full(z,a,b): raise ValueError('bad 4h')
 return [[int(r[0]),*map(float,r[1:6]),float(r[7])] for r in z]
def features(four):
 out={}; tr=[]; atr=None; n=CFG['atr_bars']; look=CFG['breakout_bars']
 for i,b in enumerate(four):
  if i==0: continue
  tr.append(max(b[2]-b[3],abs(b[2]-four[i-1][4]),abs(b[3]-four[i-1][4])))
  if i==n: atr=sum(tr[-n:])/n
  elif i>n: atr=(atr*(n-1)+tr[-1])/n
  if i<look or atr is None or atr<=0: continue
  prev=four[i-look:i]; av=sum(x[5] for x in prev)/look; vr=b[5]/av if av>0 else 0
  side=1 if b[4]>max(x[2] for x in prev) else -1 if b[4]<min(x[3] for x in prev) else 0
  if vr<CFG['volume_multiple']: side=0
  out[b[0]+FH]={'side':side,'ratio':vr,'quote24':sum(x[6] for x in four[max(0,i-5):i+1])}
 return out
def ema(vals,span):
 a=2/(span+1); e=None; out=[]
 for v in vals: e=v if e is None else a*v+(1-a)*e; out.append(e)
 return out
def signals(coin,btc):
 ft=features(coin); cc={b[0]+FH:b[4] for b in coin}; bc={b[0]+FH:b[4] for b in btc}; times=sorted(set(cc)&set(bc)); ratios={t:cc[t]/bc[t] for t in times if bc[t]>0}; rt=sorted(ratios); pos={t:i for i,t in enumerate(rt)}
 closes=[b[4] for b in btc]; ef=ema(closes,12); es=ema(closes,26); regime={}
 for i,b in enumerate(btc):
  t=b[0]+FH; regime[t]=0 if i<25 else (1 if closes[i]>ef[i]>es[i] else -1 if closes[i]<ef[i]<es[i] else 0)
 out=[]
 for t in sorted(ft):
  f=ft[t]; side=f['side']; i=pos.get(t,-1)
  if not side or regime.get(t)!=side or i<20 or f['quote24']<CFG['min_prior_24h_quote_volume']: continue
  prev=[ratios[x] for x in rt[i-20:i]]; r=ratios[t]
  if side==1 and r<=max(prev): continue
  if side==-1 and r>=min(prev): continue
  out.append({'time':t,'side':side,'volume_multiple':f['ratio'],'quote24':f['quote24'],'rs_ratio':r})
 return out

def cmc(date):
 z=get(f'{CMC}?date={date}&start=1&limit=300&convert=USD'); d=z['data']
 return [{'rank':int(x['cmcRank']),'cmc_id':x.get('id'),'name':x.get('name'),'cmc_symbol':str(x.get('symbol') or '').upper(),'slug':x.get('slug')} for x in d[:300]]

def probe(row,a,b):
 for s in candidates(row['cmc_symbol']):
  try:
   z=rows(s,'4h',a,b)
   if full(z,a,b): return {'row':row,'symbol':s,'status':'full','bars4':z}
   ts=[int(x[0]) for x in z]
   if ts and min(ts)<=a+7*24*H and max(ts)<b-FH: return {'row':row,'symbol':s,'status':'partial_mid_window_or_gap','bars4':z}
  except Exception: pass
 return {'row':row,'symbol':None,'status':'none','bars4':[]}

spec_all=api(FAPI,'/fapi/v1/exchangeInfo'); specmap={x['symbol']:x for x in spec_all.get('symbols',[])}
manifest=[]
for w in WINDOWS:
 warm,start,end=ms(w['warmup']),ms(w['start']),ms(w['end']); snap=cmc(w['snapshot']); target=[x for x in snap if 101<=x['rank']<=300]
 btc4=rows('BTCUSDT','4h',warm,end); btc=p4(btc4,warm,end)
 mapped=[]; partial=[]
 with ThreadPoolExecutor(max_workers=8) as ex:
  futs={ex.submit(probe,r,warm,end):r for r in target}
  for n,f in enumerate(as_completed(futs),1):
   q=f.result();
   if q['status']=='full': mapped.append(q)
   elif q['status'].startswith('partial'): partial.append({**q['row'],'binance_symbol':q['symbol'],'status':q['status']})
   if n%25==0: print(w['id'],'probe',n,'/200',flush=True)
 mapped.sort(key=lambda x:x['row']['rank']); pres={}; sig=[]
 for q in mapped:
  got=[x for x in signals(p4(q['bars4'],warm,end),btc) if start<=x['time']<end]; pres[q['symbol']]=got
  for x in got: sig.append({**x,'symbol':q['symbol'],'rank':q['row']['rank'],'name':q['row']['name']})
 syms=sorted({x['symbol'] for x in sig}|{'BTCUSDT'}); exact={}
 for i,s in enumerate(syms,1):
  exact[s]={'fut_1h':rows(s,'1h',warm,end),'mark_1h':rows(s,'1h',warm,end,True),'funding':funding(s,warm,end),'spec':specmap.get(s)}
  print(w['id'],'exact',i,'/',len(syms),s,flush=True)
 fx=[]; cur=warm
 while cur<end:
  z=api(SPOT,'/api/v3/klines',{'symbol':'USDTBRL','interval':'1h','startTime':cur,'endTime':end-1,'limit':1000})
  if not z: break
  fx+=z; nxt=int(z[-1][0])+H
  if nxt<=cur: break
  cur=nxt
  if len(z)<1000: break
 payload={'window':w,'snapshot_rows':snap,'target_rows':target,'mapped':[{'rank':q['row']['rank'],'name':q['row']['name'],'cmc_symbol':q['row']['cmc_symbol'],'symbol':q['symbol']} for q in mapped],'critical_partial':partial,'prescreen':pres,'prescreen_signals':sig,'btc4':btc4,'exact':exact,'fx_1h':fx,'collector':'data_only_v1'}
 p=OUT/f"{w['id']}_101_300.json.gz"
 with gzip.open(p,'wt',encoding='utf-8') as f: json.dump(payload,f,separators=(',',':'))
 manifest.append({'window':w['id'],'mapped':len(mapped),'partial':len(partial),'signals':len(sig),'signal_symbols':syms,'bytes':p.stat().st_size})
 print('DONE',manifest[-1],flush=True)
pathlib.Path(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(manifest,indent=2))
