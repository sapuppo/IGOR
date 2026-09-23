#!/usr/bin/env python3
"""R15.5 - Hierarchical Regime Intelligence.

Hierarchy:
A) predictable vs uncertain
B) if predictable: range-hold vs expansion
C) if expansion: directional vs expansion-chop
D) if directional: up vs down
E) if directional: breakout vs trend
Parallel:
F) up-edge probability (>=1.5 ATR favorable, <=1.0 ATR adverse in 8h)
G) down-edge probability (mirror condition)

TRAIN: <2026-01-01 (sampled per symbol)
CALIB: 2026Q1, used for early stopping / threshold selection
TEST: 2026Q2, touched once for evaluation
OUTER_HOLDOUT >=2026-07-01 remains unopened.
"""
from __future__ import annotations
import json, gc
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, f1_score, log_loss,
    roc_auc_score, average_precision_score, confusion_matrix,
    classification_report
)

ROOT=Path("r15_regime_lab/processed/symbols")
OUT=Path("r15_regime_lab/model_r15_5")
OUT.mkdir(parents=True,exist_ok=True)
SEED=1505
MAX_TRAIN_PER_SYMBOL=45000
CLASSES=["BREAKOUT_DOWN","BREAKOUT_UP","EXPANSION_CHOP","RANGE_HOLD","TREND_DOWN","TREND_UP","UNCERTAIN"]
DIR_CLASSES={"BREAKOUT_DOWN","BREAKOUT_UP","TREND_DOWN","TREND_UP"}

def features():
    p=next(ROOT.glob("*.parquet"))
    cols=pd.read_parquet(p).columns
    return [c for c in cols if c.startswith(("15m_","1h_","4h_","1d_","btc_"))]

FEATS=features()
BASE_COLS=["symbol","ts","split","target_path_8h","y_mfe_8h_atr","y_mae_8h_atr"]+FEATS

def load(split,sampled=False):
    parts=[]
    for p in sorted(ROOT.glob("*.parquet")):
        d=pd.read_parquet(p,columns=BASE_COLS)
        d=d[(d["split"]==split)&d.target_path_8h.notna()]
        if sampled and len(d)>MAX_TRAIN_PER_SYMBOL:
            d=d.sample(MAX_TRAIN_PER_SYMBOL,random_state=SEED)
        if len(d): parts.append(d)
    if not parts: raise RuntimeError(split)
    d=pd.concat(parts,ignore_index=True)
    d[FEATS]=d[FEATS].astype("float32").replace([np.inf,-np.inf],np.nan)
    return d

train=load("TRAIN",True)
calib=load("CALIB",False)
test=load("TEST",False)

def labels(d):
    t=d.target_path_8h
    out={}
    out["predictable"]=(t!="UNCERTAIN").astype("int8")
    out["range_vs_expansion"]=(t!="RANGE_HOLD").astype("int8") # on predictable subset only
    out["directional_vs_chop"]=t.isin(DIR_CLASSES).astype("int8") # expansion only
    out["up_vs_down"]=t.isin({"BREAKOUT_UP","TREND_UP"}).astype("int8") # directional only
    out["breakout_vs_trend"]=t.isin({"BREAKOUT_DOWN","BREAKOUT_UP"}).astype("int8") # directional only
    mfe=d.y_mfe_8h_atr.astype(float); mae=d.y_mae_8h_atr.astype(float)
    out["up_edge"]=((mfe>=1.5)&(mae<=1.0)).astype("int8")
    out["down_edge"]=((mae>=1.5)&(mfe<=1.0)).astype("int8")
    return out

Ytr,Yca,Yte=labels(train),labels(calib),labels(test)

def mask_for(name,d):
    t=d.target_path_8h
    if name=="predictable": return np.ones(len(d),dtype=bool)
    if name=="range_vs_expansion": return (t!="UNCERTAIN").to_numpy()
    if name=="directional_vs_chop": return (~t.isin({"UNCERTAIN","RANGE_HOLD"})).to_numpy()
    if name in ("up_vs_down","breakout_vs_trend"): return t.isin(DIR_CLASSES).to_numpy()
    return np.ones(len(d),dtype=bool)

def best_threshold(y,p):
    rows=[]
    for th in np.arange(.20,.805,.01):
        pr=p>=th
        ba=balanced_accuracy_score(y,pr)
        f=f1_score(y,pr,zero_division=0)
        acc=accuracy_score(y,pr)
        # Favor balanced separation, then F1, without hidden test optimization.
        score=.70*ba+.30*f
        rows.append((score,ba,f,acc,th))
    rows.sort(reverse=True)
    return float(rows[0][-1]),rows

