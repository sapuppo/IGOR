from pathlib import Path
import pandas as pd,numpy as np,json,hashlib,collections,gzip,time
R=Path(__file__).resolve().parent;path=R/'raw/bobby_2026-10.csv.gz';counts=collections.Counter();directions=collections.Counter();bycoin={};n=0;fee_missing=0;pnl_missing=0;zeros=0;min_t=None;max_t=None;fees=collections.Counter();notional=collections.Counter();closedpnl=collections.Counter();fee_sign=collections.Counter();first=[]
for c in pd.read_csv(path,chunksize=150000,dtype=str,keep_default_na=False):
 n+=len(c);directions.update(c.dir);t=pd.to_datetime(c.time,utc=True);a=t.min().isoformat();b=t.max().isoformat();min_t=min(min_t,a) if min_t else a;max_t=max(max_t,b) if max_t else b
 fee=pd.to_numeric(c.fee,errors='coerce');pnl=pd.to_numeric(c.closedPnl,errors='coerce');ntl=pd.to_numeric(c.ntl,errors='coerce');fee_missing+=fee.isna().sum();pnl_missing+=pnl.isna().sum();fee_sign.update(np.where(fee.isna(),'missing',np.where(fee>0,'paid',np.where(fee<0,'rebate','zero'))))
 for coin,g in c.assign(fee_num=fee,pnl_num=pnl,ntl_num=ntl).groupby('coin'):
  counts[coin]+=len(g);fees[coin]+=g.fee_num.sum();closedpnl[coin]+=g.pnl_num.sum();notional[coin]+=g.ntl_num.sum()
 if not first:first=c.head(10).to_dict('records')
out=dict(rows=n,columns=list(c.columns),start=min_t,end=max_t,directions=dict(directions),missing_fee=int(fee_missing),missing_closedpnl=int(pnl_missing),fee_sign=dict(fee_sign),sum_fees=float(sum(fees.values())),sum_closedpnl=float(sum(closedpnl.values())),sum_notional=float(sum(notional.values())),by_coin={x:dict(fills=counts[x],fees=fees[x],closedpnl=closedpnl[x],notional=notional[x]) for x in counts},sample=first,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
(R/'RAW_PROFILE.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print(json.dumps({k:v for k,v in out.items() if k not in ['by_coin','sample']},indent=2));print('TOP',sorted(out['by_coin'].items(),key=lambda x:-x[1]['notional'])[:12])
