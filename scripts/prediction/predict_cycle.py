#!/usr/bin/env python3
"""
Prediction cycle: verify old predictions + generate new ones + format output.
Runs after pattern_detect.py to complete the full cronjob cycle.

Usage:
  cd /home/ubuntu && /home/ubuntu/.hermes-venv/bin/python3 \
    ~/.hermes/skills/trading/crypto_portfolio_monitor_learning/scripts/predict_cycle.py

Input: Hardcoded analysis data from pattern_detect.py (paste output into the ANALYSIS dict below).
Output: Telegram-formatted text to stdout, updates prediction_registry.json.

NOTE: This script must be run via terminal() with hermes venv Python, NOT execute_code.
The analysis data below must be updated each cycle from pattern_detect.py output.
"""
import json, hashlib, datetime, os

# ============================================================
# PASTE PATTERN_DETECT OUTPUT HERE each cycle
# Replace this dict with the "analysis" section from pattern_detect.py JSON output
# ============================================================
ANALYSIS = {}  # Will be populated by the cronjob agent

# Portfolio state - also updated each cycle from pattern_detect.py output
PORTFOLIO = {"equity": 0, "balance": 0, "available": 0, "total_pnl": 0, "pnl_pct": 0, "positions_count": 0}

# ============================================================
# MACD Signal Classification
# ============================================================
def classify_macd(macd_line, macd_signal, macd_hist, prev_macd_line=None, prev_macd_signal=None, prev_macd_hist=None):
    """
    Classify MACD state with proper distinction between cross and recovery.

    Returns one of:
      BULLISH_CROSS    - MACD just crossed above signal (hist turned positive this bar)
      BEARISH_CROSS    - MACD just crossed below signal (hist turned negative this bar)
      BULLISH_RECOVERY - Histogram positive but line still below signal (recovering)
      BEARISH_RECOVERY - Histogram negative but line still above signal (weakening)
      BULLISH          - Line above signal, histogram positive and growing
      BEARISH          - Line below signal, histogram negative and growing
      NEUTRAL          - Flat/unclear
    """
    if prev_macd_hist is not None:
        if prev_macd_hist <= 0 and macd_hist > 0:
            return "BULLISH_CROSS"
        elif prev_macd_hist >= 0 and macd_hist < 0:
            return "BEARISH_CROSS"

    if macd_line > macd_signal:
        if macd_hist > 0:
            return "BULLISH"
        else:
            return "BEARISH_RECOVERY"
    else:
        if macd_hist > 0:
            return "BULLISH_RECOVERY"
        elif macd_hist < 0:
            return "BEARISH"
        else:
            return "NEUTRAL"

# ============================================================
# RSI Signal Classification
# ============================================================
def classify_rsi(rsi):
    if rsi > 70: return "OVERBOUGHT"
    elif rsi < 30: return "OVERSOLD"
    elif rsi > 55: return "BULLISH"
    elif rsi < 45: return "BEARISH"
    else: return "NEUTRAL"

# ============================================================
# BB Position Classification
# ============================================================
def classify_bb_position(price, bb_upper, bb_lower, bb_mid):
    if price > bb_upper: return "ABOVE_UPPER"
    elif price < bb_lower: return "BELOW_LOWER"
    elif price > bb_mid: return "UPPER_HALF"
    elif price < bb_mid: return "LOWER_HALF"
    else: return "MIDDLE"

# ============================================================
# Prediction ID Generator
# ============================================================
def gen_id(symbol, ts):
    h = hashlib.md5(f"{symbol}{ts}".encode()).hexdigest()[:4].upper()
    return f"PRED-{symbol}-{ts}-{h}"

