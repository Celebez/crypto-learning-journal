# Results

> The backtest progression, the live signal results, and the gap between them.

## Backtest progression (the headline chart)

| Version | Strategy | Trades | Win-rate | PnL% | Profit factor |
|---------|----------|--------|----------|------|---------------|
| v6      | BB squeeze + RSI | 212 | 47.2% | +3.8% | 1.18 |
| v7      | + MACD filter (param sweep) | 312 | 51.4% | +8.1% | 1.31 |
| v8      | + momentum + volume profile | 287 | 54.8% | +12.4% | 1.48 |
| v9      | + regime filter (BTC > 200 EMA) | 264 | 58.3% | +18.7% | 1.79 |
| v10     | full ensemble (MTF confirm) | 341 | 61.2% | +24.9% | 2.11 |
| v11     | + Yahoo SPY macro overlay | 298 | 63.8% | +29.3% | 2.34 |

**Plot this in your head:** a clean monotonic climb across six iterations. From "barely profitable" to "convincingly profitable." Each version's CSV is in `data/backtests/`. The code for each version is in `scripts/backtest/`.

```
PnL% by version
v6   ███▌                                  +3.8%
v7   ████████                              +8.1%
v8   ████████████▌                         +12.4%
v9   ███████████████████▏                  +18.7%
v10  ██████████████████████████▏           +24.9%
v11  █████████████████████████████▏        +29.3%
```

If you stopped reading here, you'd think I had a profitable strategy. **I don't.** Keep reading.

## The backtest assumptions

Each version of the backtest lab makes the same set of simplifying assumptions:

1. **No slippage.** Limit orders fill at the exact price specified.
2. **No fees.** Bybit charges 0.075% maker / 0.075% taker on perpetuals. Over 300 trades, that's ~45% of PnL eaten by fees. v11's +29.3% becomes **-15.7%** after fees.
3. **No funding rate.** Perpetuals have an 8-hour funding payment that can be ±0.01–0.05%. Over multi-day holds, this is significant. Not modeled.
4. **Perfect entry timing.** The strategy enters at the close of the signal candle. In reality, signal-to-fill latency is 100–500ms on REST.
5. **No liquidity constraints.** The backtest assumes any size order fills. For larger sizes, slippage is severe.
6. **Survivorship-free coin universe.** All coins that existed during the backtest window are in the universe, including ones that delisted or rugged.

When I rebuild v11 with realistic fees + 0.05% slippage + funding, the win-rate stays at 63.8% but the PnL drops to **-8% to -12%**. That is, the backtest is structurally overstating performance by 30+ percentage points.

The CSV files in `data/backtests/` are the *unadjusted* numbers. I left them unadjusted because that's what the backtest engine produces, and because the lesson is more honest that way.

## Live signal results (the less-flattering chart)

| Period | Predictions | Verified | Correct | Accuracy | PnL% |
|--------|-------------|----------|---------|----------|------|
| Phase 1 (Mar 5 – Apr 1) | 62 | 62 | 9 | 14.5% | -14.2% |
| Phase 2 (Apr 1 – May 1) | 54 | 54 | 13 | 24.1% | -8.7% |
| Phase 3 (May 1 – Jun 20) | 60 | 59 | 23 | 39.0% | -13.6% |
| **Total** | **176** | **175** | **45** | **25.7%** | **-36.5%** |

Note: the totals in the live table use slightly different bucketing than `scorecard.json` (which has 72 correct, 41.1% of verified). The difference is the "partial success" category — predictions where the system was "kind of right" (e.g., a BULLISH_buy that moved up but not enough to be marked "correct"). Both views are honest; they just count differently.

## The backtest-vs-live gap

If the backtest is 64% accurate and the live signal is 26% accurate, where's the gap?

```
Backtest entry signal:                       Live entry signal:
─────────────────────                       ─────────────────
1. Wait for BB squeeze                        1. Compute all 6 indicators
2. Wait for RSI < 30                          2. Sum weighted signals
3. Check MACD > 0                             3. Apply calibration multiplier
4. Check 1h momentum confirms                 4. Fire if adjusted_conf ≥ 0.65
5. Check 4h timeframe confirms
6. Check BTC regime filter
7. Check SPY macro overlay
                                             → fires 5-10x more often
                                             → with weaker per-trade conviction
                                             → with less multi-TF alignment
```

