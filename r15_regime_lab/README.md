# R15 Market Structure / Regime Recognition Lab

Status: DATA AUDIT / REGIME RESEARCH. No trading changes are authorized in this branch yet.

## Objective
Learn causal, cross-asset market regimes from the 39-asset R14 universe before reconnecting entries:
RANGE_STABLE, RANGE_DERIORATING, BREAKOUT, TREND, EXHAUSTION, UNCERTAIN.

## Data policy
- Primary execution-market source: Binance spot OHLCV.
- Timeframes: 15m, 1h, 4h, 1d.
- Preserve raw exchange candles; derive higher timeframes causally when useful.
- CoinMarketCap/CoinGecko or other reputable aggregates are validation/enrichment sources, not silently mixed into exchange OHLCV.
- Normalize structural features by each asset's volatility/liquidity characteristics.
- Never use future candles in online features.
- Labels may use future candles only as training targets; features must stop at decision timestamp.
- Keep an untouched outer holdout.

## First audit
For every symbol/timeframe:
1. first/last timestamp, rows, missing intervals, duplicates;
2. OHLC consistency and zero/abnormal volume;
3. available years and listing-age bias;
4. cross-timeframe consistency;
5. regime coverage and transition counts;
6. concentration by symbol and calendar period.

## Candidate structural features
ATR and realized volatility; normalized range width; range slope; containment; center crossings;
edge touches/rejections; directional efficiency; ADX/DI; EMA slope/separation; RSI;
volume z-score and expansion; volatility compression/expansion; breakout distance;
multi-timeframe alignment; BTC-relative return/correlation; optional Hurst-like persistence measures.

## Validation
Walk-forward only. Purge/embargo around labels. Asset-level and time-level holdouts.
Report macro and per-symbol confusion/transition metrics. No profitability optimization until regime
recognition is demonstrably stable OOS.

R14.5.1 remains frozen as baseline.
