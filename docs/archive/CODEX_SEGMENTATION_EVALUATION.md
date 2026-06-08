# Trading System Segmentation Architecture Review

## Executive Verdict

Use a **hybrid architecture**: shared execution-grade kernels with independent Forex, XAU, and Crypto strategy packages. Do not duplicate the five existing modules into three forks. Parameters belong in typed segment profiles; feature construction, external data, stop policies, and portfolio exposure rules belong in segment-specific code.

The current repository is prototype-quality research code. It is suitable as a reference implementation, but not for paper execution until the shared risk and state-management foundations are rebuilt.

The proposed success criterion of `>50% accuracy` is insufficient. Optimize for **net expectancy after spread, slippage, fees, funding and financing**, with drawdown, turnover, tail loss, and calibration stability constraints.

## Current Code Review

| Module | Reuse | Required action |
|---|---:|---|
| [improved_confidence.py](/home/ubuntu/codex-trading/improved_confidence.py:109) | 40% | Retain directional projection and bounded scoring concept. Replace duplicated calibration logic, validate inputs, and make weights profile-driven. |
| [improved_macd.py](/home/ubuntu/codex-trading/improved_macd.py:160) | 60% | Retain crossover classification. Replace absolute thresholds with ATR- or volatility-normalized thresholds. Remove unreachable recovery states. |
| [improved_bb_squeeze.py](/home/ubuntu/codex-trading/improved_bb_squeeze.py:222) | 45% | Retain lifecycle concept. Fix release direction bug, stale-compression handling, percentile enforcement, and market-specific volume confirmation. |
| [improved_calibration.py](/home/ubuntu/codex-trading/improved_calibration.py:145) | 35% | Retain Bayesian concept. Rewrite prediction lifecycle around IDs, issue-time state, idempotent resolution, persistence, and bounded windows. |
| [improved_risk.py](/home/ubuntu/codex-trading/improved_risk.py:189) | 25% | Retain result dataclasses and high-level assessment flow. Rewrite around risk-at-stop, margin, leverage, currency exposure, symbol metadata, and marked-to-market equity. |

The repository does **not** contain Bybit or OANDA API adapters. Those integrations must be added.

## Remaining Shared Defects

1. [improved_risk.py](/home/ubuntu/codex-trading/improved_risk.py:297) conflates notional exposure with risk and margin. A read-only probe sized a BTC trade to `$30,633` notional on a `$10,000` account while the generic cap is 10%. Track risk-at-stop, gross notional, margin used, leverage, and liquidation buffer separately.
2. [improved_risk.py](/home/ubuntu/codex-trading/improved_risk.py:365) ignores proposed trade size and position direction during correlation checks. Forex additionally requires currency-level exposure buckets.
3. [improved_risk.py](/home/ubuntu/codex-trading/improved_risk.py:411) uses balance instead of marked-to-market equity and has no daily-loss control.
4. [improved_risk.py](/home/ubuntu/codex-trading/improved_risk.py:278) accepts negative ATR multipliers; [check_exposure_limits()](/home/ubuntu/codex-trading/improved_risk.py:297) accepts negative proposed sizes.
5. [improved_bb_squeeze.py](/home/ubuntu/codex-trading/improved_bb_squeeze.py:280) can classify a neutral release as bearish and validate it. The probe returned `Valid neutral squeeze release`.
6. [improved_macd.py](/home/ubuntu/codex-trading/improved_macd.py:107) uses absolute histogram thresholds that are not portable across EUR/USD, XAU/USD, and BTCUSDT.
7. [improved_confidence.py](/home/ubuntu/codex-trading/improved_confidence.py:160) treats every direction other than `"long"` as short and accepts out-of-range signals. It also duplicates calibration responsibilities.
8. [improved_calibration.py](/home/ubuntu/codex-trading/improved_calibration.py:169) records shadow status when outcomes resolve, not when predictions are issued. It has no prediction IDs, duplicate-resolution protection, or durable state.

## Recommended Structure

```text
trading/
  shared/
    models.py              # Candle, Feature, Signal, InstrumentSpec, OrderIntent, Position
    confidence.py          # Profile-driven scorer
    calibration.py         # Persistent prediction lifecycle and Bayesian calibration
    indicators/            # Normalized MACD, ATR, EMA, RSI, BB/KC primitives
    risk.py                # Invariant validation and portfolio risk aggregation
    execution.py           # Idempotent orders, reconciliation, stale-data checks
  forex/                   # Analyzer, feature pipeline, stop policy, exposure policy
  xau/                     # Analyzer, macro feature pipeline, stop policy
  crypto/                  # Analyzer, derivatives feature pipeline, stop policy
  adapters/oanda/          # Pricing, candles, instruments, account, orders
  adapters/bybit/          # REST/WebSocket market data, instruments, account, orders
  configs/                 # Versioned typed profiles per segment and symbol tier
  tests/                   # Shared contract tests plus independent segment suites
```

