from pathlib import Path
import json, sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
CODE=HERE.parent/"r12_2_code"
sys.path.insert(0,str(CODE))
import run_ci
r=run_ci.r

records=[]
orig_choose=r.choose_margin

def summarize_rank(frame):
    z=frame[frame.rank_selected].copy()
    if z.empty:
        return {"n":0,"symbols":0,"avg":None,"precision":None,"pf":None,"max_share":None,
                "pred_abs_min":None,"pred_abs_max":None,"edge_min":None,"edge_max":None}
    x=z.stop_net_target
    pf=r._profit_factor(x)
    vc=z.symbol.value_counts()
    return {
        "n":int(len(z)),
        "symbols":int(z.symbol.nunique()),
        "avg":float(x.mean()),
        "precision":float((x>0).mean()),
        "pf":float(pf) if pf is not None and np.isfinite(pf) else (999.0 if pf is not None else None),
        "max_share":float(vc.iloc[0]/len(z)),
        "pred_abs_min":float(z.pred_abs_net.min()),
        "pred_abs_max":float(z.pred_abs_net.max()),
        "edge_min":float(z.calibrated_net_edge.min()),
        "edge_max":float(z.calibrated_net_edge.max()),
        "pred_abs_corr":float(z[["pred_abs_net","stop_net_target"]].corr().iloc[0,1]) if len(z)>2 else None
    }

def choose_diag(cal_scored,ver_scored,cfg):
    chosen,grid,decision=orig_choose(cal_scored,ver_scored,cfg)
    records.append({
        "calibration_rank_only":summarize_rank(cal_scored),
        "verification_rank_only":summarize_rank(ver_scored),
        "chosen_margin":chosen,
        "decision":decision,
    })
    return chosen,grid,decision

r.choose_margin=choose_diag
r.main()
# make_dual_oos is executed twice for reproducibility; keep the first deterministic pass.
half=len(records)//2 if len(records)%2==0 else len(records)
out=records[:half]
Path("r12_2_rankgate_diagnostic.json").write_text(json.dumps(out,indent=2,default=str))
print("===R12_2_RANK_DIAG===")
print(json.dumps(out,separators=(",",":"),default=str))
print("===END_R12_2_RANK_DIAG===")
