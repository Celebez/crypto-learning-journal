# Methodology

> How the system actually works — the data flow, the decision logic, and the calibration loop.

## The four scripts that matter

The full repo has 50+ Python files. Most of them are either variants, utilities, or one-off experiments. The actual production flow uses four scripts:

1. **`scripts/utils/fetch_market_data.py`** — pulls OHLCV from Bybit REST.
2. **`scripts/analysis/hermes_crypto_analysis.py`** — computes indicators and writes a structured market snapshot.
3. **`scripts/prediction/predict_cycle.py`** — reads the snapshot, applies the indicator-weight model, fires a prediction into `prediction_registry.json`.
4. **`scripts/utils/verify_and_learn.py`** — runs T+window after each prediction, checks the outcome, updates `learning_weights.json` and `scorecard.json`.

That's it. Everything else is plumbing, variants, or experiments.

## The data flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1: Fetch                                                      │
│  fetch_market_data.py                                               │
│  ─────────────────                                                  │
│  GET /v5/market/kline?category=linear&symbol=BTCUSDT&interval=60   │
│       &limit=300                                                    │
│                                                                     │
│  Output: pandas DataFrame indexed by timestamp                      │
│          columns: open, high, low, close, volume                    │
│                                                                     │
│  Cache: data/snapshots/latest_snapshot.json (last 24h of snapshots) │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 2: Analyze                                                    │
│  hermes_crypto_analysis.py                                          │
│  ────────────────────────                                           │
│  For each timeframe (15m, 1h, 4h, D):                               │
│    - compute RSI(14)                                                │
│    - compute MACD(12, 26, 9)                                        │
│    - compute Bollinger Bands(20, 2)                                 │
│    - compute EMA(9), EMA(21)                                        │
│    - compute volume profile (last 50 candles)                       │
│    - fetch open interest delta (5m, 15m, 1h)                        │
│                                                                     │
│  Output: structured JSON snapshot per symbol per timeframe           │
│          Written to data/snapshots/latest_snapshot.json             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3: Predict                                                    │
│  predict_cycle.py                                                   │
│  ────────────────                                                   │
│  Read data/snapshots/latest_snapshot.json                           │
│  Read data/learning/learning_weights.json                           │
│  Read data/learning/scorecard.json                                  │
│                                                                     │
│  For each symbol:                                                   │
│    1. Compute weighted signal across indicators:                    │
│         signal = Σ(indicator_signal_i × weight_i) / Σ(weight_i)    │
│    2. Compute raw confidence from indicator agreement:              │
│         raw_conf = (% of indicators agreeing on direction)          │
│    3. Apply calibration multiplier from scorecard:                  │
│         adjusted_conf = raw_conf × calibration_multiplier           │
│    4. Determine action:                                             │
│         adjusted_conf < 0.40 → NEUTRAL_hold                         │
│         signal > 0 + adj_conf ≥ 0.65 → BULLISH_buy                  │
│         signal < 0 + adj_conf ≥ 0.65 → BEARISH_sell                 │
│         otherwise → NEUTRAL_hold                                    │
│                                                                     │
│  Output: append to data/predictions/prediction_registry.json        │
│          { id, symbol, action, confidence, reason, timestamp }      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 4: Verify + Learn                                             │
│  verify_and_learn.py                                                │
│  ────────────────────                                               │
│  Run T+window after each prediction (window varies by timeframe):   │
│    15m prediction → check price 1h later                             │
│    1h prediction  → check price 4h later                             │
│    4h prediction  → check price 24h later                            │
│    D prediction   → check price 7d later                             │
│                                                                     │
│  "Correct" definition (conservative):                               │
│    BULLISH_buy:  price moved ≥ +1.0% AND stayed above entry         │
│    BEARISH_sell: price moved ≤ -1.0% AND stayed below entry         │
│    NEUTRAL_hold: price moved < ±1.0% in either direction            │
│                                                                     │
│  Then update:                                                       │
│    - prediction_registry.json: append outcome                       │
│    - learning_weights.json: adjust per-indicator weight              │
│         (Δweight_i = +α if indicator predicted correctly,           │
│                      -β if indicator predicted incorrectly)          │
│    - scorecard.json: recompute accuracy / PnL / calibration tier    │
└─────────────────────────────────────────────────────────────────────┘
```

## The indicator weight model

The heart of the system is `learning_engine.py`. It maintains a per-indicator weight that gets adjusted after each verified prediction.

```python
# Pseudo-code from learning_engine.py
def update_weights(registry, current_weights, alpha=0.05, beta=0.03):
    """Called after each verified prediction."""
    last_pred = registry[-1]
    indicator_signals = last_pred["indicator_signals"]  # {rsi: "buy", macd: "sell", ...}
    actual_outcome = last_pred["outcome"]               # "correct" or "wrong"

    new_weights = dict(current_weights)
    for indicator, signal in indicator_signals.items():
        if indicator_predicted_correctly(signal, last_pred):
            new_weights[indicator] += alpha
        else:
            new_weights[indicator] -= beta
        # Clamp to [1, 50] — never fully zero out an indicator
        new_weights[indicator] = max(1, min(50, new_weights[indicator]))
    return new_weights
