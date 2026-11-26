"""Offline inference contract for a later paper feed. Never sends an order."""
from pathlib import Path
import json,pickle
import numpy as np
from prepare import R,P,BASE_FEATURES,BOOK_FEATURES,SYMS,STEP
from probability import predict,expected_value

def infer(features,*,symbol,decision_ms,backend='lightgbm',month='2026-11'):
 if symbol not in SYMS:raise ValueError('symbol outside frozen universe')
 if int(features.get('available_at_ms',-1))!=decision_ms:raise ValueError('feature availability mismatch')
 cols=BASE_FEATURES+BOOK_FEATURES
 if not all(k in features and np.isfinite(features[k]) for k in cols):raise ValueError('missing/nonfinite causal features')
 if features['book_age']<=0 or features['book_age']>120:raise ValueError('future/stale book')
 folder='models_lightgbm' if backend=='lightgbm' else 'models';meta=json.loads((R/folder/(month+'.json')).read_text())
 import hashlib
 raw=(R/folder/(month+'.pkl')).read_bytes()
 if hashlib.sha256(raw).hexdigest()!=meta['model_sha256']:raise ValueError('model hash mismatch')
 if decision_ms<meta['start']:raise ValueError('model cannot predict before its training cutoff')
 models=pickle.loads(raw)  # Locally trained artifact only; never use an untrusted path.
 out=[];st=float(features['stop_fraction'])
 if not .002<=st<=.008:raise ValueError('stop fraction outside trained contract')
 for h in [8,20]:
  model,cal,mu=models[str(h)+'_book']
  for side in [1,-1]:
   X=np.array([[features[k] for k in cols]+[SYMS.index(symbol),side]],dtype=np.float32);_,p=predict(model,cal,X);prob=float(p[0]);ev,rank,tau=expected_value(prob,st,*mu,.0024)
   out.append(dict(symbol=symbol,side=side,horizon=h,probability=prob,expected_net=float(ev),score=float(rank),expected_minutes=float(tau),decision='PAPER_CANDIDATE' if ev>0 else 'SKIP_NEGATIVE_EXPECTATION'))
 return dict(mode='read_only_inference',orders_sent=0,kalman='not applied: caller must retain causal filter state',funding='caller must deduct known adverse settlement estimate before any paper entry',model=month,backend=backend,candidates=sorted(out,key=lambda x:-x['score']))
if __name__=='__main__':
 import sys
 item=json.loads(Path(sys.argv[1]).read_text());print(json.dumps(infer(item['features'],symbol=item['symbol'],decision_ms=item['decision_ms']),indent=2))