def metrics(y,p,th):
    pr=p>=th
    return {
      "n":int(len(y)),
      "positive_rate":float(np.mean(y)),
      "threshold":float(th),
      "accuracy":float(accuracy_score(y,pr)),
      "balanced_accuracy":float(balanced_accuracy_score(y,pr)),
      "f1":float(f1_score(y,pr,zero_division=0)),
      "roc_auc":float(roc_auc_score(y,p)) if len(np.unique(y))>1 else None,
      "pr_auc":float(average_precision_score(y,p)) if len(np.unique(y))>1 else None,
      "logloss":float(log_loss(y,np.c_[1-p,p],labels=[0,1]))
    }

heads=["predictable","range_vs_expansion","directional_vs_chop","up_vs_down","breakout_vs_trend","up_edge","down_edge"]
models={}; thresholds={}; results={}; test_probs={}; calib_probs={}; importance=[]

for j,name in enumerate(heads):
    mt=mask_for(name,train); mc=mask_for(name,calib); me=mask_for(name,test)
    yt=Ytr[name].to_numpy()[mt]; yc=Yca[name].to_numpy()[mc]; ye=Yte[name].to_numpy()[me]
    model=lgb.LGBMClassifier(
      objective="binary",n_estimators=550,learning_rate=.04,num_leaves=47,
      min_child_samples=140,subsample=.82,subsample_freq=1,colsample_bytree=.80,
      reg_alpha=.20,reg_lambda=1.35,max_bin=127,random_state=SEED+j,
      n_jobs=4,verbosity=-1
    )
    model.fit(train.loc[mt,FEATS],yt,eval_set=[(calib.loc[mc,FEATS],yc)],
              eval_metric="binary_logloss",
              callbacks=[lgb.early_stopping(45,verbose=False),lgb.log_evaluation(0)])
    pca=model.predict_proba(calib.loc[mc,FEATS])[:,1]
    th,_=best_threshold(yc,pca)
    pte_subset=model.predict_proba(test.loc[me,FEATS])[:,1]
    # For end-to-end inference get probability on every row.
    pte_all=model.predict_proba(test[FEATS])[:,1]
    pca_all=model.predict_proba(calib[FEATS])[:,1]
    thresholds[name]=th
    test_probs[name]=pte_all
    calib_probs[name]=pca_all
    results[name]={
      "best_iteration":int(model.best_iteration_),
      "calib":metrics(yc,pca,th),
      "test":metrics(ye,pte_subset,th)
    }
    gain=model.booster_.feature_importance(importance_type="gain")
    for f,g in zip(FEATS,gain): importance.append({"head":name,"feature":f,"gain":float(g)})
    model.booster_.save_model(str(OUT/f"{name}.txt"))
    models[name]=model
    print(name,json.dumps(results[name]["test"]),flush=True)

def hierarchy(probs,thresholds):
    n=len(next(iter(probs.values())))
    pred=np.full(n,"UNCERTAIN",object)
    predictable=probs["predictable"]>=thresholds["predictable"]
    expansion=probs["range_vs_expansion"]>=thresholds["range_vs_expansion"]
    directional=probs["directional_vs_chop"]>=thresholds["directional_vs_chop"]
    up=probs["up_vs_down"]>=thresholds["up_vs_down"]
    breakout=probs["breakout_vs_trend"]>=thresholds["breakout_vs_trend"]
    rng=predictable & ~expansion
    chop=predictable & expansion & ~directional
    direc=predictable & expansion & directional
    pred[rng]="RANGE_HOLD"; pred[chop]="EXPANSION_CHOP"
    pred[direc & up & breakout]="BREAKOUT_UP"
    pred[direc & ~up & breakout]="BREAKOUT_DOWN"
    pred[direc & up & ~breakout]="TREND_UP"
    pred[direc & ~up & ~breakout]="TREND_DOWN"
    return pred

pred_test=hierarchy(test_probs,thresholds)
truth=test.target_path_8h.to_numpy()
overall={
  "accuracy":float(accuracy_score(truth,pred_test)),
  "balanced_accuracy":float(balanced_accuracy_score(truth,pred_test)),
  "macro_f1":float(f1_score(truth,pred_test,average="macro",zero_division=0)),
  "weighted_f1":float(f1_score(truth,pred_test,average="weighted",zero_division=0)),
  "n":int(len(test))
}
pd.DataFrame(confusion_matrix(truth,pred_test,labels=CLASSES),index=CLASSES,columns=CLASSES).to_csv(OUT/"hierarchy_confusion_test.csv")
pd.DataFrame(classification_report(truth,pred_test,labels=CLASSES,output_dict=True,zero_division=0)).T.to_csv(OUT/"hierarchy_report_test.csv")

