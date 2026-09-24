# Strategy Reset — R15 -> R16 Edge First

## Executive decision

R15 is frozen as a diagnostic research line. Its predictive architecture must not be promoted to paper/live trading.

The reason is economic, not cosmetic:
- R15.7 Q1 calibration PF ~0.992 (already non-positive).
- R15.7 Q2 selected directional PF ~0.565, portfolio -12.93%.
- R15.8 economic trajectory heads were ~random (AUC ~0.50-0.52).
- R15.8 Q1 policy PF ~0.531 and Q2 portfolio -37.00%.
- More features and more complex labels did not create economic edge.

## What was wrong with R15

1. **Wrong order of operations**
   - We learned regimes/classes first and asked whether they were profitable later.
   - R16 proves economic edge first.

2. **Synthetic target mismatch**
   - RANGE/BREAKOUT/TREND/FOLLOWTHROUGH labels are descriptive.
   - Descriptive accuracy is not the same as net expected return.

3. **Excessive 15m churn**
   - Small statistical edges were overwhelmed by execution costs.
   - R16 starts on 4h (and selectively 1h), where gross move / fee ratio is healthier.

4. **Negative calibration was allowed to advance**
   - This is now prohibited.
   - If calibration expectancy <= 0 or PF <= 1 after base costs, the candidate stops.

5. **Confidence was not economic confidence**
   - R15 p_follow had ~zero relationship with net PnL.
   - Future ML scores must be trained against incremental economic value over a proven baseline.

6. **Too much complexity before baseline proof**
   - 318 features did not solve lack of edge.
   - R16 uses simple rules first; features/ML are meta-layers only.

7. **Q2 2026 is contaminated as a development set**
   - It has been inspected repeatedly.
   - It may be used for development diagnostics but not called virgin validation again.

## What remains valuable from R15

- R15.2 official Binance historical database.
- Causal timestamp alignment.
- Multi-timeframe feature engineering code.
- Leakage controls.
- Cost/slippage stress framework.
- 39-symbol coverage.
- July 2026 onward outer holdout remains sealed.
- BTC context features appear repeatedly important and may become a simple regime gate.

## First R16 discovery

R16.0 screened 8 simple predeclared strategies with no ML.

Best candidate: **TB4H55**
- 4h Donchian 55 breakout
- EMA50/EMA200 trend alignment
- ADX >= 25
- next-bar-open execution
- stop 2.5 ATR
- target 5 ATR
- max hold 30 x 4h bars

Development result through 2026-06-30:
- 1,760 trades
- gross average: +0.6977% / trade
- gross PF: 1.184
- net average at base cost: +0.3777% / trade
- net PF: 1.095
- net average at stress cost: +0.2777% / trade
- stress PF: 1.069
- 70% positive quarters
- median quarter average: +0.3254% / trade
- max positive-PnL symbol contribution: ~10.9%
- trade bootstrap probability of positive mean: 92.4% (below strict 95% gate)

Directional decomposition:
- LONG: 779 trades, +0.7631% avg net, PF 1.190
- SHORT: 981 trades, +0.0717% avg net, PF 1.018

Weak quarters:
- 2024Q2 slightly negative
- 2025Q1 strongly negative
- 2025Q2 ~flat/negative

This is **promising but not production-ready**.

## R16 research protocol

### R16.1 — Robustness / regime dependence
Test parameter neighborhood, not a single best point:
- Donchian 40 / 55 / 70
- ADX 20 / 25 / 30
- fixed stop/target/hold initially
- long-only decomposition
- BTC 4h trend gate
- market breadth gate
- weekly block bootstrap
- year and quarter consistency
- portfolio overlap / drawdown

### R16.2 — Economic geometry
Only if R16.1 confirms a plateau:
- test neighboring stop/target/hold values;
- look for broad stable plateaus, not best backtest point;
- volatility-risk sizing;
- exposure caps and correlated-position limits.

### R16.3 — ML as meta-filter
Only after R16.2:
- baseline trade signal remains deterministic;
- ML predicts incremental economic value / skip probability;
- compare baseline vs baseline+ML in walk-forward;
- ML must improve net expectancy and/or drawdown without destroying robustness.

### R16.4 — Final sealed holdout
Only one frozen architecture is allowed to open July 2026 onward.
No tuning after that result.

## Hard advancement gates

A candidate cannot advance if:
- calibration PF <= 1 after base costs;
- net expectancy <= 0;
- stress costs destroy all edge;
- result depends on one symbol or one quarter;
- block-bootstrap evidence is weak;
- parameter neighborhood has no plateau.

The objective is robust positive expectancy, not a guaranteed return. No model or strategy can guarantee consistent profit.
