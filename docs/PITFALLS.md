# Pitfalls

> Every failure mode I hit during the 3-month project, written down so the next person can skip them.

This is the most practically useful doc in the repo. The narrative in `JOURNEY.md` tells you *what* happened; this tells you *what to watch out for*.

## 1. Treating "no signal" as "no information"

**Symptom:** The `NEUTRAL_hold` action was being treated as a "system didn't fire" event, not as a "system is signaling no-trade" event. As a result, the 27/27 (100%) accuracy on `NEUTRAL_hold` was invisible in the scorecard.

**Cause:** The output schema lumped `NEUTRAL_hold` in with other low-confidence actions. There was no separate category for "system is signaling 'sit out.'"

**Fix:** Explicitly categorize `NEUTRAL_hold` as a first-class prediction with its own outcome bucket. Treat "the system said no-trade and was right" as a *positive* signal of system calibration, not a null event.

**Cost:** I didn't realize the system's strongest signal was the absence of a signal for ~6 weeks.

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

## 4. Filters that improve backtest don't improve live

**Symptom:** Adding MACD agreement filter, momentum confirmation, regime filter (BTC > 200 EMA) — each one improved the apparent quality of signals in backtesting, but live accuracy barely moved.

**Cause:** The live signal generator had different timing and different entry logic than the test. Filters that "improve" the backtested version don't translate to the live version if the architectures are different.

**Fix:** Apply filters directly to the live signal generator and measure on live accuracy, not on a parallel backtest. The only test that matters is the live one.

**Cost:** ~3 weeks of chasing filter combinations that didn't move the live accuracy number.

## 5. Mixing demo and live credentials

**Symptom:** A test script accidentally used live API credentials instead of demo. Three orders got placed on the live exchange while I was running a "dry-run" sanity check.

**Cause:** The bridge script read `api_key`/`api_secret` from a hardcoded CONFIG dict, and the demo flag was a separate variable that I forgot to set. There was no environment-based credential isolation.

**Fix:** Bridge scripts now read credentials from environment variables, with `BYBIT_DEMO` env var as the explicit gate. Hardcoded credentials are placeholders; live requires env vars to be set explicitly.

**Cost:** 3 unintended live orders. ~$40 in slippage. Significant cortisol.

## 6. Prediction registry drift

**Symptom:** Two copies of `prediction_registry.json` and `learning_weights.json` exist (one in `learn-crypto`, one in `crypto-portfolio-monitor-learning`). They diverged by 13 predictions.

**Cause:** Two different scripts wrote to two different files with overlapping concerns. Neither had a single source of truth.

