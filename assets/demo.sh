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
            echo "│   └── snapshots/        # portfolio snapshots"
            echo "├── scripts/"
            echo "│   ├── analysis/         # hermes_crypto_analysis.py"
            echo "│   ├── bridges/          # hermes_bybit_bridge.py"
            echo "│   ├── prediction/       # predict_cycle.py + variants"
            echo "│   └── utils/            # fetch / format / verify"
            echo "├── docs/"
            echo "│   ├── JOURNEY.md        # 3-month retrospective"
            echo "│   ├── METHODOLOGY.md"
            echo "│   ├── RESULTS.md"
            echo "│   └── archive/          # historical briefs"
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
# === 4. What the system does NOT do (deliberate scope limits) ===
echo "▸ What this system deliberately does NOT do"
echo ""
sleep 0.4
echo "  ✗ Position sizing        (no per-trade $ risk calc)"
echo "  ✗ Auto-exit              (open positions need manual close)"
echo "  ✗ Multi-exchange routing (Bybit only)"
echo "  ✗ Forex / XAU / equities (crypto perpetuals only)"
echo "  ✗ Margin/leverage mgmt   (assumes spot-sized positions)"
echo "  ✓ Adaptive calibration   (self-adjusting indicator weights)"
echo "  ✓ Honest scorecard       (down-weights the system when wrong)"
echo "  ✓ NEUTRAL_hold detection (100% acc on 27 trades)"
echo ""
sleep 2.5

# === 5. How to run ===
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
