# R16.30 research preregistration — portfolio edge after execution costs

Status: PRE-RESULTS for the **single** hypothesis below. Research branch only; R16.24.2 stays the last validated baseline. No real trading authorization or claim of a 20% monthly edge.

## Pinned baseline and scope

- Comparator: R16.29.2 replay code `f8c2307533265653f1faf0832fda836b21641f85`; run `36282775646`, final BASE / STRESS artifact SHA-256 `6b9074669d441f0080ec51267d55d0cd69474b13896d3e2d9a0c1a3dc866a80a`.
- Frozen alpha fingerprint `cb1f770e39ee0e3814b0b37047abad71868c8b6ec517bb39cb7cfa47e91e3a5b`. Original USD-M manifest `a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041`; identical gap/funding evidence supplements. Initial equity 10,000 USDT, fixed 39-symbol research cohort, 38 eligible, 2021-01-01 through 2026-06-30.
- Code/config/fee assumptions and position controls unchanged: 1x maximum gross, 6% aggregate stop risk, same engine-specific risk, the same BASE/STRESS costs and 15-minute stress latency.
- Retrospective years 2021–2026 have already informed strategy selection. All tests here are **contaminated diagnostic comparisons**, not untouched out-of-sample results. Historical funding settlement marks remain incomplete, so Gate 3 stays `TECHNICALLY_INVALID` even if this candidate improves results.

## Hypothesis H1, declared before its replay

Filter out REV15M signals immediately after frozen signal generation and run the unchanged causal portfolio replay with CORE + REV1H. This is a **new candidate portfolio**, not a repair of the baseline. Reasons drawn from already inspected data: REV15M lost 3,373 USDT in STRESS despite 1,496 USDT net in BASE, with median holding time near 2 hours and material transaction costs. That prior inspection contaminates any historical benefit from excluding it.

Run both scenarios end-to-end with shared cash, allocation scores, shadow state, funding, exits, and MTM recomputed. Do not subtract REV15M trade PnL from the old ledger as a substitute. Generate signals once; record signal counts, output ledger hashes, realized PnL, compounded monthly return, worst month, MTM maximum drawdown, cost attribution, usage, and the causal replay diagnostics. Independently reproduce the original BASE/STRESS ledger hashes in the same research environment first.

Predeclared comparison: report H1 relative to R16.29.2 for each scenario, including adverse changes. A research candidate of interest requires STRESS net PnL and maximum drawdown both strictly better than its baseline, without violating 1x or 6% risk; this is **not** a promotion criterion. Any future alpha/fee/size/short variant must be logged as a distinct attempt before replay. There is no alteration to the 20% goal to make a backtest pass.

## Required economic proof later

Before a claim of a durable 20% monthly return, resolve funding mark evidence and historical execution assumptions, remove universe-selection bias, predeclare capital/drawdown limits, and evaluate a **future untouched** holdout of 180 calendar days and at least 100 closed trades with no retuning. Twenty percent monthly compound corresponds to 791.61% annual; historical diagnostics cannot establish that future rate or guarantee it.
