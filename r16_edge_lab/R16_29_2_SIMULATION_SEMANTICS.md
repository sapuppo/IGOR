# R16.29.2 — scope and event semantics

This is an infrastructure rebuild, with one frozen alpha configuration and two
predeclared execution scenarios. No performance-based parameter selection is
permitted. R16.24.2 and R16.24.3 Spot-based returns are not valid USD-M evidence.

## Inputs and preservation

The original 152 gzip files must match the frozen manifest
`a50c67ce220cb55dfc4249c08fb484ad8a2f55fe6d4b19dab58423209bee4041`.
They are never replaced. Native USD-M CORE features replace the legacy Spot entry
timestamps. REV features use the same frozen thresholds, geometry and literal
16-bar REV15M horizon specified in the user directive, notwithstanding its H4 name.

Missing internal observations are recovered into a separately fingerprinted
supplement from official USD-M daily archives and their published checksums,
with official historical REST as an explicit fallback. Supplement rows may only
fill missing timestamps: overlapping/replacement rows fail validation. No
interpolation, synthesized prelisting data or alternative-venue prices are used.
The effective input fingerprint combines original and supplementary manifests.

Funding settlement prices come from the official `/fapi/v1/fundingRate` response.
Every supplied mark is matched to an original symbol, timestamp and rate. Empty
historical `markPrice` fields remain missing. The model uses the latest known
traded price for those events, counts them, and blocks historical funding
validation. Historical rates and timestamps remain unchanged. The fixed taker
fees are modeling assumptions, not historical account commissions.

The fixed 39-symbol research cohort has 38 eligible symbols. Eligibility begins
no earlier than first historical funding. This prevents prelisting fills but is
not a survivorship-free historical reconstruction of the entire exchange.

## Causal features and decisions

Features from a candle with opening timestamp t and duration d become available
at t+d-1 milliseconds. A signal/order cannot fill before the next available
15-minute opening observation. STRESS delays this by one further 15-minute
observation and increases fees and adverse slippage. Missing observations never
become synthetic fills. In a price gap the next actual observation may differ;
stress costs are compared against that scenario's execution reference.

CORE uses the original D55 cross, ADX30, EMA50/200, BTC strict and breadth55
rules. Reversal cluster selection is first-three in chronological order with
symbol tie breaks. Signals, orders, allocations, fills, funding and exits appear
separately in the ledger. Portfolio allocation priority is CORE, REV15M, REV1H.

The regime uses a separate shadow book of eligible strategy opportunities,
including opportunities rejected by portfolio allocation, to preserve the
frozen opportunity-based scoring policy. A shadow trade contributes only after
its actual close event. Portfolio and shadow books use the same deployed
stop/target/holding geometry and execution costs. Per-engine/per-symbol overlap
is decided by current occupied state, never a hindsight ranking of future
trades. Regime lookback is the frozen six-calendar-month rule.

## Global chronological clock

At a 15-minute opening observation:

1. Atomically mark existing positions to known opening prices.
2. Apply funding exactly at that timestamp to existing positions.
3. Execute existing gap exits.
4. Execute eligible pending orders in deterministic engine/symbol order.

Inside the bar, funding occurs at its historical millisecond timestamp and can
use an official settlement mark available at that instant. It cannot use that
bar's future high, low or close. New positions at an exact funding boundary pay
only when their fill precedes the timestamped funding event under this priority.

At the closed 15-minute observation, evaluate stop/target/time exits. A collision
is stop-first. A stop gap fills at the adverse opening reference; a target gap
does not get favorable gap improvement. Positions that exited within the OHLC
bar are marked at their exit reference rather than at the later close, avoiding
fictitious post-stop MTM drawdowns. Remaining positions are atomically marked to
the close, exits are booked, and only then are new signals/orders admitted.

OHLC does not prove the exact intrabar stop time relative to a funding event;
the modeled close timestamp is explicit. This is a limitation of the execution
resolution, not a claim of tick-accurate exchange replication. A truncated replay
does not force-close positions. A full run may close at the previously declared
research end, and that close is labeled `DECLARED_END`.

## Accounting and risk

Cash includes realized reference-price gross PnL, less separately booked
commissions and adverse slippage, plus funding. Unrealized PnL is reference-price
MTM. The resulting net equals execution-fill PnL less fees plus funding: slippage
is not deducted twice. The original nine-event ledger fixture still reconciles.

Isolated entry collateral remains reserved while a position is open; unrealized
profit cannot finance another position. Funding changes its isolated wallet.
Fees and entry slippage must fit in free cash in addition to reserved margin.
The portfolio cannot add exposure above 1x equity at entry, including entry
costs. All-event gross/equity is also reported; funding and fees can cause slight
post-entry drift even without a new leveraged entry. Nonpositive isolated equity
invalidates this simulation because no liquidation-tier model is implemented.

The 6% aggregate stop-risk limit is unchanged. Admission now reserves this budget
against equity after prospective stop losses and exit costs on all open positions.
This corrects the earlier admission check, which ignored the effect of open
losses on the denominator. All-event observed risk must also stay within 6% to
pass Gate 3. Gaps are not guaranteed to respect a stop-loss amount; any observed
invariant failure remains a failure, not a reason to relabel the gate.

## Validation and promotion

Gate 3 exercises the production engine: future-price/rate perturbation, truncated
raw-input replay, full-history deterministic replay, independent event-by-event
cash/MTM/cost/margin reconstruction, and fixtures with nonzero slippage and both
funding signs for long and short positions. Each of the five chronological
window boundaries gets a new feature computation and portfolio replay from
observations truncated at that boundary; every ledger event must match the
corresponding full-history prefix.

The 2021–June 2026 history was already available during alpha selection. These
windows are **chronological diagnostics, not untouched OOS**. No estimator is
fit in this rebuild, no configuration is selected from the window returns, and
state is carried chronologically across year boundaries. The prospective holdout
protocol remains unstarted until all technical requirements are satisfied.
Nothing here authorizes live trading or demonstrates 20% monthly profitability.

`BLOCKED` evidence means `TECHNICALLY_INVALID` for promotion. A successful CI job
only means that executable checks completed without an implementation failure;
it cannot change a blocked classification. Full economic tables remain diagnostic
until the source-evidence requirements are satisfied.
