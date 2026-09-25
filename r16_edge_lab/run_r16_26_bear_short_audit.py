#!/usr/bin/env python3
"""R16.26 Bear/Short audit. Diagnostic only: no parameter selection from 2022."""
from pathlib import Path
import json, pandas as pd, numpy as np
ROOT=Path("r16_edge_lab/r16_26_inputs"); OUT=Path("r16_edge_lab/r16_26_bear_short_audit"); OUT.mkdir(parents=True,exist_ok=True)
def ff(root,name):
    h=list(root.rglob(name))
    if not h: raise FileNotFoundError(f"{name} under {root}")
    return h[0]
S=pd.read_csv(ff(ROOT/"short","short_map.csv"))
B=json.loads(ff(ROOT/"baseline","summary.json").read_text())
# Existing short family is evaluated as evidence, never selected by 2022 hindsight.
stress22=pd.to_numeric(S["stress_year_2022"],errors="coerce")
base22=pd.to_numeric(S["base_year_2022"],errors="coerce")
diag={
 "variants":int(len(S)),
 "strict_pass_count":int(S["passes_gate"].astype(bool).sum()),
 "variants_positive_2022_base":int((base22>0).sum()),
 "variants_positive_2022_stress":int((stress22>0).sum()),
 "median_2022_base_trade_sum":float(base22.median()),
 "median_2022_stress_trade_sum":float(stress22.median()),
 "best_2022_stress_trade_sum_diagnostic_only":float(stress22.max()),
 "global_positive_stress_portfolio_variants":int((pd.to_numeric(S["stress_portfolio_return"],errors="coerce")>0).sum()),
 "global_positive_and_2022_positive_stress":int(((pd.to_numeric(S["stress_portfolio_return"],errors="coerce")>0)&(stress22>0)).sum()),
}
# quantify why the family was not integrated
reasons={
 "pf_below_1_10":int((pd.to_numeric(S["stress_pf"],errors="coerce")<1.10).sum()),
 "negative_avg_stress":int((pd.to_numeric(S["stress_avg"],errors="coerce")<=0).sum()),
 "weekly_prob_below_95pct_base":int((pd.to_numeric(S["base_weekly_prob_positive"],errors="coerce")<.95).sum()),
 "not_all_active_years_positive_base":int((~S["base_all_active_years_positive"].astype(bool)).sum()),
}
sel=B["selected"]; years=sel.get("stress_years",{})
summary={
 "version":"R16.26",
 "purpose":"bear-market/short-side audit without 2022 hindsight tuning",
 "baseline":"R16.24.2",
 "baseline_2022":years.get("2022"),
 "diagnostic":diag,
 "short_family_rejection_reasons":reasons,
 "finding":"The existing R16.11 short family did generate positive aggregate short opportunity in 2022 for many variants, but zero variants passed the global robustness gate; R16.24.2 therefore contains no dedicated short engine.",
 "methodology":["2022 is diagnostic evidence, not a parameter-selection target.","No 2022-best variant is promoted to production.","Any replacement short engine must be selected on pre-2022 or rolling prior data and validated out-of-sample across multiple bearish windows.","20% monthly remains an economic target, not a backtest acceptance override."],
 "next_stage":"R16.26B causal short redesign / walk-forward"
}
pd.DataFrame([diag|reasons]).to_csv(OUT/"audit_metrics.csv",index=False)
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,default=float))
print(json.dumps(summary,indent=2,default=float))