Run each segment as a separate process with separate calibration state and risk budgets. Add one independent portfolio-risk service as the final order gate.

## Shared Versus Market-Specific Functions

| Functionality | Shared kernel | Market-specific version |
|---|---|---|
| Confidence | Scoring, bounds, calibration adjustment | `build_forex_features()`, `build_xau_features()`, `build_crypto_features()` and segment weight profiles |
| MACD | `classify_macd()` after normalization | Parameters by timeframe and segment: EMA periods, ATR-normalized histogram floor, confirmation candles |
| BB squeeze | Compression/release state machine | Volume confirmation provider, compression window, release factor, timeframe alignment |
| Calibration | Prediction issue/resolve workflow | Separate calibration cohorts by segment, strategy, symbol tier, direction, and horizon |
| Stops | Validation and risk-at-stop math | `forex_stop_policy()`, `xau_stop_policy()`, `crypto_stop_policy()` |
| Position sizing | Account-risk budget and instrument rounding | Pip-value conversion, contract metadata, quote-currency conversion, margin and liquidation checks |
| Portfolio exposure | Common aggregation | FX currency buckets, XAU concentration, crypto beta and correlated-altcoin clusters |

## Segment Recommendations

| Segment | Required indicators | Initial confidence priors | Pilot risk defaults |
|---|---|---|---|
| Forex | Session classifier with DST-aware market calendar; spread filter; ATR and structure levels; currency-strength buckets; rolling pair correlations; rate differential; financing; point-in-time economic-calendar blackout | Support/resistance `1.3`, trend `1.1`, session `1.0`, rate differential `0.8`, normalized MACD `0.7`, BB release `0.5`, tick volume `0.3`. Calendar and spread are gates, not score bonuses. | Target risk `0.25%-0.50%`, hard cap `1%`; daily stop `2%`, hard cap `3%`; ATR plus structure stop with pair-specific pip floor; minimum net reward/risk `2.0`. |
| XAU | DXY or licensed USD basket; US real yields; inflation expectations; VIX; event blackout; ATR regime; structure levels; ETF flows and central-bank reserves as slow regime features | Real yield `1.3`, USD strength `1.2`, structure `1.1`, trend `0.9`, event regime `0.8`, VIX `0.6`, BB release `0.6`, ETF/reserve context `0.3`. | Target risk `0.25%-0.50%`, hard cap `1%`; daily stop `2%`, hard cap `3%`; ATR plus structure and event-gap buffer; minimum net reward/risk `2.5`. |
| Crypto | Funding rate and percentile; open-interest delta; turnover volume; taker imbalance from trades; mark/index premium; liquidation proxy; volatility regime; BTC beta; altcoin cluster exposure; optional sentiment and on-chain context | OI `1.2`, funding `1.1`, turnover volume `1.1`, taker imbalance `1.0`, trend `1.0`, normalized MACD `0.8`, BB release `0.8`, sentiment `0.4`, on-chain `0.3`. | Target risk `0.25%-0.50%`, hard cap `0.75%`; daily stop `2%-3%`, hard cap `4%`; ATR plus percentage floor and liquidation buffer; minimum net reward/risk `2.0`. |

The plan’s proposed `2%` Crypto trade risk and `6%` daily loss are too aggressive for the first deployment. Higher volatility is a reason to reduce risk, not increase it.

## Exact Changes By Existing Module

### `improved_confidence.py`
- Replace class-level `DEFAULT_INDICATOR_WEIGHTS` with injected, versioned segment profiles.
- Keep `calculate_confidence()`, but validate direction enum, finite values, signal range `[-1, 1]`, known regime, and data freshness.
- Remove `update_calibration()`, threshold mutation, and module-global calculator. Use one calibration service.
- Return score decomposition: raw features, weights, gates, calibration cohort, and profile version.

### `improved_macd.py`
- Add normalized histogram magnitude: histogram divided by ATR or rolling volatility.
- Make growth threshold, magnitude floor, confirmation count, and EMA periods profile parameters.
- Remove impossible branches created by independently supplied histogram states.
- Require candle timestamps, ordering checks, completed-candle status, and timeframe metadata.

### `improved_bb_squeeze.py`
- Reject `neutral` releases explicitly; phase must match an actual upper- or lower-band breakout.
- Enforce `COMPRESSION_PERCENTILE` and `MAX_COMPRESSION_CANDLES`, which are currently unused.
- Compare release volume with compression-period volume, not generic recent history.
- Inject confirmation providers: Forex/XAU should use tick activity and spread quality; Crypto should use turnover, trades, and optional OI expansion.

