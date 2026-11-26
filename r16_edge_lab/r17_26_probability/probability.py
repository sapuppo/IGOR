"""Chronological calibration, causal Kalman smoothing, cost-aware capital rank."""
import numpy as np
from scipy.special import expit,logit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,log_loss

def kalman_probability(p,times,q=.01,r=.25):
 out=np.empty(len(p));state=0.;variance=1.;last=None
 for i,(value,t) in enumerate(zip(p,times)):
  z=float(logit(np.clip(value,1e-5,1-1e-5)))
  if last is None or t-last>5*60000:state=z;variance=1.
  else:
   variance+=q;gain=variance/(variance+r);state+=gain*(z-state);variance=(1-gain)*variance
  out[i]=expit(state);last=t
 return out

def expected_value(p,stop,mu_plus,mu_minus,tau_plus,tau_minus,cost,adverse_funding=0):
 gross=stop*(p*mu_plus+(1-p)*mu_minus)
 duration=np.maximum(1,p*tau_plus+(1-p)*tau_minus)
 net=gross-cost-adverse_funding
 return net,net/duration,duration

def train_model(X,y,Xcal,ycal,params):
 model=HistGradientBoostingClassifier(**params).fit(X,y)
 logits=logit(np.clip(model.predict_proba(Xcal)[:,1],1e-5,1-1e-5)).reshape(-1,1)
 if len(np.unique(ycal))!=2:raise ValueError('calibration needs two outcomes')
 calibration=LogisticRegression(C=1.,solver='lbfgs',random_state=26).fit(logits,ycal)
 return model,calibration

def predict(model,calibration,X):
 raw=model.predict_proba(X)[:,1]
 p=calibration.predict_proba(logit(np.clip(raw,1e-5,1-1e-5)).reshape(-1,1))[:,1]
 return raw,p

def calibration_metrics(y,p,prior):
 bins=np.minimum((p*10).astype(int),9);ece=0
 for b in range(10):
  mask=bins==b
  if mask.any():ece+=mask.mean()*abs(float(y[mask].mean()-p[mask].mean()))
 return dict(brier=float(brier_score_loss(y,p)),constant_prior_brier=float(brier_score_loss(y,np.full(len(y),prior))),log_loss=float(log_loss(y,np.clip(p,1e-7,1-1e-7),labels=[0,1])),ece10=float(ece),observations=len(y),mean_probability=float(p.mean()),observed_positive_gross=float(y.mean()))
