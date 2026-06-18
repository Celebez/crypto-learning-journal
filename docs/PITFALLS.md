# Pitfalls

> Every failure mode I hit during the 3-month project, written down so the next person can skip them.

This is the most practically useful doc in the repo. The narrative in `JOURNEY.md` tells you *what* happened; this tells you *what to watch out for*.

## 1. Backtesting the wrong strategy

**Symptom:** Backtest shows 64% win-rate. Live signal generator shows 26% accuracy. Both have been running for weeks.

**Cause:** The backtest lab evolved into a careful, multi-filter strategy. The live signal generator stayed at the Phase 1 indicator-buffet architecture. They are not the same strategy, but I was comparing them as if they were.

**Fix:** The backtest entry function must be the same function the live system uses. If they diverge, the backtest is testing a hypothetical strategy that doesn't exist in production.

**Cost:** ~3 weeks of chasing a backtest curve that didn't reflect reality.

## 2. Indicator buffet overfitting

**Symptom:** RSI alone on its own historical window is 90%+ accurate. Combine RSI + MACD + BB + EMA in a live signal generator, accuracy drops to 26%.

**Cause:** Each indicator has its own historical accuracy. Combining them with simple AND/OR logic creates a decision boundary that overfits the *combination's* historical window. The individual indicator accuracies are not preserved under combination.

**Fix:** Either (a) pick one indicator and trade it well, or (b) use a learned ensemble (stacking with cross-validation), or (c) accept the lower combined accuracy and use it as a filter, not a signal generator.

**Cost:** ~2 weeks of "the indicators must be wrong, let me tune them."

## 3. Confidence is inversely correlated with accuracy

**Symptom:** The `HIGH` confidence tier (≥0.85) went 0/9 in the live results. The `LOW` confidence tier (<0.65) went 37/58 (63.8%). The system is more accurate when it is least sure.

**Cause:** Two contributing factors:
1. **Regime lag.** By the time the system is 85%+ confident, the move it was detecting is mostly done. The price then reverses, marking the prediction "wrong."
2. **Calibration decay.** The system's calibration loop down-weights itself as it accumulates losses. So `HIGH` confidence fires after a streak of correct MEDIUM calls — but the streak has just ended.

**Fix:** Either invert the confidence policy (trade LOW confidence, skip HIGH) or redesign confidence so it's based on the *post*-calibration probability, not the *pre*-calibration one.

**Cost:** ~9 real losing trades that the system loudly predicted would win.

## 4. Treating "no signal" as "no information"

**Symptom:** The `NEUTRAL_hold` action was being treated as a "system didn't fire" event, not as a "system is signaling no-trade" event. As a result, the 27/27 (100%) accuracy on `NEUTRAL_hold` was invisible in the scorecard.

**Cause:** The output schema lumped `NEUTRAL_hold` in with other low-confidence actions. There was no separate category for "system is signaling 'sit out.'"

**Fix:** Explicitly categorize `NEUTRAL_hold` as a first-class prediction with its own outcome bucket. Treat "the system said no-trade and was right" as a *positive* signal of system calibration, not a null event.

**Cost:** I didn't realize the system's strongest signal was the absence of a signal for ~6 weeks.

## 5. Backtesting without fees, slippage, or funding

**Symptom:** v11 backtest showed +29.3% PnL over 298 trades. Realistic fee+slippage+funding adjustment brings it to -8% to -12%.

**Cause:** The backtest engine used ideal fills at signal candle close, with no fee model, no slippage model, and no funding-rate accounting. Perpetuals charge ~0.075% per side per trade. Over 300 trades, that's a 45% PnL haircut.

**Fix:** Every backtest must include: per-side fees, slippage model (volatility-scaled), funding rate carry for multi-day holds. Without these, +29.3% is meaningless.

**Cost:** ~30 percentage points of phantom PnL that I spent a week trying to figure out why the live version wasn't matching.

## 6. Mixing demo and live credentials

**Symptom:** A test script accidentally used live API credentials instead of demo. Three orders got placed on the live exchange while I was running a "dry-run" sanity check.

**Cause:** The bridge script read `api_key`/`api_secret` from a hardcoded CONFIG dict, and the demo flag was a separate variable that I forgot to set. There was no environment-based credential isolation.

**Fix:** Bridge scripts now read credentials from environment variables, with `BYBIT_DEMO` env var as the explicit gate. Hardcoded credentials are placeholders; live requires env vars to be set explicitly.

**Cost:** 3 unintended live orders. ~$40 in slippage. Significant cortisol.

## 7. Prediction registry drift

**Symptom:** Two copies of `prediction_registry.json` and `learning_weights.json` exist (one in `learn-crypto`, one in `crypto-portfolio-monitor-learning`). They diverged by 13 predictions.

**Cause:** Two different scripts wrote to two different files with overlapping concerns. Neither had a single source of truth.

