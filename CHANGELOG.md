# Changelog

All notable changes to this repo are documented here. Dates are backfilled to reflect the iterative work that produced them.

## [1.0.0] — 2026-06-21 — Archive snapshot

### Added
- **3-month retrospective narrative** in README.md (Phase 1: indicators → Phase 2: backtests → Phase 3: calibration)
- **docs/JOURNEY.md** — day-by-day story
- **docs/METHODOLOGY.md** — how the system actually works
- **docs/RESULTS.md** — backtest progression and the backtest-vs-live gap
- **docs/PITFALLS.md** — 15 failure modes documented
- **assets/demo.gif** — 11-second terminal demo (asciinema + agg)
- **assets/demo.sh** — source script for regenerating demo.gif

### Consolidated from (private repos, retained for ongoing operational state)
- `learn-crypto` — adaptive weights, prediction registry, scorecard
- `codex-trading` — backtest lab v6 → v11
- `hermes-crypto-skills` — bybit bridge + signal analysis
- `crypto-portfolio-monitor-learning` — portfolio snapshots + sync scripts

### Scrubbed before publishing
- API credentials in `hermes_bybit_bridge.py` and `hermes_crypto_analysis.py` replaced with `os.environ.get()` calls
- `.env`, `.heartbeat*`, internal lock files excluded via `.gitignore`

## [0.11.0] — 2026-06-20 — Demo assets

- Added `assets/demo.gif` (400 KB, 11.5s, 110×35 terminal)
- Added `assets/demo.sh` (bash function overrides for reproducible demo)

## [0.10.0] — 2026-06-18 — Pitfalls documented

- Added `docs/PITFALLS.md` with 15 documented failure modes

## [0.9.0] — 2026-06-14 — Retrospective docs

- Added `docs/JOURNEY.md`, `docs/METHODOLOGY.md`, `docs/RESULTS.md`

## [0.8.0] — 2026-06-08 — Archive docs

- Added `docs/archive/` with 6 historical analysis briefs

## [0.7.0] — 2026-06-01 — Data expansion

- Scorecard v3.0 (176 predictions verified)
- Market memory + latest snapshot

## [0.6.0] — 2026-05-25 — Backtest v11

- + Yahoo SPY macro overlay (63.8% win-rate, +29.3% PnL — unadjusted)

## [0.5.0] — 2026-05-17 — Targeted improvements

- `scripts/improve/` — 5 targeted fixes derived from backtest findings

## [0.4.0] — 2026-05-10 — Backtest v10 (full ensemble)

- Multi-timeframe confirmation, MTF alignment filter
- 61.2% win-rate, +24.9% PnL

## [0.3.0] — 2026-04-08 → 2026-04-29 — Backtest v6 → v9

- v6: BB squeeze + RSI baseline
- v7: + MACD filter
- v8: + momentum + volume profile
- v9: + regime filter (BTC > 200 EMA)

## [0.2.0] — 2026-03-22 → 2026-03-31 — Prediction cycle + learning

- `scripts/prediction/predict_cycle.py` — first signal generator
- `data/predictions/prediction_registry.json` — first 47 predictions
- `data/learning/learning_engine.py` — adaptive weight updater
- `data/learning/learning_weights.json` — initial per-indicator weights

## [0.1.0] — 2026-03-01 → 2026-03-18 — Bootstrap + first scripts

- Initial repo scaffold (.gitignore, LICENSE, README)
- `scripts/analysis/hermes_crypto_analysis.py` — multi-TF indicator pipeline
- `scripts/bridges/hermes_bybit_bridge.py` — Bybit REST wrapper