# Confidence routing: product of branch certainty along chosen path.
def route_confidence(probs,pred):
    n=len(pred); conf=np.zeros(n)
    for i,label in enumerate(pred):
        pp=probs["predictable"][i]
        if label=="UNCERTAIN": conf[i]=1-pp; continue
        vals=[pp]
        pe=probs["range_vs_expansion"][i]
        if label=="RANGE_HOLD": vals.append(1-pe)
        else:
            vals.append(pe); pd=probs["directional_vs_chop"][i]
            if label=="EXPANSION_CHOP": vals.append(1-pd)
            else:
                vals.append(pd)
                pu=probs["up_vs_down"][i]
                pb=probs["breakout_vs_trend"][i]
                vals.extend([pu if label.endswith("_UP") else 1-pu,
                             pb if label.startswith("BREAKOUT") else 1-pb])
        conf[i]=float(np.prod(vals)**(1/len(vals))) # geometric route confidence
    return conf

route_conf=route_confidence(test_probs,pred_test)
curve=[]
for th in np.arange(.40,.91,.025):
    m=route_conf>=th
    if m.any():
        curve.append({"threshold":float(th),"coverage":float(m.mean()),"accuracy":float((pred_test[m]==truth[m]).mean()),"n":int(m.sum())})
    else: curve.append({"threshold":float(th),"coverage":0.0,"accuracy":None,"n":0})
pd.DataFrame(curve).to_csv(OUT/"route_confidence_curve_test.csv",index=False)

# Edge heads: evaluate economically interpretable opportunity separation.
edge_rows=[]
for side in ["up","down"]:
    name=side+"_edge"; p=test_probs[name]; th=thresholds[name]; sel=p>=th
    mfe=test.y_mfe_8h_atr.to_numpy(float); mae=test.y_mae_8h_atr.to_numpy(float)
    signed_ret=test["15m_ret1"].to_numpy(float) # context only, not outcome
    edge_rows.append({
      "side":side,"selected":int(sel.sum()),"coverage":float(sel.mean()),
      "true_edge_rate_selected":float(Yte[name].to_numpy()[sel].mean()) if sel.any() else None,
      "true_edge_rate_all":float(Yte[name].mean()),
      "median_favorable_atr":float(np.nanmedian((mfe if side=="up" else mae)[sel])) if sel.any() else None,
      "median_adverse_atr":float(np.nanmedian((mae if side=="up" else mfe)[sel])) if sel.any() else None
    })
pd.DataFrame(edge_rows).to_csv(OUT/"edge_selection_test.csv",index=False)

imp=pd.DataFrame(importance)
imp["gain_share_within_head"]=imp.gain/imp.groupby("head").gain.transform("sum")
imp.sort_values(["head","gain"],ascending=[True,False]).to_csv(OUT/"feature_importance_by_head.csv",index=False)

# Per-symbol end-to-end
per=[]
for sym,g in test.groupby("symbol",sort=True):
    idx=g.index.to_numpy()
    yt=g.target_path_8h.to_numpy(); pr=pred_test[idx]
    per.append({"symbol":sym,"rows":len(g),"accuracy":float((yt==pr).mean()),
                "macro_f1":float(f1_score(yt,pr,average="macro",zero_division=0))})
pd.DataFrame(per).to_csv(OUT/"per_symbol_hierarchy_test.csv",index=False)

summary={
 "version":"R15.5",
 "architecture":"hierarchical binary regime intelligence + directional edge heads",
 "features":len(FEATS),
 "train_rows_sampled":int(len(train)),"calib_rows":int(len(calib)),"test_rows":int(len(test)),
 "thresholds":thresholds,
 "heads":results,
 "hierarchy_test":overall,
 "edge_test":edge_rows,
 "outer_holdout_opened":False,
 "outer_holdout_start":"2026-07-01T00:00:00Z",
 "comparison_flat_r15_4":{"accuracy":0.3037276034067189,"balanced_accuracy":0.2092232831255561,"macro_f1":0.16025691172594042},
 "notes":[
   "Thresholds chosen only on CALIB.",
   "TEST is chronological 2026Q2 and is not used to fit parameters.",
   "No symbol identity is used as an input feature.",
   "OUTER_HOLDOUT remains sealed."
 ]
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
print("\nSUMMARY\n"+json.dumps(summary,indent=2),flush=True)
