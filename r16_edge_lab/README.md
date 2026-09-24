# R16 — Edge First

R16 resets the research architecture after R15 failed to establish positive net expectancy.

## What R15 proved

- Regime / structure classification contained some statistical signal.
- That signal did not convert into profitable execution after costs.
- R15.7 CALIB was already ~flat/negative (PF ~0.992); Q2 TEST fell to PF ~0.565.
- R15.8 trajectory heads were ~random (AUC ~0.50–0.52) and worsened economics.
- Therefore ML is not allowed to create the primary trade signal in R16.

## R16 principle

**First prove a simple economic edge. Then use ML only as a meta-layer.**

R16.0 screens a small, predeclared library of interpretable strategy families on 1h and 4h data:

1. trend breakout
2. EMA trend continuation
3. volatility squeeze breakout
4. momentum pullback
5. range mean reversion

Each trade:
- is signaled only from completed candles;
- enters at the next candle open;
- uses ATR-normalized exits;
- includes conservative base and stress costs;
- is evaluated by calendar-quarter folds;
- is split long vs short and by symbol;
- reports gross edge separately from net edge.

No R16 strategy may advance merely because the full-period backtest is positive.

## Advancement gate

A candidate must show, at minimum:
- positive net expectancy after base costs;
- PF > 1 after base costs;
- non-negative result under stress costs;
- majority of quarter folds positive;
- no dependence on a single asset;
- enough trades to make the estimate meaningful.

These are screening gates, not guarantees.

## Data policy

- Source: official Binance Spot OHLCV collected by R15.2.
- R16.0 uses 1h / 4h only to reduce churn and fee drag.
- R15 outer holdout beginning 2026-07-01 remains untouched.
- Q2 2026 is no longer considered virgin because R15 already inspected it; in R16.0 it is only a development fold.

## ML policy

ML is forbidden as the primary signal until a simple strategy family demonstrates robust positive economic edge. Later ML may be used for:
- regime gating;
- trade rejection;
- risk sizing;
- cross-sectional ranking;
- execution timing.

