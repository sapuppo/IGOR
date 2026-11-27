"""Order-invariant daily executed flow, never called absolute inventory."""
from pathlib import Path
import json,hashlib
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt,matplotlib.dates as mdates
from inventory import DIRECTIONS
R=Path(__file__).resolve().parent;parts=[]
for c in pd.read_csv(R/'raw/bobby_2026-10.csv.gz',chunksize=150000,dtype=str,keep_default_na=False):
 z=c[c.coin.isin(['BTC','ETH','SOL'])].copy()
 if len(z):
  z['date']=pd.to_datetime(z.time,utc=True).dt.floor('D');z['size']=pd.to_numeric(z.sz);z['notional']=pd.to_numeric(z.ntl);z['sign']=z.dir.map(DIRECTIONS);assert z.sign.notna().all();z['signed_quantity']=z['size']*z.sign;z['signed_notional']=z.notional*z.sign;parts.append(z.groupby(['date','coin']).agg(executed_quantity_net=('signed_quantity','sum'),executed_notional_net=('signed_notional','sum'),gross_notional=('notional','sum'),fills=('sign','size')).reset_index())
d=pd.concat(parts).groupby(['date','coin'],as_index=False).sum();d.to_csv(R/'DAILY_MAJOR_FLOW.csv',index=False)
fig,axes=plt.subplots(3,2,figsize=(12,8),constrained_layout=True);hashes={}
for k,coin in enumerate(['BTC','ETH','SOL']):
 p=R.parent/'r17_26_probability/prepared'/(coin+'USDT_prices.npy');tp=p.with_name(coin+'USDT_times.npy');prices=np.load(p);times=np.load(tp);sel=(times>=1790812800000)&(times<1793491200000);t=pd.to_datetime(times[sel],unit='ms',utc=True);c=prices[sel,3];axes[k,0].plot(t,c/c[0]*100,color='#3776ab',lw=1);axes[k,0].set_title(coin+' — preço Binance (início=100)',fontsize=10)
 z=d[d.coin==coin].sort_values('date');axes[k,1].step(z.date+pd.Timedelta(days=1),z.executed_quantity_net.cumsum(),where='post',color='#bc5933');axes[k,1].axhline(0,color='#999',lw=.7);axes[k,1].set_title(coin+' — fluxo executado acumulado (unidades)',fontsize=10)
 for ax in axes[k]:ax.xaxis.set_major_locator(mdates.DayLocator(interval=7));ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'));ax.grid(alpha=.18)
 hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest();hashes[tp.name]=hashlib.sha256(tp.read_bytes()).hexdigest()
fig.suptitle('BobbyBigSize atribuída — outubro de 2026\nFluxo acumulado começa em zero; não é a posição absoluta nem uma estratégia inferida.',fontsize=12);fig.savefig(R/'FLOW_VS_PRICE.png',dpi=150);plt.close(fig);(R/'PRICE_INPUT_HASHES.json').write_text(json.dumps(hashes,indent=2)+'\n');print(d.groupby('coin')[['executed_quantity_net','gross_notional','fills']].sum().to_string())
