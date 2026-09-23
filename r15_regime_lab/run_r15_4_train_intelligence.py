#!/usr/bin/env python3
"""R15.4 - Regime Intelligence Model.

Trains only on TRAIN (<2026-01-01), uses CALIB (2026Q1) for early stopping and
confidence threshold selection, evaluates once on TEST (2026Q2). OUTER_HOLDOUT
(>=2026-07-01) is never loaded for labels/evaluation.

Outputs:
- 7-class 8h path classifier
- three 8h ATR-normalized regressors: return, MFE, MAE
- confidence/coverage curve and calibrated abstention threshold
- overall + per-class + per-symbol TEST metrics
- confusion matrix, feature importance, model files
"""
from __future__ import annotations
import json, math, gc
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, f1_score, log_loss,
    classification_report, confusion_matrix, mean_absolute_error,
    mean_squared_error
)

ROOT=Path("r15_regime_lab/processed/symbols")
OUT=Path("r15_regime_lab/model_r15_4")
OUT.mkdir(parents=True,exist_ok=True)
SEED=1504
CLASSES=["BREAKOUT_DOWN","BREAKOUT_UP","EXPANSION_CHOP","RANGE_HOLD","TREND_DOWN","TREND_UP","UNCERTAIN"]
LABEL2ID={x:i for i,x in enumerate(CLASSES)}
TARGET="target_path_8h"
REG_TARGETS=["y_ret_8h_atr","y_mfe_8h_atr","y_mae_8h_atr"]
MAX_TRAIN_PER_SYMBOL=45000

def discover_features():
    p=next(ROOT.glob("*.parquet"))
    cols=pd.read_parquet(p).columns.tolist()
    return [c for c in cols if c.startswith(("15m_","1h_","4h_","1d_","btc_"))]

def load_split(features, split, sampled=False):
    parts=[]
    meta=[]
    cols=["symbol","ts","split",TARGET]+REG_TARGETS+features
    for p in sorted(ROOT.glob("*.parquet")):
        d=pd.read_parquet(p,columns=cols)
        d=d[d["split"].eq(split)]
        d=d[d[TARGET].notna()]
        if sampled and len(d)>MAX_TRAIN_PER_SYMBOL:
            d=d.sample(MAX_TRAIN_PER_SYMBOL,random_state=SEED)
        if len(d):
            meta.append({"symbol":p.stem,"split":split,"rows":len(d)})
            parts.append(d)
    if not parts: raise RuntimeError(f"No rows for {split}")
    return pd.concat(parts,ignore_index=True),pd.DataFrame(meta)

def matrix(d,features):
    X=d[features].astype("float32").replace([np.inf,-np.inf],np.nan)
    # LightGBM handles NaNs natively.
    y=d[TARGET].map(LABEL2ID).astype("int8").to_numpy()
    return X,y

def selective_curve(y,p):
    conf=p.max(axis=1); pred=p.argmax(axis=1)
    rows=[]
    for t in np.arange(.25,.86,.025):
        m=conf>=t
        n=int(m.sum())
        if n==0:
            rows.append({"threshold":float(t),"coverage":0,"accuracy":None,"utility":0})
            continue
        acc=float((pred[m]==y[m]).mean())
        cov=float(m.mean())
        utility=float(((pred[m]==y[m]).sum()-(pred[m]!=y[m]).sum())/len(y))
        rows.append({"threshold":float(t),"coverage":cov,"accuracy":acc,"utility":utility})
    return pd.DataFrame(rows)

def regression_metrics(y,p):
    return {
      "mae":float(mean_absolute_error(y,p)),
      "rmse":float(mean_squared_error(y,p)**0.5),
      "corr":float(np.corrcoef(y,p)[0,1]) if len(y)>2 else None
    }

features=discover_features()
train,train_manifest=load_split(features,"TRAIN",sampled=True)
calib,calib_manifest=load_split(features,"CALIB")
test,test_manifest=load_split(features,"TEST")

Xtr,ytr=matrix(train,features)
Xca,yca=matrix(calib,features)
Xte,yte=matrix(test,features)

clf=lgb.LGBMClassifier(
    objective="multiclass",
    n_estimators=650,
    learning_rate=.045,
    num_leaves=63,
    max_depth=-1,
    min_child_samples=120,
    subsample=.82,
    subsample_freq=1,
    colsample_bytree=.82,
    reg_alpha=.15,
    reg_lambda=1.25,
    max_bin=127,
    random_state=SEED,
    n_jobs=4,
    verbosity=-1
)
clf.fit(
    Xtr,ytr,
    eval_set=[(Xca,yca)],
    eval_metric="multi_logloss",
    callbacks=[lgb.early_stopping(45,verbose=True),lgb.log_evaluation(50)]
)
pca=clf.predict_proba(Xca)
pte=clf.predict_proba(Xte)
pred=pte.argmax(axis=1)

curve=selective_curve(yca,pca)
# Objective: correct decisions +1, wrong -1, abstain 0; require >=20% coverage.
eligible=curve[curve.coverage>=.20]
best=eligible.sort_values(["utility","accuracy","coverage"],ascending=False).iloc[0]
threshold=float(best.threshold)
conf=pte.max(axis=1)
active=conf>=threshold

