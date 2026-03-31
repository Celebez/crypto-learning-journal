#!/usr/bin/env python3
"""
Verify & Learn Script - Crypto Portfolio Monitor (Mode 4)
Fetches current prices for PENDING/PREDICTED predictions, classifies outcomes,
analyzes indicator correctness, updates learning weights.

Usage:
  cd /home/ubuntu && /home/ubuntu/.hermes-venv/bin/python3 /tmp/verify_and_learn.py

Output: JSON to stdout with verification results and updated weights.

Handles both flat and nested indicator formats in the prediction registry.

CRITICAL FIX (v3.34): Added minimum age check - predictions must be at least
2 hours old before verification to prevent the "immediate verification bug"
where predictions generated in the same cycle are incorrectly marked as SUCCESS.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/ubuntu")

from hermes_bybit_bridge import get_price

# Paths
registry_path = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/prediction_registry.json"
)
learning_path = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/learning_weights.json"
)

# Load files
with open(registry_path, "r") as f:
    registry = json.load(f)

with open(learning_path, "r") as f:
    learning = json.load(f)

# ============================================================
# v3.0 AUDIT: Reject non-compliant predictions per SKILL.md rules
# ============================================================
# Rules:
#  R1: direction != NONE (must be BULLISH, BEARISH, or NEUTRAL with conf >= 60)
#  R2: confidence cap at 50 unless historical accuracy > 60% (caller enforces)
#  R5: all required fields present
AUDIT_REJECTED = 0
AUDIT_CAPPED = 0
for p in registry.get("predictions", []):
    # Only audit non-verified, non-rejected entries
    if p.get("status") in ("VERIFIED", "REJECTED", "EXPIRED"):
        continue
    direction = p.get("direction")
    confidence = p.get("confidence", 0)
    pred_id = p.get("prediction_id", "unknown")
    # R1: NONE direction = reject
    if not direction or direction == "NONE":
        p["status"] = "REJECTED"
        p["rejection_reason"] = "R1_violation: direction is NONE or missing"
        AUDIT_REJECTED += 1
        continue
    # R1: NEUTRAL with low confidence = reject
    if direction == "NEUTRAL" and confidence < 60:
        p["status"] = "REJECTED"
        p["rejection_reason"] = f"R1_violation: NEUTRAL with confidence {confidence} < 60"
        AUDIT_REJECTED += 1
        continue
    # R2: cap confidence at 50 (do not reject, just cap)
    if confidence > 50:
        p["confidence_original"] = confidence
        p["confidence"] = 50
        p["confidence_capped"] = True
        AUDIT_CAPPED += 1
    # R5: required fields
    required = ["prediction_id", "symbol", "direction", "target_price", "invalidation_price",
                "confidence", "timeframe"]
    missing = [f for f in required if not p.get(f)]
    if missing:
        p["status"] = "REJECTED"
        p["rejection_reason"] = f"R5_violation: missing fields {missing}"
        AUDIT_REJECTED += 1
        continue

if AUDIT_REJECTED > 0 or AUDIT_CAPPED > 0:
    print(f"[AUDIT v3.0] Rejected: {AUDIT_REJECTED}, Confidence capped: {AUDIT_CAPPED}")
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2, default=str)

# ============================================================
pending = [p for p in registry["predictions"] if p.get("status") in ("PENDING", "PREDICTED")]

now = datetime.now(timezone.utc)

# CRITICAL FIX: Minimum age check - don't verify predictions younger than 2 hours
# This prevents the "immediate verification bug" where predictions generated in the
# same cycle are verified as SUCCESS even though target hasn't been hit
MIN_VERIFY_AGE_HOURS = 2
filtered_pending = []
for p in pending:
    try:
        pred_time = datetime.fromisoformat(p.get("timestamp", ""))
        if pred_time.tzinfo is None:
            pred_time = pred_time.replace(tzinfo=timezone.utc)
        age_hours = (now - pred_time).total_seconds() / 3600
        if age_hours >= MIN_VERIFY_AGE_HOURS:
            filtered_pending.append(p)
        # else: skip - too young to verify
    except:
        # If timestamp parsing fails, include it for verification
        filtered_pending.append(p)

pending = filtered_pending

if not pending:
    # No new predictions to verify, but still recalculate accuracy and clean up
    # Recalculate from ALL verified predictions in registry
    IND_KEY_MAP = {"rsi": "rsi", "macd": "macd", "bb": "bb", "ema": "ema_9_21"}
    indicator_weights = learning.get("indicator_weights", {})
    
    # Gather all verified predictions for indicator accuracy recalculation
    all_verified = [p for p in registry["predictions"]
                    if (p.get("verification") or {}).get("result") in
                    ("SUCCESS", "PARTIAL_SUCCESS", "FAILURE")]
    
    for p in all_verified:
        ia = (p.get("verification") or {}).get("indicator_analysis", {})
        for ind, result in ia.items():
            weight_key = IND_KEY_MAP.get(ind, ind)
            if weight_key not in indicator_weights:
                continue
            if result == "CORRECT":
                indicator_weights[weight_key]["correct_signals"] = indicator_weights[weight_key].get("correct_signals", 0) + 1
                indicator_weights[weight_key]["total_signals"] = indicator_weights[weight_key].get("total_signals", 0) + 1
            elif result in ("WRONG", "WEAK"):
                indicator_weights[weight_key]["total_signals"] = indicator_weights[weight_key].get("total_signals", 0) + 1
            total = indicator_weights[weight_key].get("total_signals", 1)
            correct = indicator_weights[weight_key].get("correct_signals", 0)
            if total > 0:
                indicator_weights[weight_key]["accuracy"] = correct / total
            indicator_weights[weight_key]["last_adjusted"] = now.isoformat()
    
    # Recalculate accuracy from verified predictions only (exclude EXPIRED)
    verified_count = len(all_verified)
    correct_count = sum(1 for p in all_verified
                        if (p.get("verification") or {}).get("result") in
                        ("SUCCESS", "PARTIAL_SUCCESS"))
    learning["accuracy_rate"] = correct_count / verified_count if verified_count > 0 else 0.5
    learning["verified_predictions"] = verified_count
    learning["correct_predictions"] = correct_count
    
    acc = learning["accuracy_rate"]
    if acc > 0.80:
        learning["calibration_multiplier"] = 1.0
        learning["calibration_tier"] = "HIGH"
    elif acc > 0.60:
        learning["calibration_multiplier"] = 0.85
        learning["calibration_tier"] = "MEDIUM"
    elif acc > 0.40:
        learning["calibration_multiplier"] = 0.7
        learning["calibration_tier"] = "LOW"
    else:
        learning["calibration_multiplier"] = 0.5
        learning["calibration_tier"] = "UNRELIABLE"
    
    # Clean EXPIRED entries older than 7 days (keep rolling buffer of 50)
    cutoff = now - timedelta(days=7)
    non_expired = [p for p in registry["predictions"] if p.get("status") != "EXPIRED"]
    expired = [p for p in registry["predictions"] if p.get("status") == "EXPIRED"]
    expired.sort(key=lambda p: p.get("timestamp", ""), reverse=True)
    fresh_expired = []
    for p in expired[:50]:
        try:
            ts = datetime.fromisoformat(p.get("timestamp", "2000-01-01T00:00:00+00:00"))
            if ts > cutoff:
                fresh_expired.append(p)
        except:
            fresh_expired.append(p)
    registry["predictions"] = non_expired + fresh_expired
    
    learning["last_updated"] = now.isoformat()
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)
    with open(learning_path, "w") as f:
        json.dump(learning, f, indent=2)
    
    result = {
        "status": "RECALCULATED",
        "message": "No pending predictions. Recalculated accuracy and cleaned EXPIRED.",
        "timestamp": now.isoformat(),
        "verified_count": verified_count,
        "correct_count": correct_count,
        "accuracy_rate": learning["accuracy_rate"],
        "calibration_multiplier": learning["calibration_multiplier"],
        "calibration_tier": learning["calibration_tier"],
        "expired_cleaned": len(expired) - len(fresh_expired),
        "registry_size": len(registry["predictions"])
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)

# Get current prices for all symbols
symbols = list(set(p["symbol"] for p in pending))
current_prices = {}
for sym in symbols:
    try:
        data = get_price(sym)
        current_prices[sym] = float(data.get("last", 0))
    except Exception as e:
        current_prices[sym] = 0
        print(f"Warning: Failed to get price for {sym}: {e}", file=sys.stderr)

# Verify each prediction
verification_results = []
now = datetime.now(timezone.utc)

for pred in pending:
    sym = pred["symbol"]
    current_price = current_prices.get(sym, 0)
    
    # Get prediction details (handle both flat and nested format)
    if "target_price" in pred:
        target = pred["target_price"]
        invalidation = pred["invalidation_price"]
        direction = pred["direction"]
        pred_price = pred.get("market_context", {}).get("price", 0)
        indicators = pred.get("indicators", {})
        patterns = pred.get("patterns_detected", [])
    elif "prediction" in pred:
        target = pred["prediction"]["target_price"]
        invalidation = pred["prediction"]["invalidation_price"]
        direction = pred["prediction"]["direction"]
        pred_price = pred.get("market_context", {}).get("price", 0)
        indicators = pred.get("indicators_used", {})
        patterns = pred.get("patterns_detected", [])
    else:
        continue
    
    # Determine outcome
    if current_price <= 0:
        outcome = "INVALIDATED"
        score = None
        reason = "Could not fetch current price"
    elif direction == "NEUTRAL":
        if current_price <= invalidation:
            outcome = "FAILURE"
            score = 0
            reason = f"Price {current_price} hit invalidation {invalidation}"
        elif current_price >= target:
            outcome = "SUCCESS"
            score = 100
            reason = f"Price {current_price} hit target {target}"
        else:
            outcome = "PARTIAL_SUCCESS"
            score = 50
            reason = f"Price {current_price} stayed in range"
    elif direction == "BULLISH":
        if current_price >= target:
            outcome = "SUCCESS"
            score = 100
            reason = f"Price {current_price} hit target {target}"
        elif current_price <= invalidation:
            outcome = "FAILURE"
            score = 0
            reason = f"Price {current_price} hit invalidation {invalidation}"
        elif current_price > pred_price:
            outcome = "PARTIAL_SUCCESS"
            score = 50
            reason = f"Price moved bullish {pred_price} -> {current_price} but target not hit"
        else:
            outcome = "FAILURE"
            score = 0
            reason = f"Price moved bearish {pred_price} -> {current_price}"
    elif direction == "BEARISH":
        if current_price <= target:
            outcome = "SUCCESS"
            score = 100
            reason = f"Price {current_price} hit target {target}"
        elif current_price >= invalidation:
            outcome = "FAILURE"
            score = 0
            reason = f"Price {current_price} hit invalidation {invalidation}"
        elif current_price < pred_price:
            outcome = "PARTIAL_SUCCESS"
            score = 50
            reason = f"Price moved bearish {pred_price} -> {current_price} but target not hit"
        else:
            outcome = "FAILURE"
            score = 0
            reason = f"Price moved bullish {pred_price} -> {current_price}"
    
    # Analyze indicator correctness (handles nested dict format)
    indicator_analysis = {}
    
    # RSI analysis
    rsi_data = indicators.get("rsi", {})
    if isinstance(rsi_data, dict):
        rsi_val = rsi_data.get("value", 50)
    else:
        rsi_val = float(rsi_data) if rsi_data else 50
    
    if direction == "BULLISH":
        indicator_analysis["rsi"] = "CORRECT" if rsi_val < 70 else "WEAK" if rsi_val < 80 else "WRONG"
    elif direction == "BEARISH":
        indicator_analysis["rsi"] = "CORRECT" if rsi_val > 30 else "WEAK" if rsi_val > 20 else "WRONG"
    else:
        indicator_analysis["rsi"] = "CORRECT" if 30 <= rsi_val <= 70 else "WRONG"
    
    # MACD analysis
    macd_data = indicators.get("macd", {})
    if isinstance(macd_data, dict):
        macd_hist = macd_data.get("hist", 0)
        macd_signal = macd_data.get("signal", "")
    else:
        macd_hist = 0
        macd_signal = str(macd_data)
    
    if direction == "BULLISH":
        indicator_analysis["macd"] = "CORRECT" if macd_hist > 0 or "BULLISH" in str(macd_signal).upper() else "WRONG"
    elif direction == "BEARISH":
        indicator_analysis["macd"] = "CORRECT" if macd_hist < 0 or "BEARISH" in str(macd_signal).upper() else "WRONG"
    else:
        indicator_analysis["macd"] = "CORRECT" if abs(macd_hist) < 50 else "WRONG"
    
    # BB position analysis
    bb_data = indicators.get("bb", {})
    if isinstance(bb_data, dict):
        bb_pos = bb_data.get("position", "MIDDLE")
    else:
        bb_pos = str(bb_data) if bb_data else "MIDDLE"
    
    if direction == "BULLISH":
        indicator_analysis["bb"] = "CORRECT" if bb_pos in ("UPPER_HALF", "ABOVE_UPPER") else "WRONG"
    elif direction == "BEARISH":
        indicator_analysis["bb"] = "CORRECT" if bb_pos in ("LOWER_HALF", "BELOW_LOWER") else "WRONG"
    else:
        indicator_analysis["bb"] = "CORRECT" if bb_pos == "MIDDLE" else "WRONG"
    
    # EMA analysis (uses .cross and .alignment keys)
    ema_data = indicators.get("ema", {})
    if isinstance(ema_data, dict):
        ema_alignment = ema_data.get("alignment", "")
        ema_cross = ema_data.get("cross", "")
    else:
        ema_alignment = str(ema_data)
        ema_cross = ""
    
    if direction == "BULLISH":
        indicator_analysis["ema"] = "CORRECT" if ema_alignment in ("BULL_ALIGNED", "BULL") or ema_cross == "BULLISH" else "WRONG"
    elif direction == "BEARISH":
        indicator_analysis["ema"] = "CORRECT" if ema_alignment in ("BEAR_ALIGNED", "BEAR") or ema_cross == "BEARISH" else "WRONG"
    else:
        indicator_analysis["ema"] = "CORRECT" if ema_alignment in ("MIXED",) else "WRONG"
    
    verification_results.append({
        "prediction_id": pred["prediction_id"],
        "symbol": sym,
        "direction": direction,
        "pred_price": pred_price,
        "current_price": current_price,
        "target": target,
        "invalidation": invalidation,
        "outcome": outcome,
        "score": score,
        "reason": reason,
        "indicator_analysis": indicator_analysis,
        "patterns": patterns,
        "confidence": pred.get("confidence", 0)
    })

# Update prediction statuses in registry
for vr in verification_results:
    for pred in registry["predictions"]:
        if pred["prediction_id"] == vr["prediction_id"]:
            # Compute price_change_pct (the % move from prediction to actual)
            pred_price = pred.get("market_context", {}).get("price", 0)
            actual_price = vr["current_price"]
            if pred_price > 0 and actual_price > 0:
                price_change_pct = round((actual_price - pred_price) / pred_price * 100, 4)
            else:
                price_change_pct = None
            pred["status"] = "VERIFIED"
            pred["verification"] = {
                "result": vr["outcome"],
                "verified_at": now.isoformat(),
                "actual_price": vr["current_price"],
                "price_change_pct": price_change_pct,
                "score": vr["score"],
                "reason": vr["reason"],
                "indicator_analysis": vr["indicator_analysis"]
            }
            break

# Update learning weights
indicator_weights = learning.get("indicator_weights", {})
IND_KEY_MAP = {"rsi": "rsi", "macd": "macd", "bb": "bb", "ema": "ema_9_21"}
for vr in verification_results:
    for ind, result in vr["indicator_analysis"].items():
        weight_key = IND_KEY_MAP.get(ind, ind)
        if weight_key in indicator_weights:
            if result == "CORRECT":
                indicator_weights[weight_key]["correct_signals"] = indicator_weights[weight_key].get("correct_signals", 0) + 1
                indicator_weights[weight_key]["total_signals"] = indicator_weights[weight_key].get("total_signals", 0) + 1
                new_weight = min(30, indicator_weights[weight_key]["weight"] + 5)
                indicator_weights[weight_key]["weight"] = new_weight
            elif result == "WRONG":
                indicator_weights[weight_key]["total_signals"] = indicator_weights[weight_key].get("total_signals", 0) + 1
                new_weight = max(5, indicator_weights[weight_key]["weight"] - 10)
                indicator_weights[weight_key]["weight"] = new_weight
            elif result == "WEAK":
                indicator_weights[weight_key]["total_signals"] = indicator_weights[weight_key].get("total_signals", 0) + 1
                new_weight = max(5, indicator_weights[weight_key]["weight"] - 3)
                indicator_weights[weight_key]["weight"] = new_weight
            
            total = indicator_weights[weight_key].get("total_signals", 1)
            correct = indicator_weights[weight_key].get("correct_signals", 0)
            if total > 0:
                indicator_weights[weight_key]["accuracy"] = correct / total
            indicator_weights[weight_key]["last_adjusted"] = now.isoformat()

# Update pattern weights
pattern_weights = learning.get("pattern_weights", {})
for vr in verification_results:
    for pat in vr.get("patterns", []):
        pat_lower = pat.lower()
        if pat_lower in pattern_weights:
            if vr["outcome"] == "SUCCESS":
                pattern_weights[pat_lower]["successful_detections"] = pattern_weights[pat_lower].get("successful_detections", 0) + 1
                pattern_weights[pat_lower]["weight"] = min(30, pattern_weights[pat_lower]["weight"] + 3)
            elif vr["outcome"] == "FAILURE":
                pattern_weights[pat_lower]["weight"] = max(5, pattern_weights[pat_lower]["weight"] - 5)
            pattern_weights[pat_lower]["total_detections"] = pattern_weights[pat_lower].get("total_detections", 0) + 1
            total_det = pattern_weights[pat_lower].get("total_detections", 1)
            success_det = pattern_weights[pat_lower].get("successful_detections", 0)
            if total_det > 0:
                pattern_weights[pat_lower]["reliability"] = success_det / total_det
            pattern_weights[pat_lower]["last_adjusted"] = now.isoformat()

# Update learning stats
learning["indicator_weights"] = indicator_weights
learning["pattern_weights"] = pattern_weights

success_count = sum(1 for vr in verification_results if vr["outcome"] == "SUCCESS")
partial_count = sum(1 for vr in verification_results if vr["outcome"] == "PARTIAL_SUCCESS")
failure_count = sum(1 for vr in verification_results if vr["outcome"] == "FAILURE")

learning["total_predictions"] = learning.get("total_predictions", 0) + len(verification_results)
learning["verified_predictions"] = learning.get("verified_predictions", 0) + len(verification_results)
learning["correct_predictions"] = learning.get("correct_predictions", 0) + success_count
# CORRECT — only count predictions with actual outcomes (exclude EXPIRED)
# Use (p.get("verification") or {}) because verification can be None/null
verified_count = sum(1 for p in registry["predictions"]
                     if (p.get("verification") or {}).get("result") in
                     ("SUCCESS", "PARTIAL_SUCCESS", "FAILURE"))
correct_count = sum(1 for p in registry["predictions"]
                    if (p.get("verification") or {}).get("result") in
                    ("SUCCESS", "PARTIAL_SUCCESS"))
learning["accuracy_rate"] = correct_count / verified_count if verified_count > 0 else 0.5

acc = learning["accuracy_rate"]
if acc > 0.80:
    learning["calibration_multiplier"] = 1.0
    learning["calibration_tier"] = "HIGH"
elif acc > 0.60:
    learning["calibration_multiplier"] = 0.85
    learning["calibration_tier"] = "MEDIUM"
elif acc > 0.40:
    learning["calibration_multiplier"] = 0.7
    learning["calibration_tier"] = "LOW"
else:
    learning["calibration_multiplier"] = 0.5
    learning["calibration_tier"] = "UNRELIABLE"

learning["last_updated"] = now.isoformat()

# Save updated files
with open(registry_path, "w") as f:
    json.dump(registry, f, indent=2)

with open(learning_path, "w") as f:
    json.dump(learning, f, indent=2)

# Generate output
output = {
    "timestamp": now.isoformat(),
    "predictions_verified": len(verification_results),
    "success_count": success_count,
    "partial_count": partial_count,
    "failure_count": failure_count,
    "verifications": verification_results,
    "indicator_weights": {k: {"weight": v["weight"], "accuracy": v.get("accuracy", 0)} for k, v in indicator_weights.items()},
    "learning_stats": {
        "total_predictions": learning["total_predictions"],
        "correct_predictions": learning["correct_predictions"],
        "accuracy_rate": learning["accuracy_rate"],
        "calibration_tier": learning["calibration_tier"]
    }
}

print(json.dumps(output, indent=2))
