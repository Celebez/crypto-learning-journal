# The 3-Month Journey

> Day-by-day retrospective of building a crypto signal generator, watching it lose money, and learning why.

This is the long version. The README gives you the headlines; this gives you the texture.

## Prologue — Why I started (early 2026, after 4+ years of crypto trading)

I've been trading crypto since **2021**. Started with spot buys on **Binance**, then moved into **Coinbase** for the regulated UX, and eventually settled into **Bybit** for perpetuals and derivatives. The whole journey — wins, losses, bad entries, late exits — is documented on my X timeline: **[https://x.com/0xCelebez](https://x.com/0xCelebez)**.

Over those four years I did everything wrong at least once: FOMO'd into tops, panic-sold bottoms, over-traded chop, under-traded trends. The total return was positive mostly because I bought BTC and ETH early enough — not because I had any skill.

In early 2026 I started reading about quantitative trading. The argument that hooked me was:

> "If you can't articulate *exactly* why you're entering a trade, you're gambling, not trading."

I wanted to see if I could build a system that *could* articulate exactly why. I didn't expect it to make money. I expected it to teach me something about markets.

## Phase 1 — Indicators are signals (March 2026)

**Week 1–2: Indicator buffet.**

I wired up the obvious ones:
- RSI (14-period)
- MACD (12, 26, 9)
- Bollinger Bands (20, 2)
- EMA crossover (9, 21)
- Volume profile
- Open interest

Each indicator had a "signal" attached: RSI < 30 → buy, RSI > 70 → sell, MACD bullish cross → buy, etc. I combined them with simple AND logic.

First test on historical data: **90%+ accuracy on BTCUSDT 4h.** I was ecstatic for about ten minutes.

**Week 3: Reality check.**

I ran the same logic on ETH and BNB and SOL. The 90% number was BTC-specific and regime-specific. The strategy was *curve-fit* to BTC's 2024 Q4 behavior. On a different coin or different window it was 30–40%.

Then I started live-signaling. I tracked every prediction in `prediction_registry.json`. After two weeks I had 43 verified predictions. **Accuracy: 14%.** Total PnL: -12%.

The backtest said 90%. The live signal said 14%. The gap was not a bug; it was the lesson.

**What I learned in Phase 1:**

- A high accuracy number on a backtest tells you nothing about the future. The market regime that produced it is gone.
- RSI alone, on its own historical window, *is* 90% accurate. RSI combined with three other indicators in a live system is not. Combination introduces interaction overfitting that you can't backtest away.
- "Indicators are signals" is a category error. Indicators are *features*. Signals are decisions made on top of features.

## Phase 2 — Filter experiments and signal refinement (April 2026)

After Phase 1 made it clear that the indicator buffet was overfit, I spent April iterating on which subset of indicators to combine. This phase wasn't a separate backtest lab — it was applied directly to the live signal generator, with each iteration logged in `prediction_registry.json`.

The key experiments:

- **Pure RSI + filter:** RSI alone, with an EMA-trend filter to remove counter-trend signals. Result: fewer trades, similar accuracy.
- **RSI + MACD agreement:** Only fire when RSI and MACD both agree on direction. Result: ~30% fewer trades, accuracy moved from 14% to ~18%.
- **Add volume confirmation:** Only fire when volume confirms the signal (≥1.5× average). Result: marginal improvement on accuracy, but the indicator weight for `volume` stayed at 0 signals because volume data wasn't being captured in the registry at the time.
- **Regime filter (BTC > 200 EMA):** Only take `BULLISH_buy` signals when BTC is above its 200 EMA on the daily chart. Result: filtered out ~40% of low-quality signals during bear regimes.

**What I learned in Phase 2:**

- Filters that improve backtest accuracy don't necessarily improve live accuracy if the live signal generator has different timing / different entry logic. (This is the lesson the original cross-asset backtest lab taught me — the parallel backtest evolved into a different strategy than the live one.)
- Volume and OI indicators look great in `learning_weights.json` (65–68% accuracy), but they had 0 signals tracked at the time because the prediction cycle wasn't logging them. Phantom accuracy is worse than no accuracy.
- Filtering by regime (BTC trend) is the single biggest improvement to live signal quality. Most losing trades happened during regime changes when the system was slow to adapt.

The live accuracy moved from 14% (Phase 1 end) to ~24% (Phase 2 end). Modest gain for a month of work, but the per-filter contribution is documented in the scorecard.

## Phase 3 — Calibration, not prediction (May – early June 2026)

I had a choice after Phase 2: try to fix the live signal generator, or accept that prediction is hard and build a system that knows its own limits.

