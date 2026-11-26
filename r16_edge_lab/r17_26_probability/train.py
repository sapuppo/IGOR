"""Fixed chronological tree model; no tuning from evaluation labels."""
from pathlib import Path
import json,pickle,hashlib
import numpy as np,pandas as pd
from prepare import R,P,SYMS,STEP,BASE_FEATURES,BOOK_FEATURES,ms
from probability import train_model,predict,kalman_probability,calibration_metrics

MODEL_DIR='models'
PARAMS={k:v for k,v in P['model'].items() if k not in ['type','calibration']}

def sample(frames,start,end,horizon,book=True,stride=8):
 chunks=[]
 for si,s in enumerate(SYMS):
  f=frames[s];sel=(f.index>=start)&(f.index<end-21*STEP)&((f.index//STEP)%stride==0)
  cols=BASE_FEATURES+(BOOK_FEATURES if book else [])
  sel &= np.isfinite(f[cols]).all(axis=1)
  if book:sel &= f.book_valid
  sub=f.loc[sel];base=sub[cols].to_numpy(dtype=np.float32)
  for side in [1,-1]:
   rr=sub[f'r_{horizon}_{side}'].to_numpy();dd=sub[f'd_{horizon}_{side}'].to_numpy(dtype=np.int64);valid=np.isfinite(rr)&(sub.index.to_numpy()+(1+dd)*STEP<end)
   x=np.c_[base,np.full(len(base),si),np.full(len(base),side)].astype(np.float32)
   chunks.append((x[valid],rr[valid],dd[valid],sub.index.to_numpy()[valid]))
 X=np.concatenate([z[0] for z in chunks]);rr=np.concatenate([z[1] for z in chunks]);dd=np.concatenate([z[2] for z in chunks]);times=np.concatenate([z[3] for z in chunks]);sort=np.argsort(times,kind='stable')
 return X[sort],rr[sort],dd[sort],times[sort]

def train_fold(month):
 period=pd.Period(month,freq='M');start=ms(str(period.start_time.date()));end=min(ms(str((period+1).start_time.date())),ms(P['end_exclusive']));fitstart=ms(str((period-3).start_time.date()));calstart=ms(str((period-1).start_time.date()))
 frames={s:pd.read_pickle(R/'prepared'/(s+'_features.pkl')) for s in SYMS}
 N=(end-start)//STEP;pred=dict(p=np.full((N,3,2,2),np.nan,dtype=np.float32),k=np.full((N,3,2,2),np.nan,dtype=np.float32),price_p=np.full((N,3,2,2),np.nan,dtype=np.float32),price_k=np.full((N,3,2,2),np.nan,dtype=np.float32),stop=np.full((N,3),np.nan,dtype=np.float32),book=np.zeros((N,3),dtype=bool));payoffs=[];pricepayoffs=[];audit=[];diagnostics={};models={}
 for hi,h in enumerate([8,20]):
  for withbook in [True,False]:
   X,rr,dd,ts=sample(frames,fitstart,calstart,h,withbook);Xc,rc,dc,tc=sample(frames,calstart,start,h,withbook)
   y=(rr>0).astype(int);yc=(rc>0).astype(int);assert ts.max()<tc.min() and tc.max()+STEP<start
   model,cal=train_model(X,y,Xc,yc,PARAMS)
   positive=rc>0;mu=[float(rc[positive].mean()),float(rc[~positive].mean()),float(dc[positive].mean()),float(dc[~positive].mean())]
   (payoffs if withbook else pricepayoffs).append(mu)
   key=f'{h}_'+('book' if withbook else 'price');models[key]=(model,cal,mu);audit.append(dict(model=key,fit_samples=len(y),calibration_samples=len(yc),fit_first=int(ts.min()),fit_last=int(ts.max()),calibration_first=int(tc.min()),calibration_last=int(tc.max()),evaluation_start=start,fit_positive_rate=float(y.mean()),calibration_positive_rate=float(yc.mean()),payoff_duration=mu))
   metric_y=[];metric_p=[];metric_k=[];metric_raw=[]
   for si,s in enumerate(SYMS):
    f=frames[s].reindex(np.arange(start,end,STEP));cols=BASE_FEATURES+(BOOK_FEATURES if withbook else []);valid=np.isfinite(f[cols]).all(axis=1).to_numpy()
    if withbook:valid &= f.book_valid.to_numpy()
    pred['stop'][:,si]=f.stop_fraction;pred['book'][:,si]=f.book_valid
    for di,side in enumerate([1,-1]):
     xx=np.c_[f[cols].to_numpy(dtype=np.float32),np.full(len(f),si),np.full(len(f),side)].astype(np.float32)
     raw,prob=predict(model,cal,xx[valid]);smooth=kalman_probability(prob,f.index.to_numpy()[valid])
     target='p' if withbook else 'price_p';targetk='k' if withbook else 'price_k';pred[target][valid,si,hi,di]=prob;pred[targetk][valid,si,hi,di]=smooth
     # Diagnostic outcomes only, never fed back to model/calibration/ranking.
     r=f[f'r_{h}_{side}'].to_numpy()[valid];finite=np.isfinite(r)
     metric_y.extend((r[finite]>0).astype(int));metric_p.extend(prob[finite]);metric_k.extend(smooth[finite]);metric_raw.extend(raw[finite])
   yy=np.array(metric_y);diagnostics[key]=dict(raw=calibration_metrics(yy,np.array(metric_raw),float(yc.mean())),calibrated=calibration_metrics(yy,np.array(metric_p),float(yc.mean())),kalman=calibration_metrics(yy,np.array(metric_k),float(yc.mean())))
   print('FIT',month,key,'n',len(y),'cal',len(yc),'brier',diagnostics[key]['calibrated']['brier'],flush=True)
 pred['payoff']=np.array(payoffs);pred['price_payoff']=np.array(pricepayoffs)
 out=R/MODEL_DIR;out.mkdir(exist_ok=True);artifact=pickle.dumps(models,protocol=5);(out/(month+'.pkl')).write_bytes(artifact)
 np.savez_compressed(out/(month+'_predictions.npz'),**pred)
 metadata=dict(month=month,start=start,end=end,audit=audit,diagnostics=diagnostics,model_sha256=hashlib.sha256(artifact).hexdigest(),features=BASE_FEATURES+BOOK_FEATURES+['symbol_id','side'],params=PARAMS,warning='pickle created locally; never load untrusted pickle')
 (out/(month+'.json')).write_text(json.dumps(metadata,indent=2,allow_nan=False)+'\n')
 return pred,metadata

if __name__=='__main__':
 import sys
 train_fold(sys.argv[1])
