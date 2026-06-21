#!/usr/bin/env python3
"""ANALYZE & PREDICT — 1-hour prediction cycle with verification and learning.

Combines prediction generation, old prediction verification, accuracy recalculation
from verified entries (excluding EXPIRED), registry pruning, and learning weight updates.

Usage:
  cd ~ cd ~ &&cd ~ && ~/.hermes-venv/bin/python3 /tmp/analyze_predict_cycle.py 2>/dev/null

Output: JSON to stdout with predictions, verification results, and learning status.

This script loads from latest_snapshot.json (no API calls). Snapshot must be < 30 min old.
Sync to Redis + Supabase should be done separately after running this script.
"""
import json
import os
import hashlib
from datetime import datetime, timezone, timedelta

SNAPSHOT_PATH = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/latest_snapshot.json"
)
REGISTRY_PATH = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/prediction_registry.json"
)
WEIGHTS_PATH = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/learning_weights.json"
)

TRACKED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]
TIER1 = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

# --- Confidence modifiers from references/confidence_calculation.md ---
BASE_SCORE = 50

def classify_macd(macd_hist, macd_line=None, macd_signal_line=None):
    """Classify MACD signal properly (do NOT label BULLISH_CROSS just because hist > 0)."""
    if macd_hist is None:
        return "NEUTRAL", macd_hist or 0
    h = float(macd_hist)
    if h > 0:
        if macd_line is not None and macd_signal_line is not None:
            if float(macd_line) < float(macd_signal_line):
                return "BULLISH_RECOVERY", h
        return "BULLISH", h
    elif h < 0:
        if macd_line is not None and macd_signal_line is not None:
            if float(macd_line) > float(macd_signal_line):
                return "BEARISH_RECOVERY", h
        return "BEARISH", h
    return "NEUTRAL", 0

def score_direction(data, direction, cal_mult):
    """Score a single direction (BULLISH or BEARISH) for an asset.
    
    Uses modifiers from references/confidence_calculation.md:
    - Squeeze: multi-TF +12, 4H +8, 1H +6
    - MACD: BULLISH/BEARISH +8, RECOVERY +4
    - RSI: 4H >55/<45 ±3, 1H >55/<45 ±2
    - EMA: 4H bullish +8 / bearish -10, 1H ±4
    - Price position: above/below BB mid ±3
    """
    ind = data.get("indicators_4h", {})
    ind_1h = data.get("indicators_1h", {})
    price = float(data.get("price", 0))
    
    rsi_4h = float(ind.get("rsi", 50))
    bb_width = float(ind.get("bb_width", 0.1))
    bb_squeeze = bool(ind.get("bb_squeeze", False))
    macd_hist = float(ind.get("macd_hist", 0))
    ema9 = float(ind.get("ema9", price))
    ema21 = float(ind.get("ema21", price))
    ema_alignment = ind.get("ema_alignment", "MIXED")
    
    rsi_1h = float(ind_1h.get("rsi", 50))
    bb_width_1h = float(ind_1h.get("bb_width", 0.1))
    bb_squeeze_1h = bool(ind_1h.get("bb_squeeze", False))
    
    score = BASE_SCORE
    
    # Squeeze modifiers
    multi_tf_squeeze = bb_squeeze and bb_squeeze_1h
    if multi_tf_squeeze:
        score += 12
    elif bb_squeeze:
        score += 8
    elif bb_squeeze_1h:
        score += 6
    
    # MACD modifiers
    macd_class, _ = classify_macd(macd_hist)
    if direction == "BULLISH":
        if macd_class in ("BULLISH", "BULLISH_CROSS"):
            score += 8
        elif macd_class == "BULLISH_RECOVERY":
            score += 4
        elif macd_class in ("BEARISH", "BEARISH_CROSS"):
            score -= 8
        elif macd_class == "BEARISH_RECOVERY":
            score -= 4
    else:  # BEARISH
        if macd_class in ("BEARISH", "BEARISH_CROSS"):
            score += 8
        elif macd_class == "BEARISH_RECOVERY":
            score += 4
        elif macd_class in ("BULLISH", "BULLISH_CROSS"):
            score -= 8
        elif macd_class == "BULLISH_RECOVERY":
            score -= 4
    
    # RSI modifiers
    if direction == "BULLISH":
        if rsi_4h < 45:
            score += 3
        elif rsi_4h > 55:
            score -= 3
        if rsi_1h < 45:
            score += 2
        elif rsi_1h > 55:
            score -= 2
    else:  # BEARISH
        if rsi_4h > 55:
            score += 3
        elif rsi_4h < 45:
            score -= 3
        if rsi_1h > 55:
            score += 2
        elif rsi_1h < 45:
            score -= 2
    
    # EMA alignment modifiers
    bb_mid = (ema9 + ema21) / 2
    if direction == "BULLISH":
        if ema_alignment in ("BULL_ALIGNED", "BULLISH_ALIGNED"):
            score += 8
        elif ema_alignment in ("BEAR_ALIGNED", "BEARISH_ALIGNED", "FULL_BEAR"):
            score -= 10
        if ema9 > ema21:
            score += 4
        else:
            score -= 4
    else:  # BEARISH
        if ema_alignment in ("BEAR_ALIGNED", "BEARISH_ALIGNED", "FULL_BEAR"):
            score += 5
        elif ema_alignment in ("BULL_ALIGNED", "BULLISH_ALIGNED"):
            score -= 10
        if ema9 < ema21:
            score += 4
        else:
            score -= 4
    
    # Price position
    if direction == "BULLISH":
        if price > bb_mid:
            score += 3
        else:
            score -= 3
    else:  # BEARISH
        if price < bb_mid:
            score += 3
        else:
            score -= 3
    
    # Clamp
    score = max(20, min(100, score))
    
    # Calibrate
    calibrated = int(score * cal_mult)
    calibrated = max(20, min(100, calibrated))
    
    return score, calibrated