I chose the second. **Calibration, not prediction.**

The `learning_engine.py` does one thing: it watches the scorecard, and adjusts per-indicator weights so that the system's reported confidence matches its actual hit rate. The `scorecard.json` reflects three calibration tiers:

- `HIGH`: system accuracy ≥ 65%. Confidence multiplier ×1.0.
- `MEDIUM`: 50–65%. Multiplier ×0.85.
- `LOW`: <50%. Multiplier ×0.7.

I was in `LOW` from week 3 of Phase 1 onward and I never escaped it. That's a feature, not a bug: a `LOW`-calibrated system that knows it's bad is more useful than a `HIGH`-calibrated system that doesn't.

**The `NEUTRAL_hold` insight.**

In May I noticed something in the scorecard: `NEUTRAL_hold` — the system firing "no trade here, sit out" — was 27-of-27 correct. 100% accuracy on the hold signal.

This was hiding in plain sight. The system had learned, without being told, that the most reliable thing it could say was "nothing interesting here." That's a huge piece of information. It means:

- The system *can* identify dead zones reliably.
- The system *cannot* identify good entry points reliably.
- Therefore the optimal policy is to only enter trades when the system is *very confident*, and to sit out otherwise.

I had been running the inverse policy: enter when confident, sit out when not. The data said the opposite. I had to flip the policy.

**The paper-trade cycle (late May – early June).**

I ran the system in paper-trade mode for 30 days (`scripts/backtest/paper_trade_30d.py`, `scripts/backtest/forward_test_30d.py`). The results:

- 38 trades fired.
- 11 winners (28.9% — consistent with the scorecard).
- -8.2% PnL.
- 12 of 38 trades were `NEUTRAL_hold` after re-classification. **Of those 12, the price did move in a tradable direction 0 times.** The system correctly identified 12 "do-nothing" setups.

The system is, at best, a sophisticated filter for not taking bad trades. It is not a generator of good ones. That is honest and useful.

**What I learned in Phase 3:**

- A self-aware losing system is more valuable than a confident losing system. The calibration work turned a broken-looking signal generator into a usable risk filter.
- The most reliable signal in the dataset was "no trade." That signal deserves its own UI, its own metric, its own weight in the scorecard.
- The distinction between *prediction accuracy* and *expected value of acting on predictions* is everything. A 30%-accurate signal with a 5:1 payoff is better than a 70%-accurate signal with a 0.8:1 payoff. My system has neither, but at least it knows.

## Epilogue — What I'm keeping

I'm not shutting down the project. I'm changing the framing.

The crypto signal generator lives on as a **risk filter**, not a signal generator. New rules:

1. The system fires a prediction.
2. If the prediction is `NEUTRAL_hold`, do nothing. (100% accurate so far.)
3. If the prediction is `BULLISH_buy` with confidence ≥ 0.7, ignore it. (0% accuracy on 9 trades.)
4. If the prediction is `BEARISH_sell` with confidence 0.5–0.65, *consider* it. (52% accuracy on those, still losing money but closer to breakeven.)
5. Everything else: paper-trade for another 30 days before risking real capital.

The prediction registry keeps growing. The scorecard keeps getting honest. The system keeps learning.

This archive is the snapshot from the end of Phase 3. Everything after this is in the private repos, where the operational state lives.

## Timeline summary

| Date | Event | Scorecard |
|------|-------|-----------|
| Feb 28 | Started reading quant trading material | — |
| Mar 5 | First indicator wiring (RSI alone) | — |
| Mar 12 | First live signal | 0/0 |
| Mar 20 | Reality check: 14% accuracy on 43 trades | 14.0% |
| Apr 1 | Began filter experiments on live signal gen | 18.5% |
| Apr 15 | + MACD agreement filter | 21.0% |
| Apr 29 | + regime filter (BTC > 200 EMA) | 22.5% |
| May 10 | Multi-TF confirmation deployed | 23.5% |
| May 15 | Discovered `NEUTRAL_hold` is 100% | 24.0% |
| May 20 | Flipped policy: sit out unless LOW-confidence BULLISH | 24.5% |
| May 25 | Final ensemble + macro overlay (live) | 25.0% |
| Jun 1 | Started paper-trade cycle | 25.8% |
| Jun 12 | Paper trade cycle ended | 26.1% |
| Jun 20 | Final scorecard snapshot, this archive | **26.3%** |

The progression moved from 14% to 26% over the 3-month learning project. Modest but honest.

---

Next: [METHODOLOGY.md](METHODOLOGY.md) — how the system actually works, in detail.
