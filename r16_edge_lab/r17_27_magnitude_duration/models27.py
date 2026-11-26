"""Fit calibrated class + conditional magnitude + duration + mean return.

All probability/regression calibration uses only the month preceding testing.
"""
import json,pickle,hashlib,warnings
import numpy as np,pandas as pd
from scipy.special import expit,logit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import mean_squared_error,mean_absolute_error,brier_score_loss
from lightgbm import LGBMClassifier,LGBMRegressor
from data27 import R,P,R26,STEP,HORIZONS,SYMS,FEATURES,BOOK_FEATURES,ms
warnings.filterwarnings('ignore',message='X does not have valid feature names')
PARAMS=P['model']['class_params']

def sample(frames,start,end,h,book=True,stride=15):
 rows=[];cols=FEATURES+(BOOK_FEATURES if book else [])
 for si,s in enumerate(SYMS):
  f=frames[s];sel=(f.index>=start)&(f.index<end-181*STEP)&((f.index//STEP)%stride==0)&f.book_valid
  clean=f.copy(deep=False);clean=clean.assign(stop_fraction=f['stop_'+str(h)])
  sel &= np.isfinite(clean[cols]).all(axis=1)
  z=clean.loc[sel];X=z[cols].to_numpy(dtype=np.float32)
  for side in [1,-1]:
   rr=z[f'r_{h}_{side}'].to_numpy();dd=z[f'd_{h}_{side}'].to_numpy(dtype=np.int64);t=z.index.to_numpy();valid=np.isfinite(rr)&(t+(1+dd)*STEP<end)
   xx=np.c_[X,np.full(len(z),si),np.full(len(z),side)].astype(np.float32);rows.append((xx[valid],rr[valid],dd[valid],t[valid]))
 X=np.concatenate([z[0] for z in rows]);r=np.concatenate([z[1] for z in rows]);d=np.concatenate([z[2] for z in rows]);t=np.concatenate([z[3] for z in rows]);idx=np.argsort(t,kind='stable')
 return X[idx],r[idx],d[idx],t[idx]

def fit_heads(X,r,d,Xc,rc,dc):
 positive=r>0;pc=rc>0
 classifier=LGBMClassifier(**PARAMS).fit(X,positive.astype(int));raw=classifier.predict_proba(Xc)[:,1];cal=LogisticRegression(C=1,solver='lbfgs',random_state=27).fit(logit(np.clip(raw,1e-5,1-1e-5)).reshape(-1,1),pc.astype(int))
 gain=LGBMRegressor(**PARAMS,objective='regression_l2').fit(X[positive],r[positive])
 loss=LGBMRegressor(**PARAMS,objective='regression_l2').fit(X[~positive],-r[~positive])
 duration=LGBMRegressor(**PARAMS,objective='regression_l2').fit(X,np.log1p(d))
 direct=LGBMRegressor(**PARAMS,objective='regression_l2').fit(X,r)
 rawdirect=direct.predict(Xc);resid=rc-rawdirect
 corrections=dict(gain_bias=float(np.mean(rc[pc]-gain.predict(Xc[pc]))),loss_bias=float(np.mean(-rc[~pc]-loss.predict(Xc[~pc]))),duration_bias=float(np.mean(dc-np.expm1(duration.predict(Xc)))),direct_bias=float(resid.mean()),residual_rms=float(np.sqrt(np.mean((resid-resid.mean())**2))))
 means=[float(rc[pc].mean()),float(-rc[~pc].mean()),float(dc.mean())]
 return dict(classifier=classifier,calibration=cal,gain=gain,loss=loss,duration=duration,direct=direct,corrections=corrections,means=means)

def predict_heads(bundle,X,h):
 raw=bundle['classifier'].predict_proba(X)[:,1];p=bundle['calibration'].predict_proba(logit(np.clip(raw,1e-5,1-1e-5)).reshape(-1,1))[:,1];c=bundle['corrections']
 return dict(p=p,gain=np.maximum(0,bundle['gain'].predict(X)+c['gain_bias']),loss=np.maximum(0,bundle['loss'].predict(X)+c['loss_bias']),duration=np.clip(np.expm1(bundle['duration'].predict(X))+c['duration_bias'],1,h),direct=bundle['direct'].predict(X)+c['direct_bias'])

def train_fold(month):
 period=pd.Period(month);a=ms(str(period.start_time.date()));b=min(ms(str((period+1).start_time.date())),ms(P['final_period'][1]));fitstart=ms(str((period-3).start_time.date()));calstart=ms(str((period-1).start_time.date()));N=(b-a)//STEP
 frames={s:pd.read_pickle(R/'prepared'/(s+'_features.pkl')) for s in SYMS};shape=(N,len(SYMS),len(HORIZONS),2)
 pred={k:np.full(shape,np.nan,dtype=np.float32) for k in ['p_price','gain_price','loss_price','duration_price','direct_price','p_book','gain_book','loss_book','duration_book','direct_book']}
 pred.update(stop=np.full((N,len(SYMS),len(HORIZONS)),np.nan,dtype=np.float32),book=np.zeros((N,len(SYMS)),dtype=bool),mean_price=np.zeros((len(HORIZONS),3)),rms_book=np.zeros(len(HORIZONS)),rule_side=np.zeros((N,len(SYMS)),np.int8))
 bundles={};audits=[];diagnostics={}
 for hi,h in enumerate(HORIZONS):
  for book in [False,True]:
   X,r,d,t=sample(frames,fitstart,calstart,h,book);Xc,rc,dc,tc=sample(frames,calstart,a,h,book)
   assert t.max()+181*STEP<tc.min() and tc.max()+181*STEP<a
   bundle=fit_heads(X,r,d,Xc,rc,dc);kind='book' if book else 'price';key=str(h)+'_'+kind;bundles[key]=bundle
   if not book:pred['mean_price'][hi]=bundle['means']
   else:pred['rms_book'][hi]=bundle['corrections']['residual_rms']
   audits.append(dict(key=key,fit_samples=len(r),calibration_samples=len(rc),fit_first=int(t.min()),fit_last=int(t.max()),calibration_first=int(tc.min()),calibration_last=int(tc.max()),evaluation_start=a,corrections=bundle['corrections'],means=bundle['means']))
   truths=[];forecast={k:[] for k in ['p','gain','loss','duration','direct']};true_d=[]
   cols=FEATURES+(BOOK_FEATURES if book else [])
   for si,s in enumerate(SYMS):
    f=frames[s].reindex(np.arange(a,b,STEP));f=f.assign(stop_fraction=f['stop_'+str(h)]);valid=np.isfinite(f[cols]).all(axis=1).to_numpy()&f.book_valid.to_numpy();base=f[cols].to_numpy(dtype=np.float32)
    pred['stop'][:,si,hi]=f.stop_fraction;pred['book'][:,si]=f.book_valid
    # A deterministic benchmark: ret20 and ret180 agree with EMA distance20
    # and distance60; only completed candle data, no learned threshold.
    side=np.where((f.ret20>0)&(f.ret180>0)&(f.distance20>0)&(f.distance60>0),1,np.where((f.ret20<0)&(f.ret180<0)&(f.distance20<0)&(f.distance60<0),-1,0));pred['rule_side'][:,si]=side
    for di,sd in enumerate([1,-1]):
     xx=np.c_[base,np.full(N,si),np.full(N,sd)].astype(np.float32);p=predict_heads(bundle,xx[valid],h)
     for k in p:pred[k+'_'+kind][valid,si,hi,di]=p[k]
     rr=f[f'r_{h}_{sd}'].to_numpy()[valid];dd=f[f'd_{h}_{sd}'].to_numpy()[valid];finite=np.isfinite(rr)
     truths.extend(rr[finite]);true_d.extend(dd[finite])
     for k in p:forecast[k].extend(p[k][finite])
   truth=np.asarray(truths);pp=np.asarray(forecast['p']);mu=np.asarray(forecast['direct']);tau=np.asarray(forecast['duration']);cond=pp*np.asarray(forecast['gain'])-(1-pp)*np.asarray(forecast['loss']);durationtrue=np.asarray(true_d)
   diagnostics[key]=dict(samples=len(truth),brier=float(brier_score_loss((truth>0).astype(int),pp)),prior_brier=float(brier_score_loss((truth>0).astype(int),np.full(len(truth),(rc>0).mean()))),direct_rmse=float(np.sqrt(mean_squared_error(truth,mu))),constant_mean_rmse=float(np.sqrt(mean_squared_error(truth,np.full(len(truth),rc.mean())))),conditional_rmse=float(np.sqrt(mean_squared_error(truth,cond))),duration_mae=float(mean_absolute_error(durationtrue,tau)),constant_duration_mae=float(mean_absolute_error(durationtrue,np.full(len(truth),dc.mean()))),mean_predicted_return_R=float(mu.mean()),mean_realized_return_R=float(truth.mean()))
   print('FIT',month,key,len(r),len(rc),'return_rmse',round(diagnostics[key]['direct_rmse'],4),flush=True)
 O=R/'models';O.mkdir(exist_ok=True);raw=pickle.dumps(bundles,protocol=5);(O/(month+'.pkl')).write_bytes(raw);np.savez_compressed(O/(month+'_predictions.npz'),**pred)
 meta=dict(version='R17.27',month=month,start=a,end=b,params=PARAMS,feature_columns=FEATURES+BOOK_FEATURES+['symbol','side'],audit=audits,diagnostics=diagnostics,model_sha256=hashlib.sha256(raw).hexdigest())
 (O/(month+'.json')).write_text(json.dumps(meta,indent=2,allow_nan=False)+'\n');return pred,meta

if __name__=='__main__':
 import sys
 train_fold(sys.argv[1])
