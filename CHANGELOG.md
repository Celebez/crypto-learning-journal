# Changelog

All notable changes to this repo are documented here. Dates are backfilled to reflect the iterative work that produced them.

## [1.1.0] — 2026-06-21 — Crypto-only cleanup

### Removed
- All non-crypto backtest scripts (entire `scripts/backtest/` directory — 15 files total)
- All non-crypto backtest CSV results (`data/backtests/` — entire directory deleted)
- Cross-asset-specific archive docs (`AI_PROMPT_RECOMMENDATION.md`, `CODEX_SEGMENTATION_EVALUATION.md`, `SEGMENTATION_INSTRUCTIONS.md`, `SEGMENTATION_PLAN.md`)

### Changed
- **README.md**: removed backtest progression table and backtest-step from tutorial
- **demo.sh / demo.gif**: replaced backtest progression section with "What this system deliberately does NOT do" scope list
- **JOURNEY.md**: condensed Phase 2 from backtest-lab narrative to filter-experiment narrative (applied directly to live signal gen, not parallel backtest)
- **METHODOLOGY.md**: updated "does not backtest against itself" note to reflect new state
- **RESULTS.md**: completely rewritten to focus on live signal results only (no more backtest progression)
- **PITFALLS.md**: replaced cross-asset pitfalls with crypto-only relevant pitfalls (added #15 scope drift trap)
- **CHANGELOG.md**: documents the [1.1.0] crypto-only cleanup

### Reason
The original repo was a consolidated view of crypto work AND a separate cross-asset backtest lab. The user requested it be crypto-only. Removing the non-crypto content makes the repo's purpose unambiguous: it's a crypto signal generator + learning loop, full stop. The cross-asset work continues in private archives (not in this repo).

## [1.0.0] — 2026-06-21 — Archive snapshot

### Added
- **3-month retrospective narrative** in README.md
- **docs/JOURNEY.md** — day-by-day story
- **docs/METHODOLOGY.md** — how the system actually works
- **docs/RESULTS.md** — live signal results analysis (was: backtest progression; rewritten in 1.1.0)
- **docs/PITFALLS.md** — 15 failure modes documented
- **assets/demo.gif** — 11-second terminal demo
- **assets/demo.sh** — source script for regenerating demo.gif

### Consolidated from (private repos, retained for ongoing operational state)
- `learn-crypto` — adaptive weights, prediction registry, scorecard
- `codex-trading` — backtest lab v6 → v11 (removed in 1.1.0)
- `hermes-crypto-skills` — bybit bridge + signal analysis
- `crypto-portfolio-monitor-learning` — portfolio snapshots + sync scripts

### Scrubbed before publishing
- API credentials in `hermes_bybit_bridge.py` and `hermes_crypto_analysis.py` replaced with `os.environ.get()` calls
- `/home/ubuntu/` local filesystem paths replaced with relative paths or `~/`
- `.env`, `.heartbeat*`, internal lock files excluded via `.gitignore`

## [0.11.0] — 2026-06-20 — Demo assets

- Added `assets/demo.gif` (400 KB, 11.5s, 110×35 terminal — updated to 10s in 1.1.0)
- Added `assets/demo.sh` (bash function overrides for reproducible demo)

## [0.10.0] — 2026-06-18 — Pitfalls documented

- Added `docs/PITFALLS.md` with 15 documented failure modes (overhauled in 1.1.0)

## [0.9.0] — 2026-06-14 — Retrospective docs

- Added `docs/JOURNEY.md`, `docs/METHODOLOGY.md`, `docs/RESULTS.md`

## [0.8.0] — 2026-06-08 — Archive docs

- Added `docs/archive/` with 6 historical analysis briefs (4 removed in 1.1.0)

## [0.7.0] — 2026-06-01 — Data expansion

- Scorecard v3.0 (176 predictions verified)
- Market memory + latest snapshot

## [0.6.0] — 2026-05-25 — Filter refinement

- + Yahoo macro overlay (live signal generator, not separate backtest)
- 25.0% live accuracy at this point

## [0.5.0] — 2026-05-17 — Targeted improvements

- Added MACD + regime filter directly to live signal generator

## [0.4.0] — 2026-05-10 — Multi-TF confirmation

- Multi-timeframe confirmation deployed to live signal gen
- 23.5% live accuracy

## [0.3.0] — 2026-04-08 → 2026-04-29 — Filter experiments

- Apr 8: Pure RSI + EMA-trend filter
- Apr 15: + MACD agreement filter (21.0% accuracy)
- Apr 29: + regime filter (BTC > 200 EMA, 22.5% accuracy)

## [0.2.0] — 2026-03-22 → 2026-03-31 — Prediction cycle + learning

- `scripts/prediction/predict_cycle.py` — first signal generator
- `data/predictions/prediction_registry.json` — first 47 predictions
- `data/learning/learning_engine.py` — adaptive weight updater
- `data/learning/learning_weights.json` — initial per-indicator weights

## [0.1.0] — 2026-03-01 → 2026-03-18 — Bootstrap + first scripts

- Initial repo scaffold (.gitignore, LICENSE, README)
- `scripts/analysis/hermes_crypto_analysis.py` — multi-TF indicator pipeline
- `scripts/bridges/hermes_bybit_bridge.py` — Bybit REST wrapper