```

The asymmetry (α=0.05, β=0.03) means the system is **slow to forget** an indicator that used to work, but **slow to trust** an indicator that recently worked. This is intentional: indicators have regime-specific accuracy, and you don't want to chase the most-recent-winner.

## The scorecard

`scorecard.json` is recomputed after each verified prediction. It contains:

```json
{
  "updated_at": "2026-06-20T14:49:36+00:00",
  "total_predictions": 176,
  "verified": 175,
  "correct": 72,
  "overall_accuracy": 0.2629,
  "total_pnl_pct": -36.531,
  "calibration_tier": "LOW",
  "calibration_multiplier": 0.7,
  "by_direction": {
    "BULLISH_buy":  {"verified": 43, "correct": 6, "accuracy": 0.1395},
    "BEARISH_sell": {"verified": 81, "correct": 22, "accuracy": 0.2716},
    "NEUTRAL_hold": {"verified": 27, "correct": 27, "accuracy": 1.0}
  },
  "by_confidence_tier": {
    "HIGH":   {"verified": 9, "correct": 0, "accuracy": 0.0},
    "MEDIUM": {"verified": 75, "correct": 16, "accuracy": 0.2133},
    "LOW":    {"verified": 58, "correct": 37, "accuracy": 0.6379}
  }
}
```

The calibration tier mapping:

```python
def calibration_tier(accuracy):
    if accuracy >= 0.65: return ("HIGH",   1.0)
    if accuracy >= 0.50: return ("MEDIUM", 0.85)
    return ("LOW", 0.7)
```

## The model-agnostic interface

`hermes_crypto_analysis.py` is the only script that *could* call an LLM. In practice it has two modes:

**Mode 1: No LLM (default).**
Pure technical analysis. The script computes indicators, looks for divergences, and outputs a structured JSON. No external calls.

**Mode 2: LLM-assisted.**
The structured JSON is passed to an LLM (configurable: any model with a `/chat/completions` endpoint), with a system prompt that asks the model to interpret the indicators and produce a final directional call. The LLM's output is then fed into the same `predict_cycle.py`.

The choice of LLM does not affect `prediction_registry.json` directly — the structured indicators are always preserved. The LLM is just one additional input.

This separation is what makes the system **model-agnostic**. The same data, the same scorecard, the same learning loop, regardless of which model (if any) is consulted.

## The file bridge

For automated trading, `scripts/bridges/hermes_bybit_bridge.py` is the only script that talks to Bybit. It exposes:

```python
get_balance()         → USDT wallet balance
get_positions()       → open positions
get_price(symbol)     → current mark price
place_order(...)      → market/limit order
close_position(...)   → close at market
```

Other scripts never call Bybit directly. They call the bridge. This is for safety and for testability: the bridge can be mocked in unit tests without touching the real exchange.

## What the system does NOT do

This is as important as what it does:

- **It does not manage risk.** There is no position sizing logic, no max-drawdown cutoff, no portfolio-level exposure limit. The system fires signals; the (human) trader decides position size.
- **It does not exit trades automatically.** Once a `BULLISH_buy` is placed, the system watches the outcome and reports it to the scorecard, but it does not issue a `close` order. Exit is manual.
- **It does not handle exchange errors robustly.** The bridge has minimal retry logic. Network blips will drop orders.
- **It does not backtest against itself.** This repo ships only the live signal generator + learning loop, not a backtest lab. (The original project also ran a parallel backtest lab for non-crypto assets; those scripts and CSVs are archived elsewhere, not here.)
- **It does not paper-trade by default.** The paper-trade mode (`paper_trade_30d.py`) is a separate script that wraps the prediction cycle and simulates fills. It is not on by default.

## A note on the data files

The data files in `data/` are real. They reflect what the system actually produced during the learning project. They are not synthetic, not curated, not post-hoc edited (except for the API key scrub documented in the README).

If you spot something in the data that contradicts the narrative in JOURNEY.md or METHODOLOGY.md, **trust the data**. The narrative was written after the fact; the data is the ground truth.

---

Next: [RESULTS.md](RESULTS.md) — live signal results, by-direction breakdown, and calibration tier analysis.
