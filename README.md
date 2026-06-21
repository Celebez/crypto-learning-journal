# crypto-learning-journal

> A 3-month journey into crypto signal generation, captured as a public, self-contained learning artifact. Use it as a **tutorial**, a **code reference**, or a **cautionary tale**.

![Status](https://img.shields.io/badge/status-archived-lightgrey) ![Visibility](https://img.shields.io/badge/visibility-public-blue) ![Tutorial](https://img.shields.io/badge/type-tutorial-orange) ![Crypto](https://img.shields.io/badge/domain-crypto-yellow) ![Self--Learning](https://img.shields.io/badge/focus-self--learning-green) ![License](https://img.shields.io/badge/license-MIT-green)

![Demo](assets/demo.gif)

## 🎓 What is this?

This is a **3-month learning journal** about building (and stress-testing) a crypto signal generator. It contains:

- **63 files** of working code (analysis, prediction, backtest, calibration)
- **176 verified predictions** with outcomes
- **6 backtest iterations** (v6 → v11) with raw CSV output
- **A self-calibrating weight engine** that adjusts per-indicator trust
- **The honest numbers** (26% live accuracy, -36% PnL — not cherry-picked)
- **A demo GIF** that runs anywhere without API keys

It's intended as a **tutorial for developers** who want to learn about:
- Technical indicator pipelines (RSI, MACD, BB, EMA, volume, OI)
- Self-calibrating prediction systems
- The gap between backtest performance and live performance
- Why "NEUTRAL_hold" can be your most profitable signal

---

## 🚀 Quick start (5 minutes)

Want to **see the system run** without setting up any exchange? Try the demo:

```bash
git clone https://github.com/Celebez/crypto-learning-journal.git
cd crypto-learning-journal
bash assets/demo.sh
```

You'll see the repo structure, current scorecard, and indicator weights printed to your terminal. No API keys needed — the demo uses bash function overrides that print realistic output.

## 🛠️ Real install (15 minutes)

If you want to actually run the analysis pipeline against Bybit's testnet:

### Prerequisites

| Tool | Min version | Install (Ubuntu/Debian) |
|---|---|---|
| Python | 3.10+ | `sudo apt install python3 python3-pip python3-venv` |
| git | any recent | `sudo apt install git` |
| Bybit testnet account | — | https://testnet.bybit.com |

### Steps

```bash
# 1. Clone
git clone https://github.com/Celebez/crypto-learning-journal.git
cd crypto-learning-journal

# 2. Create venv
python3 -m venv .venv
source .venv/bin/activate

# 3. Install deps
pip install pybit pandas numpy

# 4. Get Bybit testnet API keys from https://testnet.bybit.com
export BYBIT_API_KEY='your_testnet_key_here'
export BYBIT_API_SECRET='your_testnet_secret_here'

# 5. Run analysis (DEMO mode by default)
python3 scripts/analysis/hermes_crypto_analysis.py
```

You should see structured JSON output with market snapshots for BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, HYPEUSDT across 15m, 1h, 4h, and daily timeframes.

---

## 📚 Tutorial: How to read this codebase as a learning resource

This repo is organized so you can read it in any order. Here's a suggested path for someone who wants to **build intuition about crypto signal generation**.

### Step 1: Start with the data, not the code

Before reading any script, open **`data/learning/scorecard.json`**. It contains the entire project's scorecard in 30 lines of JSON:

```json
{
  "total_predictions": 176,
  "verified": 175,
  "correct": 72,
  "overall_accuracy": 0.2629,
  "total_pnl_pct": -36.531,
  "calibration_tier": "LOW",
  "by_direction": {
    "BULLISH_buy":    {"verified": 43, "correct":  6, "accuracy": 0.1395},
    "BEARISH_sell":   {"verified": 81, "correct": 22, "accuracy": 0.2716},
    "NEUTRAL_hold":   {"verified": 27, "correct": 27, "accuracy": 1.0}
  }
}
```

**Lesson 1:** Read the by-direction breakdown. Notice that "do nothing" (`NEUTRAL_hold`) is 100% accurate (27/27) while "buy bullish" (`BULLISH_buy`) is only 14% accurate. This is the most important finding in the entire project.

**Lesson 2:** The "calibration_tier" is `LOW`. The system correctly distrusts itself. If you build a signal generator and its calibration tier is `HIGH`, be suspicious.

### Step 2: Read the indicator weight evolution

Open **`data/learning/learning_weights.json`**. This is the adaptive weight vector that the system uses to combine indicators:

```json
{
  "indicator_weights": {
    "rsi":      {"weight": 30, "accuracy": 0.9075, "total_signals": 45170},
    "macd":     {"weight": 10, "accuracy": 0.4155, "total_signals": 45174},
    "bb":       {"weight": 10, "accuracy": 0.2968, "total_signals": 45174},
    "ema_9_21": {"weight":  5, "accuracy": 0.2810, "total_signals": 45167},
    "volume":   {"weight": 10, "accuracy": 0.68},
    "oi":       {"weight": 10, "accuracy": 0.65}
  }
}
```

**Lesson 3:** RSI is weighted 30 (vs 5–10 for others) because it has 90% standalone accuracy. **But** the system's *combined* accuracy is 26%, not 90%. Combining indicators introduces interaction overfitting that ruins the individual signal accuracies.

### Step 3: Trace the prediction flow

Read these scripts in order:

1. **`scripts/utils/fetch_market_data.py`** (110 lines) — pulls OHLCV from Bybit REST. Notice how it imports `session` from `hermes_bybit_bridge` rather than calling Bybit directly — the file-bridge pattern is for safety and testability.

2. **`scripts/analysis/hermes_crypto_analysis.py`** (649 lines) — the multi-timeframe analysis pipeline. Look for:
   - The `CONFIG` dict at the top (line 32) — all the symbols and timeframes
   - The `get_klines` function (line 54) — fetches and parses OHLCV
   - The indicator computation section (~line 100+) — RSI, MACD, BB, EMA

3. **`scripts/prediction/predict_cycle.py`** (the "fire a signal" step) — read this file to understand:
   - How the weighted-indicator sum is computed
   - How the calibration multiplier from `scorecard.json` is applied
   - How the prediction is appended to `prediction_registry.json`

4. **`scripts/utils/verify_and_learn.py`** — the verification loop. After a prediction's outcome window passes, this script:
   - Checks the actual price movement
   - Updates `learning_weights.json` (per-indicator weights)
   - Recomputes `scorecard.json` (overall accuracy)

### Step 4: Trace the calibration engine

The **`data/learning/learning_engine.py`** file (~430 lines) is the heart of the adaptive system. Key function:

```python
def update_weights(registry, current_weights, alpha=0.05, beta=0.03):
    """Called after each verified prediction."""
    last_pred = registry[-1]
    new_weights = dict(current_weights)
    for indicator, signal in last_pred["indicator_signals"].items():
        if indicator_predicted_correctly(signal, last_pred):
            new_weights[indicator] += alpha    # trust grows slowly
        else:
            new_weights[indicator] -= beta     # trust decays slowly
        new_weights[indicator] = max(1, min(50, new_weights[indicator]))
    return new_weights
```

**Lesson 4:** Notice `alpha=0.05, beta=0.03` — the system is **asymmetric**. It takes 5 successful predictions to add 0.25 of trust, but only 3 failed predictions to remove 0.09. This is intentional: indicators have regime-specific accuracy, and you don't want to chase the most-recent-winner.

### Step 5: Modify and experiment

Once you've read the above, try modifying the system:

**Experiment A: Change the calibration multiplier**

Edit `data/learning/scorecard.json` and change `calibration_multiplier` from `0.7` to `1.0`. Then run `python3 scripts/utils/verify_and_learn.py --dry-run`. Notice how the predicted signals change — the system becomes more confident.

**Experiment B: Add your own indicator**

Edit `scripts/analysis/hermes_crypto_analysis.py` and add a new indicator (e.g., ATR, Ichimoku, VWAP). Then add it to the `indicator_weights` dict in `data/learning/learning_weights.json` with weight `5`. Run a verification cycle and watch the weight adapt.

**Experiment C: Reverse the policy**

The data says "low-confidence is high-accuracy." Modify `scripts/prediction/predict_cycle.py` to **only fire trades when confidence < 0.65** (the inverse of the current logic). Compare the resulting `scorecard.json` to the baseline.

---

## 🗂️ Repo walkthrough

```
crypto-learning-journal/
├── README.md                         # this file — tutorial entry point
├── CHANGELOG.md                      # version history
├── LICENSE                           # MIT
│
├── data/                             # all raw artifacts, frozen as-is
│   ├── predictions/                  #   every signal the system ever fired
│   ├── learning/                     #   what the system learned from mistakes
│   └── snapshots/                    #   portfolio snapshots over time
│
├── scripts/                          # the actual code, organized by role
│   ├── analysis/                     #   market analysis & signal generation
│   ├── bridges/                      #   exchange connectivity (Bybit)
│   ├── prediction/                   #   prediction-cycle scripts
│   └── utils/                        #   supporting utilities
│
├── docs/                             # narrative documentation
│   ├── JOURNEY.md                    #   3-month retrospective, day-by-day
│   ├── METHODOLOGY.md                #   how the system actually works
│   ├── RESULTS.md                    #   live signal results, deep analysis
│   ├── PITFALLS.md                   #   failure modes documented
│   └── archive/                      #   historical analysis briefs
│
└── assets/
    ├── demo.gif                      #   10-second terminal demo
    └── demo.sh                       #   source script for regenerating demo
```

| If you want to... | Look at... |
|---|---|
| Understand the data | `data/learning/scorecard.json` |
| See the indicator weights | `data/learning/learning_weights.json` |
| Read a prediction entry | `data/predictions/prediction_registry.json` |
| Trace market data fetch | `scripts/utils/fetch_market_data.py` |
| Trace signal generation | `scripts/analysis/hermes_crypto_analysis.py` |
| Trace prediction fire | `scripts/prediction/predict_cycle.py` |
| Trace outcome verification | `scripts/utils/verify_and_learn.py` |
| Modify the calibration loop | `data/learning/learning_engine.py` |
| Learn from mistakes | `docs/PITFALLS.md` |
| Read the full story | `docs/JOURNEY.md` |

---

## 🤔 FAQ

**Q: Does this system actually make money?**

No. The live signal generator has 26% accuracy and -36% PnL. The backtest ensemble has 64% win-rate but doesn't reflect live behavior. The system's most useful output is the `NEUTRAL_hold` signal (100% accuracy on 27 trades) — i.e., the system is best at detecting dead zones, not at generating entries.

**Q: Is this investment advice?**

No. This is a learning artifact. The data is honest about its own limitations; you should be too.

**Q: Can I use this code for my own trading?**

Yes, MIT licensed. But please read `docs/PITFALLS.md` first — most of the failure modes are subtle and will burn you if you don't understand them.

**Q: Why is the backtest so much better than the live results?**

Because the backtest entry logic and the live entry logic are different. The backtest evolved into a careful multi-filter strategy; the live signal generator stayed at the Phase 1 indicator-buffet architecture. See `docs/RESULTS.md` for the full gap analysis.

**Q: What's a calibration tier?**

It's the system's self-assessed reliability:
- `HIGH` (accuracy ≥ 65%): trust the system
- `MEDIUM` (50–65%): some trust, but be cautious
- `LOW` (<50%): system correctly distrusts itself, multiplier = 0.7

This project's calibration tier has been `LOW` since week 3. That's a feature, not a bug.

**Q: Can I run a backtest against historical crypto data?**

This repo doesn't ship a backtest lab — only the live signal generator + learning loop. The original backtest lab was on forex/XAU data (kept separate, not in this repo). To backtest crypto strategies, you'd need to:
1. Fetch historical OHLCV from Bybit or another exchange
2. Build a `Candle` list matching `data/learning/learning_engine.py` interface
3. Run each prediction through the engine's calibration logic
4. Compare predicted direction vs actual outcome

This is left as an exercise for the reader.

**Q: What's `NEUTRAL_hold` and why is it 100% accurate?**

`NEUTRAL_hold` is the system's "sit out" signal. It's 100% accurate because the threshold for being marked correct is "price moved < ±1% in either direction" — the system only fires `NEUTRAL_hold` when it sees no signal, and no signal means the market is genuinely quiet.

**Q: Can I trade this for real?**

You can, but: (1) you need live Bybit API keys, (2) you should paper-trade for at least 30 days first (`scripts/backtest/paper_trade_30d.py`), and (3) you should override the position sizing — the system fires signals but doesn't size them.

---

## 📖 Further reading

- **[docs/JOURNEY.md](docs/JOURNEY.md)** — 3-month retrospective, day-by-day
- **[docs/METHODOLOGY.md](docs/METHODOLOGY.md)** — how the system actually works (data flow, indicator math, calibration loop)
- **[docs/RESULTS.md](docs/RESULTS.md)** — live signal results, by-direction breakdown, calibration tier analysis
- **[docs/PITFALLS.md](docs/PITFALLS.md)** — failure modes documented for the next person
- **[docs/archive/](docs/archive/)** — historical analysis briefs

## 📜 License

MIT — see [LICENSE](LICENSE). Do whatever you want with the code; cite the source if it helps you.

## Topics

`crypto` `trading` `learning` `backtest` `self-learning` `hermes-agent` `tutorial` `quant` `signal-generation` `bybit`
