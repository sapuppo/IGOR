from pathlib import Path
import json
import numpy as np,pandas as pd
from prepare import R,P,SYMS,ms
from execution import get_data,forecast_table
rows=[]
for backend in ['','_lightgbm']:
 for month in P['walk_forward_months']+['2026-11']:
  raw=np.load(R/('models'+backend)/(month+'_predictions.npz'));pred={k:raw[k] for k in raw.files};start=month+'-01';end=min((pd.Period(month)+1).start_time,pd.Timestamp(P['end_exclusive'])).strftime('%Y-%m-%d');ds=get_data(start,end)
  for mode in P['variants']:
   prob,ev,score,order=forecast_table(ds,pred,mode,1);finite=np.isfinite(score);ep=ev[np.isfinite(ev)]
   rows.append(dict(backend='lightgbm' if backend else 'hist_gradient_boosting',month=month,variant=mode,eligible_forecasts=int(finite.sum()),positive_cost_adjusted_forecasts=int((ep>0).sum()),max_forecast_net=float(ep.max()) if len(ep) else None,net_percentiles=list(np.percentile(ep,[1,50,99])) if len(ep) else None,mean_probability=float(np.nanmean(prob)),max_probability=float(np.nanmax(prob))))
(R/'FORECAST_DIAGNOSTICS.json').write_text(json.dumps(rows,indent=2)+'\n');print('DIAGNOSTICS',len(rows))