The backtest has **seven sequential filters**. The live signal generator has **two** (weighted sum + threshold). The backtest is selective; the live system fires on anything that looks mildly bullish.

**This is the lesson.** The backtest lab evolved into a careful, multi-filter strategy. The live signal generator stayed at the Phase 1 "indicator buffet" architecture. They were never the same system.

## The `NEUTRAL_hold` breakout

When I sliced the live results by direction, the `NEUTRAL_hold` category was 27/27 (100%). This was hiding in the scorecard as "the absence of a signal" until I explicitly bucketed it.

```
By direction (live, n=175 verified):

NEUTRAL_hold   ████████████████████████████  100.0%  (27 trades, 0 loss)
BEARISH_sell   ████████▏                    27.2%   (81 trades)
BULLISH_buy    ███▊                         14.0%   (43 trades)
```

The system is, at heart, a **"do nothing" detector** that occasionally also takes a directional guess. The directional guesses lose money. The "do nothing" calls don't.

This reframes the entire product. Instead of "crypto signal generator," it's "dead-zone detector with optional directional overlay." The overlay loses money; the dead-zone detection is reliable.

## The `HIGH`-confidence paradox

| Confidence tier | Verified | Correct | Accuracy |
|-----------------|----------|---------|----------|
| HIGH (≥0.85)    | 9        | 0       | **0.0%** |
| MEDIUM (0.65–0.85) | 75     | 16      | 21.3% |
| LOW (<0.65)     | 58       | 37      | 63.8% |

The system is **most accurate when it is least confident.** Every "very confident" call was wrong.

This is a calibration failure of the worst kind: the system's confidence is *inversely* correlated with its accuracy. The higher it claims to be sure, the more likely it is to be wrong.

There are a few possible explanations:

1. **Regime change at the boundary.** The 0.85+ confidence cases are concentrated in two weeks in early May when the market was trending strongly. The system got the direction right *during* the trend but the timing wrong — by the time it was 85%+ confident, the move was already mostly done. The price then reversed, marking the prediction "wrong."
2. **Self-fulfilling skepticism.** The calibration loop down-weights the system as it accumulates wrong calls. So when it does fire HIGH, it's after a streak of correct MEDIUM calls — but those streaks ended.
3. **Statistical fluke.** 9 trades is a small sample. With 95% confidence intervals, 0/9 is consistent with a true accuracy anywhere from 0% to ~30%. So this could just be bad luck.

I lean toward explanation #1 (regime/timing) but can't rule out #3.

## The forward-test (paper trade) cycle

In late May I ran a 30-day paper-trade cycle. Results:

- **Trades fired:** 38
- **Winners:** 11 (28.9%)
- **Losers:** 27 (71.1%)
- **PnL:** -8.2%
- **`NEUTRAL_hold` reclassified:** 12 (price moved < 1% in either direction 12/12 times — 100%)

The 28.9% win-rate in paper-trade matched the scorecard's 26% closely. The system is, at minimum, *consistently* bad.

## The honest summary

| What works | What doesn't |
|------------|--------------|
| Identifying dead zones (NEUTRAL_hold) | Identifying good entry points |
| Detecting regime change (BB squeeze → expansion) | Timing the entry within the expansion |
| Multi-timeframe alignment | Single-timeframe directional calls |
| Backtest ensemble (with filters) | Live signal generator (without filters) |
| Adaptive weight decay (slow forget) | Confidence calibration (inverse correlation) |

The system is a **calibration experiment, not a trading strategy.** It taught me a lot about market microstructure, indicator behavior across regimes, and the difference between backtest performance and live performance. It did not teach me how to make money trading crypto.

That's fine. That was the goal.

---

Next: [PITFALLS.md](PITFALLS.md) — every failure mode I hit, so the next person doesn't have to.
