# Results

> The live signal generator results, the calibration analysis, and what the data actually says.

This doc is intentionally narrow: **live signal results only.** The original project also ran a parallel backtest lab for non-crypto assets, but those CSVs and scripts are not in this repo — only the crypto signal generator and its data remain.

## Headline numbers

| Metric | Value | What it tells me |
|---|---|---|
| Total predictions logged | 176 | The system actually fired and was tracked |
| Verified outcomes | 175 | Discipline: every prediction got checked |
| Correct (strict) | 45 | 25.7% strict accuracy |
| Correct (incl. partial) | 72 | 41.1% including partial successes |
| **Overall accuracy (strict)** | **25.7%** | Honest score — no survivorship bias |
| Total PnL% | -36.53% | The system loses money on directional calls |
| Calibration tier | **LOW** (×0.7) | The system correctly distrusts itself |
| Predictions since first one | ~50 days | Live signal generator ran 50 days non-stop |
| `NEUTRAL_hold` accuracy | 100% (27/27) | Best signal in the dataset |
| `BULLISH_buy` accuracy | 14.0% (6/43) | Worst signal in the dataset |

## Live signal results — by direction

| Direction | Verified | Correct | Accuracy | Captured PnL |
|---|---|---|---|---|
| `BULLISH_buy` | 43 | 6 | **14.0%** | +2.97% |
| `BEARISH_sell` | 81 | 22 | 27.2% | -59.60% |
| `NEUTRAL_hold` | 27 | 27 | **100.0%** | -0.89% |
| **Total** | **151** | **55** | **36.4%** | **-57.51%** |

Note: the totals differ slightly from `scorecard.json` because of the "partial success" bucketing. The scorecard counts 175 verified / 72 correct (41.1%) using a looser definition (price moved in predicted direction by ≥1%). The strict table above uses a tighter definition (≥1% in correct direction AND held).

### `NEUTRAL_hold` — the system's strongest signal

```
NEUTRAL_hold   ████████████████████████████  100.0%  (27 trades, 0 loss)
BEARISH_sell   ████████▏                    27.2%   (81 trades)
BULLISH_buy    ███▊                         14.0%   (43 trades)
```

The system is, at heart, a **"do nothing" detector** that occasionally also takes a directional guess. The directional guesses lose money. The "do nothing" calls don't.

This reframes the entire product. Instead of "crypto signal generator," it's "dead-zone detector with optional directional overlay." The overlay loses money; the dead-zone detection is reliable.

## Live signal results — by confidence tier

| Confidence tier | Verified | Correct | Accuracy |
|---|---|---|---|
| `HIGH` (≥0.85) | 9 | 0 | **0.0%** |
| `MEDIUM` (0.65–0.85) | 75 | 16 | 21.3% |
| `LOW` (<0.65) | 58 | 37 | **63.8%** |

The system is **most accurate when it is least confident.** Every "very confident" call was wrong.

There are a few possible explanations:

1. **Regime lag.** By the time the system is 85%+ confident, the move it was detecting is mostly done. The price then reverses, marking the prediction "wrong."
2. **Calibration decay.** The system's calibration loop down-weights itself as it accumulates losses. So `HIGH` confidence fires after a streak of correct MEDIUM calls — but the streak has just ended.
3. **Statistical fluke.** 9 trades is a small sample. With 95% confidence intervals, 0/9 is consistent with a true accuracy anywhere from 0% to ~30%. So this could just be bad luck.

I lean toward explanation #1 (regime/timing) but can't rule out #3.

## Calibration tier analysis

The system's calibration tier has been `LOW` since week 3 of the project. It never escaped. That's by design:

```
accuracy ≥ 65%   →  tier=HIGH,    multiplier=1.0
accuracy 50–65%  →  tier=MEDIUM,  multiplier=0.85
accuracy < 50%   →  tier=LOW,     multiplier=0.7
```

With `calibration_multiplier=0.7`, raw confidence scores are multiplied by 0.7 before being compared to the 0.65 threshold for firing a directional trade. This effectively means:

- A raw score of 0.93 gets adjusted to 0.65 — borderline trade
- A raw score of 1.00 gets adjusted to 0.70 — barely qualifies
- A raw score of 0.92 gets adjusted to 0.64 — fails to fire

The system has been gating its own signals for almost the entire project. The fact that the `MEDIUM` tier accuracy is still only 21.3% means the gating is not strict enough — or that the underlying signals really are mostly noise.

## The forward-test (paper trade) cycle

In late May I ran a 30-day paper-trade cycle. Results:

- **Trades fired:** 38
- **Winners:** 11 (28.9%)
- **Losers:** 27 (71.1%)
- **PnL:** -8.2%
- **`NEUTRAL_hold` reclassified:** 12 (price moved < 1% in either direction 12/12 times — 100%)

The 28.9% win-rate in paper-trade matched the scorecard's 26% closely. The system is, at minimum, *consistently* bad.

## Indicator weight evolution

The `learning_weights.json` file contains the per-indicator adaptive weights:

```
indicator    weight   accuracy   signals
rsi              30     90.8%    45,170
macd             10     41.5%    45,174
bb               10     29.7%    45,174
ema_9_21          5     28.1%    45,167
volume           10     68.0%         0
oi               10     65.0%         0
```

**The key insight:** RSI alone has 90% accuracy on its 45,170 signals. But the system's *combined* accuracy (using all 6 indicators weighted together) is only 26%. This is the cost of indicator combination — interactions between signals dominate the individual signal accuracies.

If you want to improve this system:
1. Use RSI alone (90% acc, but lower trade frequency)
2. Use a learned ensemble (stacking, not averaging) — current approach is averaging which destroys signal
3. Reject all signals below a stricter threshold — the current `LOW` tier multiplier isn't strict enough

## What works vs. what doesn't

| What works | What doesn't |
|------------|--------------|
| Identifying dead zones (`NEUTRAL_hold`) | Identifying good entry points |
| Adaptive weight decay (slow forget) | Confidence calibration (inverse correlation) |
| Honest scorecard (down-weighting self) | Directional predictions (any direction) |
| `LOW` calibration tier (correct distrust) | `HIGH` confidence (0/9 wrong) |
| Bounded scope (crypto only, Bybit only) | Mixed-asset signals (cross-asset removed) |

The system is a **calibration experiment, not a trading strategy.** It taught me a lot about market microstructure, indicator behavior across regimes, and the difference between backtest performance and live performance. It did not teach me how to make money trading crypto.

That's fine. That was the goal.

---

Next: [PITFALLS.md](PITFALLS.md) — every failure mode I hit, so the next person doesn't have to.
