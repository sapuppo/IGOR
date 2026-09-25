# R16 Backtest Integrity Contract

Status: mandatory before any strategy result can be promoted.

## 1. Causality
- Every feature carries a knowledge timestamp.
- A decision at t may read only observations fully closed/known at or before t.
- Orders generated from a completed candle fill no earlier than the next tradable observation.
- Portfolio/regime state uses only trades whose exit/fill event has already occurred.
- Ranking/selection is event-driven; a later candidate can never alter an earlier decision.
- No centered rolling windows, backward fill, future interpolation, or full-sample normalization.

## 2. Point-in-time universe
- A symbol becomes eligible only after its real listing/tradability timestamp.
- Delisted/failed symbols remain in historical universes.
- Today's Top-N membership must never be projected backward.
- Missing pre-listing history is missing, never synthesized.

## 3. Execution model
Primary research venue: Binance USD-M perpetual futures, isolated position accounting, target leverage 1x unless a test explicitly declares otherwise.
- Separate signal, order, fill, and exit timestamps.
- Market fills include fee + spread/slippage.
- Stop/target collision inside one OHLC bar resolves conservatively (stop first) unless lower-timeframe data proves order.
- Funding is charged/credited only at funding timestamps crossed by the open position; use historical rate when available.
- Stress scenario worsens fee/slippage/latency; it may not improve a fill.

## 4. Portfolio accounting
At every event:
  equity = cash + realized PnL + unrealized PnL - accrued costs
- Drawdown is computed from mark-to-market equity, not closed balance.
- Gross and net exposure are measured against current MTM equity.
- Margin/collateral is reserved while positions are open.
- Aggregate stop risk and per-symbol/per-engine risk are enforced.
- Correlated positions must be reported and eventually constrained.
- If 1x/no-leverage is declared, the engine must not open new exposure that requires > available collateral. Breaches are test failures, not metrics.

## 5. Costs
Report separately:
- commissions
- spread/slippage
- funding
- financing/borrow if applicable
- liquidation/forced-close effects if leverage is enabled
Gross PnL and every cost component must reconcile exactly to net PnL.

## 6. Validation
- Strategy parameters are frozen before each OOS window.
- Selection uses only prior data.
- Walk-forward OOS results are primary; full-history fit is diagnostic.
- Keep a final untouched holdout.
- Log number of variants/attempts tested.
- 2021-2026 and 2022-2026 are both reported; neither is silently excluded.
- 20% monthly is an economic target, never a reason to accept/reject statistical evidence.

## 7. Mandatory invariants / tests
A result is INVALID if any fails:
1. future-data perturbation test: changing data after decision t cannot change decisions <=t.
2. prefix replay: running data through t must exactly match the prefix of a full run.
3. next-observation execution test.
4. no pre-listing trades.
5. no impossible same-bar favorable fill.
6. closed-only realized state.
7. MTM equity reconciliation at every event.
8. cash/margin/collateral reconciliation.
9. exposure limit invariant.
10. aggregate stop-risk invariant.
11. fee/funding reconciliation.
12. deterministic replay with identical input/seed.
13. chronological walk-forward isolation.
14. trade ledger -> monthly/yearly report reconciliation.
15. baseline fingerprint: input artifacts/code/config hashes stored with result.

## Promotion states
- TECHNICALLY_INVALID: any invariant fails.
- TECHNICALLY_VALID: engine/invariants pass, regardless of profit.
- RESEARCH_CANDIDATE: technically valid + positive evidence under declared gate.
- OOS_VALIDATED: passes frozen walk-forward/holdout.
- PAPER_CANDIDATE: OOS validated and ready for prospective paper reconciliation.
No stage is allowed to skip directly to live capital.