**Fix:** Single canonical location for each artifact (this repo's `data/` directory). The other repos either read from there or are deprecated.

**Cost:** ~1 day of figuring out which file was the real one.

## 7. The "indicator weight" trap

**Symptom:** I spent a week tuning the indicator weights in `learning_weights.json` by hand, trying to find the "optimal" combination. The optimal combination had 0% accuracy on the live signal generator.

**Cause:** Indicator weights are not a hyperparameter to be tuned. They are a *reflection* of the system's actual recent performance. Manually tuning them decouples them from reality and reintroduces overfitting.

**Fix:** Indicator weights must only be updated by `learning_engine.py` based on verified outcomes. Manual editing is forbidden. (This is now policy, not enforced — the repo is read-only.)

**Cost:** ~1 week of tuning that made the system worse.

## 8. The "AI will fix it" anti-pattern

**Symptom:** When the live signal generator kept losing, I added an LLM step to `hermes_crypto_analysis.py`. The LLM was supposed to "interpret" the indicators and produce a better signal. It didn't help.

**Cause:** LLMs are not oracles. Passing structured technical indicators to an LLM and asking "what do you think?" produces an answer that is no better than the indicators themselves. Sometimes worse, because the LLM can hallucinate context that isn't in the data.

**Fix:** The LLM step is now optional and runs in parallel with the indicator-only path, not as a replacement. If the LLM disagrees with the indicator-only signal, the system fires `NEUTRAL_hold` (the most accurate action).

**Cost:** ~2 weeks of "if I just prompt the model better, it'll figure it out."

## 9. The "more data" fallacy

**Symptom:** I added Open Interest and funding rate to the indicator set, expecting them to boost accuracy. They showed 0 signal history because the prediction cycle didn't use them yet. They had 65–68% "accuracy" on nothing.

**Cause:** I added indicators to the indicator list before the prediction cycle was actually consuming them. They showed up in `learning_weights.json` with 0 signal count and a fake accuracy placeholder.

**Fix:** Either the indicator is wired into `predict_cycle.py` or it doesn't appear in `learning_weights.json`. No ghosts.

**Cost:** ~3 days of chasing a phantom 65%-accuracy signal that didn't exist.

## 10. The "asymmetric loss" blind spot

**Symptom:** The system is symmetric — it treats a wrong `BULLISH_buy` (lost 2%) the same as a wrong `BEARISH_sell` (lost 2%). But the scorecard doesn't weight outcomes by actual PnL.

**Cause:** "Correct" was defined as a directional move ≥ 1%, regardless of magnitude. A move of exactly 1.0% counts the same as a move of 10%.

**Fix:** Recompute accuracy with magnitude weighting. The result is the same: 26% accuracy. But at least it's the right kind of 26%.

**Cost:** Mostly conceptual. The numbers didn't change much, but the framing did.

## 11. The "test on the same window you trained on" trap

**Symptom:** Filter improvements (regime filter, MACD agreement) looked great in their initial test window. When the regime changed or the lookback extended, the gains mostly disappeared.

**Cause:** The original test windows happened to be ones where the filter aligned with the dominant trend. Rolling out-of-sample windows revealed the gain was window-specific, not a real improvement.

**Fix:** Test on multiple rolling windows (out-of-sample) before declaring a filter works. A single-window test is a hypothesis, not a result.

**Cost:** I trusted the regime filter for two weeks before realizing it was regime-specific.

## 12. The "demo mode" false confidence

**Symptom:** I was running the system in demo mode for weeks. It was "working" — every trade fired correctly. Then I switched to live mode and three orders failed with cryptic Bybit errors.

**Cause:** Demo mode has different rate limits, different error semantics, and different liquidity. Code that "works" in demo can fail silently in live.

**Fix:** Every script must be tested with a real-money minimum order (the smallest position size the exchange allows) before any size increase. Demo is for development; real-minimum is for validation.

**Cost:** ~3 hours of debugging on a Sunday morning.

## 13. The "I'll just commit the .env to git" trap

**Symptom:** None — I caught it before it shipped. But the code had `api_key` and `api_secret` hardcoded in `CONFIG` dicts in two scripts.

**Cause:** Early development velocity over discipline. The credentials were testnet/demo, so they didn't *feel* sensitive.

**Fix:** Scrubbed before publishing this repo. All credentials are now `os.environ.get()` calls with placeholder defaults. `.env` is in `.gitignore`.

**Cost:** None directly. But it was a close call — I almost shipped this repo with hardcoded testnet keys, which would have set a bad precedent for future scripts.

## 14. The "single source of truth" fragmentation

**Symptom:** Four private repos, all containing overlapping crypto work. `learn-crypto`, `codex-trading`, `hermes-crypto-skills`, `crypto-portfolio-monitor-learning`. Each had partial state.

**Cause:** The project evolved incrementally. New repos got created when old ones felt "done" or "in a different domain." No central architecture document.

**Fix:** This archive. Single repo, single structure, single source of truth for the historical record. The other four repos are now archived with redirect notices pointing here.

**Cost:** This consolidation effort itself — about a day to merge, organize, scrub, document, and publish.

## 15. The "cross-asset contamination" trap

**Symptom:** The original codex-trading repo contained both forex/XAU backtests AND crypto live signals. Mixing them in one repo made the narrative confusing — the backtests were on EURUSD/GBPUSD/XAUUSD, the live signals were on BTCUSDT/ETHUSDT. Anyone reading the repo would assume they were the same system.

**Cause:** "It's all trading, why separate it?" was the original reasoning. In practice, the backtest lab and the live signal generator had nothing in common except the indicator names.

**Fix:** This crypto-only repo. The forex/XAU backtest scripts and CSVs are removed. If you want the cross-asset version, it's a separate workstream.

**Cost:** ~1 day to audit, remove, and re-document. But the cleanup made the repo's purpose unambiguous.

## A meta-lesson

Most of these pitfalls share a common pattern: **the system rewarded me for working on it, even when the work wasn't making the system better.** Adding indicators felt productive. Tuning weights felt productive. Building backtests felt productive. None of it moved the live accuracy number much.

The single thing that actually moved the needle was **admitting the live system doesn't work and changing the framing** — from "signal generator" to "calibration experiment." That reframing took five minutes and a fresh look at the scorecard.

If you take one thing from this doc: **when the numbers stop moving, stop working on the system and start working on the framing.** The system is a mirror. If you don't like what it shows, change what you're looking at.