**Fix:** Single canonical location for each artifact (this repo's `data/` directory). The other repos either read from there or are deprecated.

**Cost:** ~1 day of figuring out which file was the real one.

## 8. The "indicator weight" trap

**Symptom:** I spent a week tuning the indicator weights in `learning_weights.json` by hand, trying to find the "optimal" combination. The optimal combination had 0% accuracy on the live signal generator.

**Cause:** Indicator weights are not a hyperparameter to be tuned. They are a *reflection* of the system's actual recent performance. Manually tuning them decouples them from reality and reintroduces overfitting.

**Fix:** Indicator weights must only be updated by `learning_engine.py` based on verified outcomes. Manual editing is forbidden. (This is now policy, not enforced — the repo is read-only.)

**Cost:** ~1 week of tuning that made the system worse.

## 9. The "AI will fix it" anti-pattern

**Symptom:** When the live signal generator kept losing, I added an LLM step to `hermes_crypto_analysis.py`. The LLM was supposed to "interpret" the indicators and produce a better signal. It didn't help.

**Cause:** LLMs are not oracles. Passing structured technical indicators to an LLM and asking "what do you think?" produces an answer that is no better than the indicators themselves. Sometimes worse, because the LLM can hallucinate context that isn't in the data.

**Fix:** The LLM step is now optional and runs in parallel with the indicator-only path, not as a replacement. If the LLM disagrees with the indicator-only signal, the system fires `NEUTRAL_hold` (the most accurate action).

**Cost:** ~2 weeks of "if I just prompt the model better, it'll figure it out."

## 10. The "more data" fallacy

**Symptom:** I added Open Interest and funding rate to the indicator set, expecting them to boost accuracy. They showed 0 signal history because the prediction cycle didn't use them yet. They had 65–68% "accuracy" on nothing.

**Cause:** I added indicators to the indicator list before the prediction cycle was actually consuming them. They showed up in `learning_weights.json` with 0 signal count and a fake accuracy placeholder.

**Fix:** Either the indicator is wired into `predict_cycle.py` or it doesn't appear in `learning_weights.json`. No ghosts.

**Cost:** ~3 days of chasing a phantom 65%-accuracy signal that didn't exist.

## 11. The "asymmetric loss" blind spot

**Symptom:** The system is symmetric — it treats a wrong `BULLISH_buy` (lost 2%) the same as a wrong `BEARISH_sell` (lost 2%). But the scorecard doesn't weight outcomes by actual PnL.

**Cause:** "Correct" was defined as a directional move ≥ 1%, regardless of magnitude. A move of exactly 1.0% counts the same as a move of 10%.

**Fix:** Recompute accuracy with magnitude weighting. The result is the same: 26% accuracy. But at least it's the right kind of 26%.

**Cost:** Mostly conceptual. The numbers didn't change much, but the framing did.

## 12. The "test on the same window you trained on" trap

**Symptom:** v9 backtest (regime filter) showed 58.3% win-rate. When I ran the same logic on a different window, it was 49%.

**Cause:** The regime filter (BTC > 200 EMA) was tuned on a window where BTC was in a strong uptrend. On a choppy window, the filter flipped too often and got whipsawed.

**Fix:** Backtest on multiple windows (rolling out-of-sample) before declaring a strategy works. A single-window backtest is a hypothesis, not a result.

**Cost:** I trusted v9 for two weeks before realizing it was regime-specific.

## 13. The "demo mode" false confidence

**Symptom:** I was running the system in demo mode for weeks. It was "working" — every trade fired correctly. Then I switched to live mode and three orders failed with cryptic Bybit errors.

**Cause:** Demo mode has different rate limits, different error semantics, and different liquidity. Code that "works" in demo can fail silently in live.

**Fix:** Every script must be tested with a real-money minimum order (the smallest position size the exchange allows) before any size increase. Demo is for development; real-minimum is for validation.

**Cost:** ~3 hours of debugging on a Sunday morning.

## 14. The "I'll just commit the .env to git" trap

**Symptom:** None — I caught it before it shipped. But the code had `api_key` and `api_secret` hardcoded in `CONFIG` dicts in two scripts.

**Cause:** Early development velocity over discipline. The credentials were testnet/demo, so they didn't *feel* sensitive.

**Fix:** Scrubbed before publishing this repo. All credentials are now `os.environ.get()` calls with placeholder defaults. `.env` is in `.gitignore`.

**Cost:** None directly. But it was a close call — I almost shipped this repo with hardcoded testnet keys, which would have set a bad precedent for future scripts.

## 15. The "single source of truth" fragmentation

**Symptom:** Four private repos, all containing overlapping crypto work. `learn-crypto`, `codex-trading`, `hermes-crypto-skills`, `crypto-portfolio-monitor-learning`. Each had partial state.

**Cause:** The project evolved incrementally. New repos got created when old ones felt "done" or "in a different domain." No central architecture document.

**Fix:** This archive. Single repo, single structure, single source of truth for the historical record. The other four repos still exist for ongoing operational state but are no longer the canonical reference.

**Cost:** This consolidation effort itself — about a day to merge, organize, scrub, document, and publish.

## A meta-lesson

Most of these pitfalls share a common pattern: **the system rewarded me for working on it, even when the work wasn't making the system better.** Backtest iteration felt productive. Tuning weights felt productive. Adding indicators felt productive. None of it moved the live accuracy number.

The single thing that actually moved the needle was **admitting the live system doesn't work and changing the framing** — from "signal generator" to "calibration experiment." That reframing took five minutes and a fresh look at the scorecard.

If you take one thing from this doc: **when the numbers stop moving, stop working on the system and start working on the framing.** The system is a mirror. If you don't like what it shows, change what you're looking at.