def load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return default or {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def main():
    now = datetime.now(timezone.utc)
    
    # Load data
    snapshot = load_json(SNAPSHOT_PATH)
    registry = load_json(REGISTRY_PATH, {"predictions": [], "version": "1.0"})
    weights = load_json(WEIGHTS_PATH, {})
    
    if not snapshot or "assets" not in snapshot:
        print(json.dumps({"error": "No valid snapshot found"}))
        return
    
    snap_time = datetime.fromisoformat(snapshot["timestamp"].replace("Z", "+00:00"))
    snap_age_min = (now - snap_time).total_seconds() / 60
    
    # === STEP 1: Recalculate accuracy from verified predictions (exclude EXPIRED) ===
    preds = registry.get("predictions", [])
    verified = [p for p in preds if (p.get("verification") or {}).get("result") in 
                ("SUCCESS", "PARTIAL_SUCCESS", "FAILURE")]
    correct = [p for p in preds if (p.get("verification") or {}).get("result") in 
               ("SUCCESS", "PARTIAL_SUCCESS")]
    
    if verified:
        new_accuracy = len(correct) / len(verified)
    else:
        new_accuracy = 0.5
    
    # Determine calibration tier
    if new_accuracy > 0.8:
        cal_mult = 1.0
        cal_tier = "HIGH"
    elif new_accuracy > 0.6:
        cal_mult = 0.85
        cal_tier = "MEDIUM"
    elif new_accuracy > 0.4:
        cal_mult = 0.7
        cal_tier = "LOW"
    else:
        cal_mult = 0.5
        cal_tier = "UNRELIABLE"
    
    # === STEP 2: Verify old PREDICTED predictions ===
    verified_count = 0
    for pred in preds:
        if pred.get("status") != "PREDICTED":
            continue
        sym = pred.get("symbol", "")
        if not sym:
            # Fallback: extract from prediction_id
            pid = pred.get("prediction_id", "")
            if pid.startswith("PRED-"):
                parts = pid.split("-")
                if len(parts) >= 3:
                    sym = parts[1]
        if not sym:
            continue
        snap_asset = snapshot.get("assets", {}).get(sym)
        if not snap_asset:
            continue
        
        current_price = float(snap_asset.get("price", 0))
        if current_price <= 0:
            continue
        
        # Get target/invalidation (handle both formats)
        if "prediction" in pred and isinstance(pred["prediction"], dict):
            p_data = pred["prediction"]
        else:
            p_data = pred
        
        target = float(p_data.get("target_price", 0))
        invalidation = float(p_data.get("invalidation_price", 0))
        direction = pred.get("direction", p_data.get("direction", ""))
        
        if target <= 0 or invalidation <= 0:
            continue
        
        pred_time = datetime.fromisoformat(pred["timestamp"].replace("Z", "+00:00"))
        pred_age_hours = (now - pred_time).total_seconds() / 3600
        
        result = None
        score = 0
        reason = ""
        
        if direction == "BEARISH":
            if current_price <= target:
                result = "SUCCESS"
                score = 100
                reason = f"Price {current_price} hit target {target}"
            elif current_price >= invalidation:
                result = "FAILURE"
                score = 0
                reason = f"Price {current_price} hit invalidation {invalidation}"
            elif pred_age_hours > 24:
                orig_price = float(pred.get("market_context", {}).get("price", current_price))
                if current_price < orig_price:
                    result = "PARTIAL_SUCCESS"
                    score = 50
                    reason = f"Price moved down but didn't hit target ({current_price})"
                else:
                    result = "FAILURE"
                    score = 0
                    reason = f"Price moved up after 24h ({current_price})"
        elif direction == "BULLISH":
            if current_price >= target:
                result = "SUCCESS"
                score = 100
                reason = f"Price {current_price} hit target {target}"
            elif current_price <= invalidation:
                result = "FAILURE"
                score = 0
                reason = f"Price {current_price} hit invalidation {invalidation}"
            elif pred_age_hours > 24:
                orig_price = float(pred.get("market_context", {}).get("price", current_price))
                if current_price > orig_price:
                    result = "PARTIAL_SUCCESS"
                    score = 50
                    reason = f"Price moved up but didn't hit target ({current_price})"
                else:
                    result = "FAILURE"
                    score = 0
                    reason = f"Price moved down after 24h ({current_price})"
        
        if result:
            pred["status"] = "VERIFIED"
            pred["verified_at"] = now.isoformat()
            pred["actual_price"] = current_price
            pred["verification"] = {
                "result": result,
                "verified_at": now.isoformat(),
                "actual_price": current_price,
                "score": score,
                "reason": reason
            }
            verified_count += 1
    
    # === STEP 3: Expire old PREDICTED entries ===
    for pred in preds:
        if pred.get("status") == "PREDICTED":
            pred["status"] = "EXPIRED"
    
    # === STEP 4: Clean EXPIRED entries older than 7 days ===
    cutoff = now - timedelta(days=7)
    clean_count = 0
    new_preds = []
    for p in preds:
        if p.get("status") == "EXPIRED":
            try:
                ts = datetime.fromisoformat(p.get("timestamp", "2000-01-01T00:00:00+00:00").replace("Z", "+00:00"))
                if ts < cutoff:
                    clean_count += 1
                    continue
            except:
                pass
        new_preds.append(p)
    preds = new_preds
    
    # Keep max 50 EXPIRED as rolling buffer
    expired_preds = [p for p in preds if p.get("status") == "EXPIRED"]
    if len(expired_preds) > 50:
        expired_preds.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        to_remove = set(id(p) for p in expired_preds[50:])
        preds = [p for p in preds if id(p) not in to_remove]
    
    # === STEP 5: Generate new predictions (bidirectional scoring) ===
    candidates = []
    for sym in TRACKED:
        data = snapshot["assets"].get(sym)
        if not data:
            continue
        
        # Score both directions
        bull_raw, bull_cal = score_direction(data, "BULLISH", cal_mult)
        bear_raw, bear_cal = score_direction(data, "BEARISH", cal_mult)
        
        # Pick stronger direction
        if bull_cal > bear_cal:
            direction = "BULLISH"
            signal = "BUY"
            raw = bull_raw
            cal = bull_cal
        else:
            direction = "BEARISH"
            signal = "SELL"
            raw = bear_raw
            cal = bear_cal
        
        candidates.append({
            "symbol": sym,
            "direction": direction,
            "signal": signal,
            "raw": raw,
            "cal": cal,
            "bull_raw": bull_raw,
            "bull_cal": bull_cal,
            "bear_raw": bear_raw,
            "bear_cal": bear_cal,
            "data": data,
            "tier1": sym in TIER1,
        })
    
    # Sort by tier (1 first) then calibrated score
    candidates.sort(key=lambda x: (-int(x["tier1"]), -x["cal"]))
    
    # Dynamic threshold (death spiral protection)
    prediction_threshold = 50 if cal_mult >= 0.6 else int(cal_mult * 80)
    
    natural_preds = [c for c in candidates if c["cal"] > prediction_threshold]
    skipped = [c for c in candidates if c["cal"] <= prediction_threshold]
    
    # Force top-2 if zero natural predictions
    forced = []
    if len(natural_preds) == 0 and len(candidates) >= 2:
        candidates_sorted = sorted(candidates, key=lambda x: -x["cal"])
        forced = candidates_sorted[:2]
        for f in forced:
            f["forced"] = True
    
    # Generate prediction entries
    new_predictions = []
    for c in natural_preds + forced:
        sym = c["symbol"]
        data = c["data"]
        direction = c["direction"]
        signal = c["signal"]
        ind = data.get("indicators_4h", {})
        ind_1h = data.get("indicators_1h", {})
        price = float(data.get("price", 0))
        
        # Support/resistance from BB and EMA
        ema9 = float(ind.get("ema9", price))
        ema21 = float(ind.get("ema21", price))
        bb_mid = (ema9 + ema21) / 2
        bb_width = float(ind.get("bb_width", 0.03))
        
        if direction == "BEARISH":
            target = round(bb_mid - price * bb_width * 0.5, 4)
            invalidation = round(ema21, 4)
            resistance = sorted([round(ema21, 4), round(ema21 * 1.02, 4)])
            support = sorted([round(bb_mid, 4), round(bb_mid * 0.98, 4)])
        else:
            target = round(ema21, 4)
            invalidation = round(bb_mid - price * bb_width * 0.5, 4)
            resistance = sorted([round(ema21, 4), round(ema21 * 1.02, 4)])
            support = sorted([round(bb_mid, 4), round(bb_mid * 0.98, 4)])
        
        # Determine tier
        if c["cal"] >= 70:
            tier = "HIGH"
        elif c["cal"] >= 55:
            tier = "MEDIUM"
        elif c["cal"] >= 40:
            tier = "LOW"
        else:
            tier = "UNRELIABLE"
        
        # Generate prediction ID
        ts_str = now.strftime("%Y%m%d%H%M%S")
        hash_input = f"{sym}{ts_str}{price}"
        hash_val = hashlib.md5(hash_input.encode()).hexdigest()[:4].upper()
        pred_id = f"PRED-{sym}-{ts_str}-{hash_val}"
        
        # MACD classification
        macd_hist = float(ind.get("macd_hist", 0))
        macd_class, _ = classify_macd(macd_hist)
        
        # BB position
        if price > ema21:
            bb_pos = "ABOVE_UPPER"
        elif price > bb_mid:
            bb_pos = "UPPER_HALF"
        elif price > ema9:
            bb_pos = "LOWER_HALF"
        else:
            bb_pos = "BELOW_LOWER"
        
        # RSI signal
        rsi_val = float(ind.get("rsi", 50))
        if rsi_val > 70:
            rsi_sig = "OVERBOUGHT"
        elif rsi_val > 55:
            rsi_sig = "BULLISH"
        elif rsi_val < 30:
            rsi_sig = "OVERSOLD"
        elif rsi_val < 45:
            rsi_sig = "BEARISH"
        else:
            rsi_sig = "NEUTRAL"
        
        patterns = [p.get("name", "") for p in data.get("patterns", [])]
        
        pred_entry = {
            "prediction_id": pred_id,
            "symbol": sym,  # MUST include — see pitfall pitfalls-v3.30.md #2
            "timestamp": now.isoformat(),
            "model_used": "hermes-agent",
            "market_context": {
                "price": price,
                "change_24h": data.get("change_24h", 0),
                "fear_greed": snapshot.get("portfolio", {}).get("fear_greed", 50),
            },
            "direction": direction,
            "signal": signal,
            "prediction": {
                "target_price": target,
                "invalidation_price": invalidation,
                "timeframe": "4H",
                "confidence": c["cal"],
                "confidence_raw": c["raw"],
                "tier": tier,
                "forced": c.get("forced", False),
            },
            "support_resistance": {
                "resistance": resistance,
                "support": support,
            },
            "indicators_used": {
                "rsi": {"value": round(rsi_val, 1), "signal": rsi_sig},
                "macd": {"signal": macd_class, "hist": round(macd_hist, 2)},
                "bb": {"position": bb_pos, "width": round(bb_width, 4), "squeeze": bool(ind.get("bb_squeeze", False))},
                "ema": {"cross": "BEARISH" if ema9 < ema21 else "BULLISH", "alignment": ind.get("ema_alignment", "MIXED")},
            },
            "patterns": patterns,
            "status": "PREDICTED",
            "forced": c.get("forced", False),
        }
        new_predictions.append(pred_entry)
        preds.append(pred_entry)
    
    # === STEP 6: Update learning weights ===
    all_verified = [p for p in preds if (p.get("verification") or {}).get("result") in 
                    ("SUCCESS", "PARTIAL_SUCCESS", "FAILURE")]
    all_correct = [p for p in preds if (p.get("verification") or {}).get("result") in 
                   ("SUCCESS", "PARTIAL_SUCCESS")]
    
    final_accuracy = len(all_correct) / len(all_verified) if all_verified else 0.5
    
    if final_accuracy > 0.8:
        final_cal = 1.0
        final_tier = "HIGH"
    elif final_accuracy > 0.6:
        final_cal = 0.85
        final_tier = "MEDIUM"
    elif final_accuracy > 0.4:
        final_cal = 0.7
        final_tier = "LOW"
    else:
        final_cal = 0.5
        final_tier = "UNRELIABLE"
    
    # === STEP 7: Save registry ===
    status_counts = {}
    for p in preds:
        s = p.get("status", "UNKNOWN")
        status_counts[s] = status_counts.get(s, 0) + 1
    
    registry["predictions"] = preds
    registry["last_updated"] = now.isoformat()
    registry["summary"] = {
        "total": len(preds),
        "pending": status_counts.get("PREDICTED", 0),
        "verified": status_counts.get("VERIFIED", 0),
        "expired": status_counts.get("EXPIRED", 0),
        "correct": len(all_correct),
    }
    registry["accuracy_rate"] = final_accuracy
    registry["calibration_multiplier"] = final_cal
    registry["calibration_tier"] = final_tier
    
    save_json(REGISTRY_PATH, registry)
    
    # Update learning weights
    weights["accuracy_rate"] = final_accuracy
    weights["calibration_multiplier"] = final_cal
    weights["calibration_tier"] = final_tier
    weights["total_predictions"] = len(preds)
    weights["verified_predictions"] = len(all_verified)
    weights["correct_predictions"] = len(all_correct)
    weights["total_verified"] = len(all_verified)
    weights["correct_verified"] = len(all_correct)
    weights["last_recalculated"] = now.isoformat()
    weights["last_updated"] = now.isoformat()
    
    save_json(WEIGHTS_PATH, weights)
    
    # === STEP 8: Build output ===
    portfolio = snapshot.get("portfolio", {})
    
    # Determine tier for each prediction
    def get_tier(cal):
        if cal >= 70: return "HIGH"
        elif cal >= 55: return "MEDIUM"
        elif cal >= 40: return "LOW"
        else: return "UNRELIABLE"
    
    # Build Telegram formatted output
    tg_lines = [
        f"ANALYSIS & PREDICTIONS \u2014 {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Snapshot age: {round(snap_age_min, 0)} min | Fear & Greed: {portfolio.get('fear_greed', '?')}",
        f"Portfolio: ${portfolio.get('total_equity', 0):.2f} | Positions: {len(portfolio.get('positions', []))}",
        "",
        "MARKET STRUCTURE:",
        f"  All 8 assets BEAR_ALIGNED: {'YES' if all(snapshot['assets'].get(s, {}).get('indicators_4h', {}).get('ema_alignment', '') in ('BEAR_ALIGNED', 'FULL_BEAR') for s in TRACKED if s in snapshot.get('assets', {})) else 'NO'}",
        "",
        f"PREDICTIONS ({len(new_predictions)} natural + {len(forced)} forced):",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
    ]
    
    for p in new_predictions:
        sym = p["symbol"]
        d = p["direction"]
        sig = p["signal"]
        tgt = p["prediction"]["target_price"]
        inv = p["prediction"]["invalidation_price"]
        conf = p["prediction"]["confidence"]
        tier = p["prediction"]["tier"]
        is_forced = p["prediction"].get("forced", False)  # NOTE: use is_forced, not forced (pitfall #1)
        pid = p["prediction_id"]
        
        ind = p["indicators_used"]
        
        forced_tag = " [FORCED]" if is_forced else ""
        tg_lines.extend([
            f"{sym} {d} ({sig}){forced_tag}",
            f"  Target: ${tgt} | Stop: ${inv}",
            f"  Confidence: {conf}% [{tier}]",
            f"  ID: {pid}",
            f"  RSI: {ind['rsi']['value']} ({ind['rsi']['signal']}) | MACD: {ind['macd']['signal']}",
            f"  BB: {ind['bb']['position']} | EMA: {ind['ema']['alignment']}",
            "",
        ])
    
    if skipped:
        tg_lines.append("WATCH LIST (below threshold):")
        for c in skipped:
            tg_lines.append(f"  {c['symbol']} -- cal {c['cal']}% (bear:{c['bear_cal']}, bull:{c['bull_cal']})")
        tg_lines.append("")
    
    tg_lines.extend([
        "LEARNING STATUS:",
        f"  Accuracy: {final_accuracy:.1%} ({len(all_correct)}/{len(all_verified)})",
        f"  Cal mult: {final_cal} [{final_tier}]",
        f"  Verified this cycle: {verified_count}",
        f"  Cleaned EXPIRED: {clean_count}",
        f"  Registry: {len(preds)} total",
    ])
    
    output = {
        "timestamp": now.isoformat(),
        "snapshot_age_min": round(snap_age_min, 1),
        "fear_greed": portfolio.get("fear_greed", "?"),
        "portfolio": {
            "total_equity": portfolio.get("total_equity", 0),
            "positions_count": len(portfolio.get("positions", [])),
        },
        "market_structure": {
            "all_bear_aligned": all(
                snapshot["assets"].get(s, {}).get("indicators_4h", {}).get("ema_alignment", "") in ("BEAR_ALIGNED", "FULL_BEAR")
                for s in TRACKED if s in snapshot.get("assets", {})
            ),
        },
        "learning": {
            "accuracy_rate": round(final_accuracy, 4),
            "calibration_multiplier": final_cal,
            "calibration_tier": final_tier,
            "verified_count": len(all_verified),
            "correct_count": len(all_correct),
            "prediction_threshold": prediction_threshold,
        },
        "predictions": new_predictions,
        "forced_predictions": len(forced),
        "skipped_assets": [{"symbol": c["symbol"], "reason": f"calibrated {c['cal']}% <= threshold {prediction_threshold}%"} for c in skipped],
        "watch_list": [{"symbol": c["symbol"], "price": float(c["data"].get("price", 0)), "bear_cal": c["bear_cal"], "bull_cal": c["bull_cal"]} for c in skipped],
        "registry_cleanup": {
            "expired_cleaned": clean_count,
            "verified_this_cycle": verified_count,
            "total_predictions": len(preds),
        },
        "formatted_output": "\n".join(tg_lines),
    }
    
    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