# ============================================================
# Main Prediction Cycle
# ============================================================
def run_prediction_cycle(analysis, portfolio, calibration_multiplier=1.0):
    """
    Full prediction cycle: verify old + generate new + format output.

    Args:
        analysis: dict of {symbol: {price, ema_alignment, rsi, macd_hist, ...}}
        portfolio: dict with equity, balance, total_pnl, etc.
        calibration_multiplier: from learning weights (default 1.0 = no history)

    Returns:
        (output_text, registry_update) tuple
    """
    now = datetime.datetime.now(datetime.timezone.utc)

    # Load registry
    reg_path = os.path.expanduser(
        "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/prediction_registry.json"
    )
    try:
        with open(reg_path) as f:
            registry = json.load(f)
    except Exception:
        registry = {"predictions": [], "summary": {"total": 0, "pending": 0, "verified": 0, "expired": 0}}

    # --- VERIFY OLD PREDICTIONS ---
    verification_results = []
    for pred in registry["predictions"]:
        if pred["status"] != "PREDICTED":
            continue
        sym = pred["symbol"]
        if sym not in analysis:
            continue
        current_price = analysis[sym]["price"]

        # Handle both flat format (old) and nested format (new)
        if "target_price" in pred:
            target = pred["target_price"]
            invalidation = pred["invalidation_price"]
            direction = pred["direction"]
        elif "prediction" in pred:
            target = pred["prediction"]["target_price"]
            invalidation = pred["prediction"]["invalidation_price"]
            direction = pred["prediction"]["direction"]
        else:
            continue

        if direction == "BULLISH":
            if current_price >= target:
                pred["status"] = "SUCCESS"
                pred["verification"] = {"result": "SUCCESS", "price_at_verify": current_price, "verified_at": now.isoformat()}
            elif current_price <= invalidation:
                pred["status"] = "FAILURE"
                pred["verification"] = {"result": "FAILURE", "price_at_verify": current_price, "verified_at": now.isoformat()}
        elif direction == "BEARISH":
            if current_price <= target:
                pred["status"] = "SUCCESS"
                pred["verification"] = {"result": "SUCCESS", "price_at_verify": current_price, "verified_at": now.isoformat()}
            elif current_price >= invalidation:
                pred["status"] = "FAILURE"
                pred["verification"] = {"result": "FAILURE", "price_at_verify": current_price, "verified_at": now.isoformat()}
        elif direction == "NEUTRAL":
            if current_price >= target or current_price <= invalidation:
                pred["status"] = "PARTIAL"
                pred["verification"] = {"result": "PARTIAL", "price_at_verify": current_price, "verified_at": now.isoformat()}

        # Expire predictions older than 48 hours
        try:
            pred_time = datetime.datetime.fromisoformat(pred["timestamp"].replace("Z", "+00:00"))
            if (now - pred_time).total_seconds() > 48 * 3600 and pred["status"] == "PREDICTED":
                pred["status"] = "EXPIRED"
                pred["verification"] = {"result": "EXPIRED", "reason": "Time expired (48h)"}
        except Exception:
            pass

        verification_results.append({"id": pred["prediction_id"], "symbol": sym, "status": pred["status"]})

    # Update summary
    pending = [p for p in registry["predictions"] if p["status"] == "PREDICTED"]
    verified = [p for p in registry["predictions"] if p["status"] == "SUCCESS"]
    partial = [p for p in registry["predictions"] if p["status"] == "PARTIAL"]
    failed = [p for p in registry["predictions"] if p["status"] == "FAILURE"]
    expired = [p for p in registry["predictions"] if p["status"] == "EXPIRED"]

    registry["summary"] = {
        "total": len(registry["predictions"]),
        "pending": len(pending),
        "success": len(verified),
        "partial_success": len(partial),
        "failure": len(failed),
        "expired": len(expired)
    }

    # --- GENERATE NEW PREDICTIONS ---
    new_predictions = []
    ts = now.strftime("%Y%m%d%H%M%S")

    for sym, data in analysis.items():
        price = data["price"]
        ema_a = data["ema_alignment"]
        rsi = data["rsi"]
        macd_hist = data["macd_hist"]
        macd_line = data["macd_line"]
        macd_signal_val = data["macd_signal"]
        bb_upper = data["bb_upper"]
        bb_lower = data["bb_lower"]
        bb_mid = data["bb_mid"]
        patterns = data["patterns"]
        ms = data["market_structure"]
        vol_ratio = data["vol_ratio"]
        atr = data["atr"]

        pattern_names = [p["name"] for p in patterns]
        has_squeeze = "BB_SQUEEZE" in pattern_names

        # Determine direction via scoring
        bull_score = 0
        bear_score = 0

        if ema_a == "BULLISH": bull_score += 2
        elif ema_a == "BEARISH": bear_score += 2
        if rsi > 55: bull_score += 1
        elif rsi < 45: bear_score += 1
        if macd_hist > 0: bull_score += 1
        elif macd_hist < 0: bear_score += 1
        if macd_line > macd_signal_val: bull_score += 1
        else: bear_score += 1
        if price > bb_mid: bull_score += 1
        else: bear_score += 1
        if ms in ["BREAKOUT_HIGH", "HIGHER_HL"]: bull_score += 2
        elif ms in ["BREAKDOWN_LOW", "LOWER_LH"]: bear_score += 2

        net = bull_score - bear_score
        if net >= 2:
            direction, target, invalidation = "BULLISH", bb_upper, bb_lower
        elif net <= -2:
            direction, target, invalidation = "BEARISH", bb_lower, bb_upper
        else:
            direction, target, invalidation = "NEUTRAL", bb_upper, bb_lower

        # Calculate confidence
        conf = 50
        if has_squeeze: conf += 15
        if direction == "BULLISH":
            if ema_a == "BULLISH": conf += 10
            if macd_hist > 0 and macd_line > macd_signal_val: conf += 10
            if rsi > 50: conf += 10
            if price > bb_mid: conf += 10
        elif direction == "BEARISH":
            if ema_a == "BEARISH": conf += 10
            if macd_hist < 0 and macd_line < macd_signal_val: conf += 10
            if rsi < 50: conf += 10
            if price < bb_mid: conf += 10
        else:
            conf += 5
        if direction == "BULLISH" and ms in ["BREAKOUT_HIGH", "HIGHER_HL"]: conf += 10
        elif direction == "BEARISH" and ms in ["BREAKDOWN_LOW", "LOWER_LH"]: conf += 10
        elif direction != "NEUTRAL": conf -= 10
        if portfolio.get("total_pnl", 0) >= 0: conf += 5
        if vol_ratio < 0.5: conf -= 10

        calibrated = max(30, min(95, round(conf * calibration_multiplier)))
        tier = "HIGH" if calibrated >= 70 else "MEDIUM" if calibrated >= 55 else "LOW"

        # Support/Resistance levels
        if direction == "BULLISH":
            resistance = [bb_upper, round(bb_upper + atr * 0.5, 4)]
            support = [bb_mid, round(bb_lower, 4)]
        elif direction == "BEARISH":
            resistance = [bb_upper, round(bb_upper + atr * 0.5, 4)]
            support = [bb_lower, round(bb_lower - atr * 0.5, 4)]
        else:
            resistance, support = [bb_upper], [bb_lower]

        # Round prices
        if price > 1000:
            target, invalidation = round(target, 1), round(invalidation, 1)
            resistance, support = [round(r, 1) for r in resistance], [round(s, 1) for s in support]
        elif price > 10:
            target, invalidation = round(target, 2), round(invalidation, 2)
            resistance, support = [round(r, 2) for r in resistance], [round(s, 2) for s in support]
        elif price > 1:
            target, invalidation = round(target, 4), round(invalidation, 4)
            resistance, support = [round(r, 4) for r in resistance], [round(s, 4) for s in support]
        else:
            target, invalidation = round(target, 5), round(invalidation, 5)
            resistance, support = [round(r, 5) for r in resistance], [round(s, 5) for s in support]

        # Classify signals using proper functions
        macd_sig = classify_macd(macd_line, macd_signal_val, macd_hist)
        rsi_sig = classify_rsi(rsi)
        bb_pos = classify_bb_position(price, bb_upper, bb_lower, bb_mid)

        new_predictions.append({
            "prediction_id": gen_id(sym, ts),
            "timestamp": now.isoformat(),
            "symbol": sym,
            "direction": direction,
            "signal": "BUY" if direction == "BULLISH" else "SELL" if direction == "BEARISH" else "HOLD",
            "target_price": target,
            "invalidation_price": invalidation,
            "timeframe": "4H",
            "confidence": calibrated,
            "confidence_tier": tier,
            "market_context": {"price": price, "daily_trend": ema_a, "ema_alignment": ema_a},
            "indicators": {"rsi": rsi, "macd_hist": macd_hist, "bb_position": bb_pos, "macd_signal": macd_sig},
            "support_resistance": {"resistance": resistance, "support": support},
            "patterns_detected": pattern_names,
            "market_structure": ms,
            "status": "PREDICTED"
        })

    # Update registry
    registry["predictions"].extend(new_predictions)
    registry["last_updated"] = now.isoformat()
    registry["summary"]["total"] = len(registry["predictions"])
    registry["summary"]["pending"] = len([p for p in registry["predictions"] if p["status"] == "PREDICTED"])

    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    with open(reg_path, "w") as f:
        json.dump(registry, f, indent=2)

    # --- BUILD OUTPUT ---
    lines = []
    lines.append(f"CRYPTO PREDICTIONS -- {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("========================================")
    lines.append("")
    lines.append(f"PORTFOLIO: ${portfolio['equity']:.2f} | PnL: ${portfolio['total_pnl']:.2f} ({portfolio['pnl_pct']:.2f}%) | {portfolio['positions_count']} positions")
    lines.append("")

    if verification_results:
        lines.append("VERIFICATION:")
        for v in verification_results:
            emoji_map = {"SUCCESS": "[OK]", "FAILURE": "[FAIL]", "PARTIAL": "[WARN]", "EXPIRED": "[TIME]", "PREDICTED": "[WAIT]"}
            lines.append(f"  {emoji_map.get(v['status'], '[?]')} {v['id']}: {v['status']}")
        lines.append("")

    for p in new_predictions:
        dir_mark = {"BULLISH": ">>> BULL", "BEARISH": "<<< BEAR", "NEUTRAL": "--- NEUTRAL"}.get(p["direction"], "???")
        lines.append(f"SYMBOL: {p['symbol']} | {dir_mark}")
        lines.append(f"  Target: ${p['target_price']}")
        lines.append(f"  Invalidation: ${p['invalidation_price']}")
        lines.append(f"  Confidence: {p['confidence']}% ({p['confidence_tier']})")
        lines.append(f"  ID: {p['prediction_id']}")
        lines.append(f"  RSI: {p['indicators']['rsi']:.1f} ({p['indicators']['macd_signal']}) | BB: {p['indicators']['bb_position']} | MS: {p['market_structure']}")
        if p["patterns_detected"]:
            lines.append(f"  Patterns: {', '.join(p['patterns_detected'])}")
        lines.append("")

    lines.append("========================================")
    lines.append(f"Total: {len(new_predictions)} | Pending: {registry['summary']['pending']}")
    avg_conf = round(sum(p["confidence"] for p in new_predictions) / len(new_predictions)) if new_predictions else 0
    lines.append(f"Avg Confidence: {avg_conf}%")
    lines.append(f"Calibration: {calibration_multiplier}x")

    return "\n".join(lines), registry

# ============================================================
# Standalone execution (for testing or when analysis is hardcoded)
# ============================================================
if __name__ == "__main__":
    if not ANALYSIS:
        print("ERROR: ANALYSIS dict is empty. Paste pattern_detect.py output into the script.")
        print("Usage: Update ANALYSIS and PORTFOLIO dicts, then run.")
    else:
        output, _ = run_prediction_cycle(ANALYSIS, PORTFOLIO)
        print(output)
