"""Coarse first-party PnL series: context only, no interpolated monthly returns."""
from pathlib import Path
import json,datetime,hashlib
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt,matplotlib.dates as mdates
R=Path(__file__).resolve().parent;start=1732665600000;end=1795737600000;meta=[];fig,axes=plt.subplots(2,1,figsize=(11,6),constrained_layout=True)
for ax,name in zip(axes,['bobby','wintermute']):
 p=R/f'raw/{name}_portfolio.json';d=dict(json.loads(p.read_text()))['allTime'];z=[x for x in d['pnlHistory'] if start<=x[0]<end];ts=pd.to_datetime([x[0] for x in z],unit='ms',utc=True);v=np.array([float(x[1]) for x in z]);ax.plot(ts,v/1e6,'o-',markersize=3,lw=1);ax.set_title(f'{name}: {len(z)} pontos reportados dentro da janela de dois anos',fontsize=11);ax.set_ylabel('PnL acumulado (US$ milhões)');ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%Y'));ax.grid(alpha=.2)
 meta.append(dict(wallet_label=name,first_date_utc=ts[0].isoformat(),last_date_utc=ts[-1].isoformat(),points_in_target=len(z),total_alltime_points=len(d['pnlHistory']),source='https://api.hyperliquid.xyz/info',request_type='portfolio',series='allTime.pnlHistory',sha256=hashlib.sha256(p.read_bytes()).hexdigest(),monthly_returns_computed=False,note='Sparse cumulative reported PnL, not reconstructed trades, not capital return, no interpolation at month ends.'))
fig.suptitle('Séries oficiais esparsas — 27/11/2024 a 26/11/2026\nLinhas ligam amostras; oscilações entre pontos não são observadas.',fontsize=12);fig.savefig(R/'HISTORICAL_PNL.png',dpi=150);plt.close(fig);(R/'PORTFOLIO_HISTORY.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta,indent=2))
