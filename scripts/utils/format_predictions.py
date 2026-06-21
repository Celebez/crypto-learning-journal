#!/usr/bin/env python3
"""
Format Mode 3 (predict-only cycle) output for Telegram.
Reads from /tmp/pred_result.json (NOT /tmp/scan_result.json).

⚠️ This formatter ONLY works with predict_only_cycle.py or analyze_predict_v3.py output.
It does NOT work with scan_and_predict_combined.py output — different schema.
For Mode 2 (scan_and_predict), format Telegram output manually.

Usage:
  1. Run predict_only_cycle.py or analyze_predict_v3.py > /tmp/pred_result.json
  2. Run: cd ~ cd ~ &&cd ~ && ~/.hermes-venv/bin/python3 /tmp/format_predictions.py

Expected input keys:
  - timestamp
  - calibration: {accuracy, cal_mult, tier, correct, total_verified}
  - portfolio: {total_equity, positions, fear_greed}
  - predictions[]: {symbol, direction, target, invalidation, confidence_calibrated,
                     confidence_raw, prediction_id, rsi_4h, rsi_signal, macd_signal,
                     bb_position, bb_squeeze, ema_alignment, tier, forced}
  - watch_list[] (optional): {symbol, price, rsi_4h, bullish_cal, bearish_cal, reason}
  - avg_confidence
  - forced_count (optional)

No emoji (safe for heredocs). No stdin (file-based, avoids pipe-to-interpreter flag).
"""
import json

with open("/tmp/pred_result.json") as f:
    data = json.load(f)

ts = data["timestamp"][:19].replace("T", " ") + " UTC"
cal = data["calibration"]
portfolio = data["portfolio"]
predictions = data["predictions"]
watch_list = data.get("watch_list", [])
forced = data.get("forced_count", 0)

lines = []
lines.append(f"PREDICTIONS - {ts}")
lines.append("=" * 32)
lines.append("")
lines.append(f"Portfolio: ${portfolio['total_equity']:.2f}")
lines.append(f"Positions: {portfolio['positions']}")
lines.append(f"Fear & Greed: {portfolio['fear_greed']} (Extreme Fear)")
lines.append("")
lines.append(f"Calibration: {cal['accuracy']*100:.1f}% accuracy | x{cal['cal_mult']} | {cal['tier']}")
lines.append(f"Verified: {cal['correct']}/{cal['total_verified']}")
lines.append("")

tier1 = [p for p in predictions if p["tier"] == "TIER1"]
tier2 = [p for p in predictions if p["tier"] == "TIER2"]

if tier1:
    lines.append("TIER 1 (Priority)")
    lines.append("-" * 32)
    for p in tier1:
        forced_tag = " [FORCED]" if p.get("forced") else ""
        lines.append(f"  {p['symbol']} {p['direction']}{forced_tag}")
        lines.append(f"  Target: ${p['target']:,.4f}")
        lines.append(f"  Invalidation: ${p['invalidation']:,.4f}")
        lines.append(f"  Confidence: {p['confidence_calibrated']}% (raw: {p['confidence_raw']}%)")
        lines.append(f"  ID: {p['prediction_id']}")
        lines.append(f"  RSI: {p['rsi_4h']:.1f} ({p['rsi_signal']})")
        lines.append(f"  MACD: {p['macd_signal']}")
        lines.append(f"  BB: {p['bb_position']} (squeeze: {p['bb_squeeze']})")
        lines.append(f"  EMA: {p['ema_alignment']}")
        lines.append("")

if tier2:
    lines.append("TIER 2")
    lines.append("-" * 32)
    for p in tier2:
        forced_tag = " [FORCED]" if p.get("forced") else ""
        lines.append(f"  {p['symbol']} {p['direction']}{forced_tag}")
        lines.append(f"  Target: ${p['target']:,.4f}")
        lines.append(f"  Invalidation: ${p['invalidation']:,.4f}")
        lines.append(f"  Confidence: {p['confidence_calibrated']}% (raw: {p['confidence_raw']}%)")
        lines.append(f"  ID: {p['prediction_id']}")
        lines.append(f"  RSI: {p['rsi_4h']:.1f} ({p['rsi_signal']}) | MACD: {p['macd_signal']} | EMA: {p['ema_alignment']}")
        lines.append("")

if watch_list:
    lines.append("WATCH LIST (Below threshold)")
    lines.append("-" * 32)
    for w in watch_list:
        lines.append(f"  {w['symbol']}: ${w['price']:,.4f} | RSI: {w['rsi_4h']:.1f} | Bull: {w['bullish_cal']} | Bear: {w['bearish_cal']}")
        lines.append(f"  Reason: {w['reason']}")
    lines.append("")

lines.append("=" * 32)
lines.append(f"Total Predictions: {len(predictions)}")
lines.append(f"Avg Confidence: {data['avg_confidence']}%")
if forced:
    lines.append(f"Forced: {forced} (kept learning loop active)")

print("\n".join(lines))