overall={
 "accuracy":float(accuracy_score(yte,pred)),
 "balanced_accuracy":float(balanced_accuracy_score(yte,pred)),
 "macro_f1":float(f1_score(yte,pred,average="macro")),
 "weighted_f1":float(f1_score(yte,pred,average="weighted")),
 "logloss":float(log_loss(yte,pte,labels=list(range(len(CLASSES))))),
 "confidence_threshold_from_calib":threshold,
 "selective_coverage":float(active.mean()),
 "selective_accuracy":float((pred[active]==yte[active]).mean()) if active.any() else None,
 "selective_macro_f1":float(f1_score(yte[active],pred[active],average="macro",zero_division=0)) if active.any() else None,
 "n_test":int(len(yte)),
 "n_selective":int(active.sum())
}
report=classification_report(yte,pred,target_names=CLASSES,output_dict=True,zero_division=0)
pd.DataFrame(report).T.to_csv(OUT/"classification_report_test.csv")
cm=confusion_matrix(yte,pred,labels=list(range(len(CLASSES))))
pd.DataFrame(cm,index=CLASSES,columns=CLASSES).to_csv(OUT/"confusion_matrix_test.csv")
curve.to_csv(OUT/"calibration_selective_curve.csv",index=False)

# Per-symbol generalization metrics on untouched TEST.
rows=[]
off=0
for sym,g in test.groupby("symbol",sort=True):
    idx=g.index.to_numpy()
    ys=np.array([LABEL2ID[x] for x in g[TARGET]])
    ps=pte[idx]
    pr=ps.argmax(axis=1); cf=ps.max(axis=1); ac=cf>=threshold
    rows.append({
      "symbol":sym,"rows":len(g),"accuracy":float((pr==ys).mean()),
      "macro_f1":float(f1_score(ys,pr,average="macro",zero_division=0)),
      "selective_coverage":float(ac.mean()),
      "selective_accuracy":float((pr[ac]==ys[ac]).mean()) if ac.any() else np.nan
    })
pd.DataFrame(rows).to_csv(OUT/"per_symbol_test.csv",index=False)

# Feature importance
imp=pd.DataFrame({"feature":features,
                  "gain":clf.booster_.feature_importance(importance_type="gain"),
                  "split":clf.booster_.feature_importance(importance_type="split")})
imp=imp.sort_values("gain",ascending=False)
imp.to_csv(OUT/"feature_importance.csv",index=False)
clf.booster_.save_model(str(OUT/"path_classifier.txt"))
(OUT/"labels.json").write_text(json.dumps({"classes":CLASSES,"label2id":LABEL2ID},indent=2))

# Regression heads. Keep same chronological partitions and feature matrix.
reg_results={}
for target in REG_TARGETS:
    yt=train[target].to_numpy(dtype="float32")
    yc=calib[target].to_numpy(dtype="float32")
    ye=test[target].to_numpy(dtype="float32")
    mtr=np.isfinite(yt); mca=np.isfinite(yc); mte=np.isfinite(ye)
    reg=lgb.LGBMRegressor(
      objective="huber" if target=="y_ret_8h_atr" else "regression_l1",
      n_estimators=500,learning_rate=.045,num_leaves=47,min_child_samples=140,
      subsample=.82,subsample_freq=1,colsample_bytree=.82,reg_alpha=.15,reg_lambda=1.25,
      max_bin=127,random_state=SEED+len(reg_results)+1,n_jobs=4,verbosity=-1)
    reg.fit(Xtr.loc[mtr],yt[mtr],eval_set=[(Xca.loc[mca],yc[mca])],
            callbacks=[lgb.early_stopping(40,verbose=False),lgb.log_evaluation(0)])
    pr=reg.predict(Xte.loc[mte])
    reg_results[target]={**regression_metrics(ye[mte],pr),"best_iteration":int(reg.best_iteration_)}
    reg.booster_.save_model(str(OUT/(target+".txt")))
    del reg,pr; gc.collect()

manifest=pd.concat([train_manifest,calib_manifest,test_manifest],ignore_index=True)
manifest.to_csv(OUT/"split_manifest.csv",index=False)
summary={
 "version":"R15.4",
 "model":"LightGBM multiclass + 3 ATR-normalized regression heads",
 "features":len(features),
 "classes":CLASSES,
 "train_rows_sampled":int(len(train)),
 "calib_rows":int(len(calib)),
 "test_rows":int(len(test)),
 "train_max_per_symbol":MAX_TRAIN_PER_SYMBOL,
 "best_iteration_classifier":int(clf.best_iteration_),
 "test":overall,
 "regression_test":reg_results,
 "outer_holdout_opened":False,
 "outer_holdout_start":"2026-07-01T00:00:00Z",
 "notes":[
   "No symbol identity is used as a feature.",
   "Higher-timeframe features were made available only after candle close in R15.3.",
   "Confidence threshold selected on CALIB only; TEST used once for evaluation.",
   "OUTER_HOLDOUT was not loaded for labels or metrics."
 ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print(json.dumps(summary,indent=2))
print("\nTOP FEATURES\n",imp.head(20).to_string(index=False))
