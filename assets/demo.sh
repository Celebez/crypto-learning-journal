#!/usr/bin/env bash
# demo.sh — recorded with asciinema + agg to produce assets/demo.gif
# Bash function overrides fake external commands so this runs anywhere
# without real API keys or network calls.
#
# To regenerate the GIF:
#   asciinema rec --quiet --overwrite demo.cast -c "bash demo.sh"
#   agg demo.cast ../assets/demo.gif \
#     --cols 110 --rows 35 --font-size 13 --line-height 1.3 \
#     --speed 1.5 --idle-time-limit 2 --no-loop

# ============================================================
# Fake command overrides (take precedence over PATH)
# ============================================================

clj() {
    case "${1:-}" in
        tree)
            echo "."
            echo "├── README.md"
            echo "├── data/"
            echo "│   ├── predictions/      # 176 predictions tracked"
            echo "│   ├── learning/         # adaptive indicator weights"
            echo "│   ├── snapshots/        # portfolio snapshots"
            echo "│   └── backtests/        # v6 → v11 backtest CSVs"
            echo "├── scripts/"
            echo "│   ├── analysis/         # hermes_crypto_analysis.py"
            echo "│   ├── bridges/          # hermes_bybit_bridge.py"
            echo "│   ├── prediction/       # predict_cycle.py + variants"
            echo "│   ├── backtest/         # v6_mt5 → v11_yahoo"
            echo "│   ├── improve/          # confidence / risk / calibration"
            echo "│   └── utils/            # fetch / format / verify"
            echo "├── docs/"
            echo "│   ├── JOURNEY.md        # 3-month retrospective"
            echo "│   ├── METHODOLOGY.md"
            echo "│   ├── RESULTS.md"
            echo "│   └── archive/          # 6 historical briefs"
            echo "└── assets/"
            echo "    └── demo.gif"
            ;;
        scorecard)
            echo "  total_predictions : 176"
            echo "  verified           : 175"
            echo "  correct            :  72   (41.1% of verified)"
            echo "  overall_accuracy   : 0.263"
            echo "  total_pnl_pct      : -36.5%"
            echo "  calibration_tier   : LOW"
            echo "  ─────────────────────────────────────────────"
            echo "  by direction:"
            echo "    BULLISH_buy    : 43 verified ·  6 correct (14.0%)"
            echo "    BEARISH_sell   : 81 verified · 22 correct (27.2%)"
            echo "    NEUTRAL_hold   : 27 verified · 27 correct (100%)  ← best"
            echo "  by confidence:"
            echo "    HIGH (≥0.85)   :  9 verified ·  0 correct   (0.0%)"
            echo "    MEDIUM (0.65-) : 75 verified · 16 correct   (21.3%)"
            echo "    LOW (<0.65)    : 58 verified · 37 correct   (63.8%)  ← sweet spot"
            ;;
        weights)
            echo "  indicator    weight   accuracy   signals"
            echo "  ───────────  ──────   ────────   ───────"
            echo "  rsi              30     90.8%    45,170"
            echo "  macd             10     41.5%    45,174"
            echo "  bb               10     29.7%    45,174"
            echo "  ema_9_21          5     28.1%    45,167"
            echo "  volume           10     68.0%         0"
            echo "  oi               10     65.0%         0"
            echo "  ─────────────────────────────────────────"
            echo "  insight: RSI alone > 90% accurate when weighted alone;"
            echo "           combining all 6 → 26% (over-fit by interaction)"
            ;;
        backtest)
            echo "  version   strategy                        win%   trades   pnl"
            echo "  ───────   ──────────────────────────      ────   ──────   ─────"
            echo "  v6_mt5    BB squeeze + RSI                47.2%   212     +3.8%"
            echo "  v7_mt5    + MACD filter (param sweep)     51.4%   312     +8.1%"
            echo "  v8_strats + momentum + volume profile    54.8%   287    +12.4%"
            echo "  v9_filters  regime filter (BTC trend)    58.3%   264    +18.7%"
            echo "  v10_final  full ensemble                  61.2%   341    +24.9%"
            echo "  v11_yahoo  + yahoo macro overlay          63.8%   298    +29.3%"
            ;;
        *)
            echo "clj: unknown subcommand '$*'" >&2
            return 1
            ;;
    esac
}

# ============================================================
# Demo flow
# ============================================================

clear
echo "╭─────────────────────────────────────────────────────────────╮"
echo "│  crypto-learning-journal  ·  Celebez                         │"
echo "╰─────────────────────────────────────────────────────────────╯"
echo ""
sleep 1.0

echo "▸ Repo structure"
echo ""
clj tree
echo ""
sleep 2.0

echo "▸ Current scorecard (data/learning/scorecard.json)"
echo ""
sleep 0.4
clj scorecard
echo ""
sleep 2.5

echo "▸ Adaptive indicator weights (data/learning/learning_weights.json)"
echo ""
sleep 0.4
clj weights
echo ""
sleep 3.0

echo "▸ Backtest progression (data/backtests/)"
echo ""
sleep 0.4
clj backtest
echo ""
sleep 3.5

echo "▸ Quick start"
echo ""
sleep 0.5
echo "  $ pip install pybit pandas numpy"
echo "  $ export BYBIT_API_KEY='***'"
echo "  $ export BYBIT_API_SECRET='***'"
echo "  $ python3 scripts/utils/verify_and_learn.py \\"
echo "      --registry data/predictions/prediction_registry.json \\"
echo "      --weights  data/learning/learning_weights.json \\"
echo "      --dry-run"
echo ""
sleep 2.5

echo "▸ Demo complete — see docs/JOURNEY.md for the full retrospective"
echo ""
sleep 1.5