### `improved_calibration.py`
- Add `issue_prediction()` and idempotent `resolve_prediction(prediction_id, outcome)`.
- Persist issue-time segment, symbol, strategy, horizon, direction, confidence, shadow state, timestamps, and profile version.
- Use bounded rolling windows and separate recovery attempts.
- Remove `force_recovery_boost()` from automated paths and remove process-global state.

### `improved_risk.py`
- Replace generic `RiskManager` policy constants with injected `RiskProfile` and `InstrumentSpec`.
- Add daily realized-plus-unrealized PnL limits, equity drawdown, spread/slippage/fee buffers, financing/funding, pending orders, margin, and liquidation-distance checks.
- Add broker precision rounding, min/max quantity, minimum notional, tick size, pip location, quote conversion, and stale instrument-metadata rejection.
- Replace pair-only correlation checks with post-trade signed portfolio exposure.

## Integration Notes

For Crypto, use Bybit V5 REST/WebSocket adapters. Fetch instrument metadata dynamically because Bybit documents quantity limits that can change; ingest klines, mark/index data, funding, OI, trades, and account-ratio data. Reconcile orders after restarts because the real-time order endpoint has retention limitations.

For Forex and eligible XAU accounts, use OANDA V20 pricing streams, candle endpoints, account instruments, account NAV, and orders with price bounds. Confirm XAU/USD availability from the account instruments endpoint rather than assuming it is enabled.

## Testing Strategy

| Layer | Required tests |
|---|---|
| Shared | Property tests for unit consistency, invalid inputs, rounding, stop direction, duplicate outcomes, restart recovery, stale timestamps, partial fills, pending orders, and kill-switch hysteresis |
| Forex | DST session boundaries, pip-value conversion for JPY and non-USD crosses, quote conversion, calendar blackout windows, spreads, financing, and signed USD exposure |
| XAU | Real-yield and USD-feature lag tests, event gaps, stale macro data, missing slow-data behavior, spread spikes, and XAU contract specifications |
| Crypto | Funding interval alignment, OI gaps, WebSocket reconnects, mark-versus-last divergence, instrument metadata refresh, liquidation buffer, fees, funding payments, and 24/7 daily-boundary policy |
| Backtests | Point-in-time data, walk-forward validation, purged cross-validation, cost stress tests, latency simulation, regime slices, and Monte Carlo trade-order reshuffling |
| Rollout | Historical replay, paper execution, shadow live run, limited-capital canary, then gradual risk increase |

Treat ETF flows, central-bank activity, social sentiment, and on-chain metrics as optional regime features until they demonstrate incremental out-of-sample value. Slow or revised data must not drive intraday entries.

## Priority And Effort

| Priority | Deliverable | Effort |
|---:|---|---:|
| 0 | Shared models, persistent calibration lifecycle, rewritten risk kernel, instrument metadata, portfolio-risk gate | `10-15` engineer-days |
| 1 | Crypto segment and Bybit adapter, using funding/OI/trades before optional sentiment or on-chain data | `10-15` engineer-days |
| 2 | Forex segment and OANDA adapter, including sessions, calendar gates, pip conversion, and currency buckets | `12-18` engineer-days |
| 3 | XAU segment, reusing OANDA infrastructure plus macro ingestion and lag handling | `10-15` engineer-days |
| 4 | Replay harness, walk-forward reports, observability, reconciliation, and deployment hardening | `10-15` engineer-days |

Estimated implementation total: `52-78` engineer-days, excluding vendor onboarding and the live shadow-observation period. Crypto should be implemented first because the original system context is crypto and Bybit exposes the required derivatives data directly. Which segment has the highest edge cannot be determined from architecture; that requires cost-adjusted out-of-sample results.

## Data Sources

- Bybit official docs: [V5 API](https://bybit-exchange.github.io/docs/), [klines](https://bybit-exchange.github.io/docs/v5/market/kline), [open interest](https://bybit-exchange.github.io/docs/v5/market/open-interest), [instrument metadata](https://bybit-exchange.github.io/docs/v5/market/instrument), [orders](https://bybit-exchange.github.io/docs/v5/order/create-order)
- OANDA official docs: [pricing](https://developer.oanda.com/rest-live-v20/pricing-ep/), [account instruments and NAV](https://developer.oanda.com/rest-live-v20/account-ep/), [orders](https://developer.oanda.com/rest-live-v20/order-df/)
- XAU macro context: [FRED](https://fred.stlouisfed.org/), [World Gold Council ETF flows](https://www.gold.org/what-we-do/investing-gold/how-buy-gold/gold-backed-etfs-and-similar), [central-bank reserves](https://www.gold.org/goldhub/data/monthly-central-bank-statistics)

No code was changed. All five Python files passed read-only AST parsing; targeted read-only probes were used for the unresolved behavioral findings.
