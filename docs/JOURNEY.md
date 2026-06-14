# The 3-Month Journey

> Day-by-day retrospective of building a crypto signal generator, watching it lose money, and learning why.

This is the long version. The README gives you the headlines; this gives you the texture.

## Prologue — Why I started (late February 2026)

I had been trading crypto casually for about a year. Mostly buys on Coinbase, held for weeks or months, occasionally sold into pumps. The whole "HODL" mindset. My total return was positive because I bought BTC at $30k and ETH at $1.6k in 2023, not because I had any skill.

In February I started reading about quantitative trading. The argument that hooked me was:

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

## Phase 2 — Backtests will save us (April 2026)

Once the live signal generator was clearly losing, I needed a better testbed. I built the backtest lab.

**v6 — Bollinger Band squeeze + RSI (April 8)**

The idea: BB squeeze identifies consolidation, RSI oversold identifies the breakout direction. Live trade on the next candle after squeeze + oversold.

Results (`backtest_v6_mt5_results.csv`):
- 212 trades
- 47.2% win rate
- +3.8% PnL

Not bad for a first cut. The profit factor was 1.18.

**v7 — Add MACD filter (April 15)**

v6 took both long and short signals on RSI oversold/overbought. v7 added: only take the long if MACD is above zero, only take the short if MACD is below zero. Removed ~30% of the trades, kept the better half.

Results (`backtest_v7_mt5_param_sweep.csv`):
- 312 trades (more data because of parameter sweep)
- 51.4% win rate
- +8.1% PnL

**v8 — Add momentum + volume profile (April 22)**

Filtered trades further: only enter if 1h momentum confirms and volume profile shows acceptance above/below the level.

Results (`backtest_v8_new_strats.csv`):
- 287 trades
- 54.8% win rate
- +12.4% PnL

**v9 — Add regime filter (April 29)**

Only take long signals when BTC is above its 200 EMA (i.e., bullish regime). Skip everything in bear regimes. This was the single biggest improvement.

Results (`backtest_v9_filters.csv`):
- 264 trades
- 58.3% win rate
- +18.7% PnL

**v10 — Full ensemble (May 10)**

Combined all the above into a final strategy. Multi-timeframe confirmation: signal must align on 15m, 1h, and 4h.

Results (`BACKTEST_FINAL_v10.csv`):
- 341 trades
- 61.2% win rate
- +24.9% PnL

**v11 — Yahoo macro overlay (May 25)**

Added a macro overlay: when SPY is trending up, bias long crypto; when SPY is trending down, bias short. (Correlation is imperfect but real.)

Results (`backtest_v11_yahoo.csv`):
- 298 trades
- 63.8% win rate
- +29.3% PnL

The progression felt great. From 47% to 64% win-rate. From +3.8% to +29.3% PnL. Six iterations of careful work.

**The catch.**

While the backtest was climbing, the live signal generator was still using the v6-era logic. I had been so deep in backtest iteration that I hadn't re-deployed the new entry logic to the live `predict_cycle.py`. When I finally did, in late May, the live accuracy barely moved: 27% → 28%.

The reason, in retrospect, is obvious: **the backtest entry logic was bespoke and clean. The live entry logic was the messy indicator buffet from Phase 1, with extra filters duct-taped on.** They weren't the same strategy. They had two different scorecards because they were two different strategies.

**What I learned in Phase 2:**

- Backtest iteration is rewarding because the feedback loop is fast and the numbers always go up. That makes it seductive in a way that can hide the fact that live results aren't moving.
- Filters that improve backtest accuracy don't necessarily improve live accuracy if the live signal generator has different timing / different entry logic.
- Win-rate progression (47 → 64%) is not the same as edge progression. PnL progression (+3.8% → +29.3%) reflects more filters removing trades, not the remaining trades being better in any absolute sense.

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
| Apr 1 | Began backtest lab | 18.5% |
| Apr 8 | v6 backtest: BB + RSI | (backtest 47.2%) |
| Apr 15 | v7 backtest: + MACD filter | (backtest 51.4%) |
| Apr 22 | v8 backtest: + momentum | (backtest 54.8%) |
| Apr 29 | v9 backtest: + regime filter | (backtest 58.3%) |
| May 10 | v10 backtest: full ensemble | (backtest 61.2%) |
| May 15 | Discovered `NEUTRAL_hold` is 100% | 22.3% |
| May 20 | Flipped policy: sit out unless LOW-confidence BULLISH | 24.1% |
| May 25 | v11 backtest: + Yahoo macro | (backtest 63.8%) |
| Jun 1 | Started paper-trade cycle | 25.8% |
| Jun 12 | Paper trade cycle ended | 26.1% |
| Jun 20 | Final scorecard snapshot, this archive | **26.3%** |

The backtest and the live system are two different curves, and they tell two different stories. Both stories are in this repo.

---

Next: [METHODOLOGY.md](METHODOLOGY.md) — how the system actually works, in detail.
