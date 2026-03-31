#!/usr/bin/env python3
"""ANALYZE & PREDICT — Mode 3 (snapshot-based, no API calls)
Validated: 2026-06-03. Uses confidence_calculation.md reference modifiers.
Handles: both snapshot formats, verification null, status-safe iteration.
Run: cd /home/ubuntu && /home/ubuntu/.hermes-venv/bin/python3 /tmp/analyze_predict.py
"""
import json, os, hashlib, warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore", category=DeprecationWarning)

SKILL_DIR = os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning")
SNAP_PATH = os.path.join(SKILL_DIR, "data/latest_snapshot.json")
REG_PATH = os.path.join(SKILL_DIR, "data/prediction_registry.json")
LW_PATH = os.path.join(SKILL_DIR, "data/learning_weights.json")

TIER1 = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "HYPEUSDT"}

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default or {}

def generate_pred_id(symbol, ts):
    h = hashlib.md5(f"{symbol}{ts}".encode()).hexdigest()[:4].upper()
    return f"PRED-{symbol}-{ts}-{h}"

def classify_macd(macd_hist, ema9, ema21, prev_hist=None):
    if macd_hist > 0:
        if prev_hist is not None and prev_hist <= 0:
            return "BULLISH_CROSS"
        elif ema9 > ema21 and macd_hist > 0:
            return "BULLISH"
        else:
            return "BULLISH_RECOVERY"
    else:
        if prev_hist is not None and prev_hist > 0:
            return "BEARISH_CROSS"
        elif ema9 < ema21 and macd_hist < 0:
            return "BEARISH"
        else:
            return "BEARISH_RECOVERY"

def score_direction(data, direction, cal_mult):
    """Score a direction (BULLISH or BEARISH) using reference modifiers."""
    ind4h = data.get("indicators_4h", {})
    ind1h = data.get("indicators_1h", {})
    price = data.get("price", 0)
    vol_ratio = data.get("vol_ratio", 1.0)

    rsi_4h = ind4h.get("rsi", 50)
    rsi_1h = ind1h.get("rsi", 50)
    macd_hist = ind4h.get("macd_hist", 0)
    bb_width = ind4h.get("bb_width", 0.1)
    bb_sq = ind4h.get("bb_squeeze", False)
    ema9 = ind4h.get("ema9", price)
    ema21 = ind4h.get("ema21", price)
    ema_align = ind4h.get("ema_alignment", "MIXED")
    bb_1h_width = ind1h.get("bb_width", 0.1)

    base = 50
    score = base
    reasons = []

    # === SQUEEZE (ref: +12 multi-TF, +8 4H, +6 1H) ===
    sq_threshold = 0.02
    sq_1h_threshold = sq_threshold * 0.5
    multi_tf_sq = bb_sq and bb_1h_width < sq_1h_threshold
    sq_1h = bb_1h_width < sq_1h_threshold and not bb_sq
    sq_4h = bb_sq and not multi_tf_sq

    if multi_tf_sq:
        score += 12; reasons.append("Multi-TF squeeze +12")
    elif sq_1h:
        score += 6; reasons.append("1H squeeze +6")
    elif sq_4h:
        score += 8; reasons.append("4H squeeze +8")

    # === MACD (ref: +/-8 cross/strong, +/-4 recovery) ===
    macd_class = classify_macd(macd_hist, ema9, ema21)
    macd_mods = {
        "BULLISH_CROSS": 8, "BULLISH": 8, "BULLISH_RECOVERY": 4,
        "BEARISH_CROSS": -8, "BEARISH": -8, "BEARISH_RECOVERY": -4,
    }
    macd_mod = macd_mods.get(macd_class, 0)
    if direction == "BEARISH":
        macd_mod = -macd_mod
    score += macd_mod
    if macd_mod != 0:
        reasons.append(f"MACD {macd_class} {'+'if macd_mod>0 else ''}{macd_mod}")

    # === RSI (ref: 4H +/-3, 1H +/-2) ===
    if direction == "BULLISH":
        rsi_4h_mod = 3 if rsi_4h < 45 else (-3 if rsi_4h > 55 else 0)
        rsi_1h_mod = 2 if rsi_1h < 45 else (-2 if rsi_1h > 55 else 0)
    else:
        rsi_4h_mod = 3 if rsi_4h > 55 else (-3 if rsi_4h < 45 else 0)
        rsi_1h_mod = 2 if rsi_1h > 55 else (-2 if rsi_1h < 45 else 0)
    score += rsi_4h_mod + rsi_1h_mod
    if rsi_4h_mod != 0: reasons.append(f"RSI 4H {'+'if rsi_4h_mod>0 else ''}{rsi_4h_mod}")
    if rsi_1h_mod != 0: reasons.append(f"RSI 1H {'+'if rsi_1h_mod>0 else ''}{rsi_1h_mod}")

    # === EMA ALIGNMENT (ref: bullish aligned +8, bearish aligned -10; 1H +/-4) ===
    if direction == "BULLISH":
        ema_4h_mod = 8 if ema_align == "BULLISH_ALIGNED" else (-10 if ema_align == "BEARISH_ALIGNED" else 0)
        ema_1h_mod = 4 if ema9 > ema21 else -4
    else:
        ema_4h_mod = 10 if ema_align == "BEARISH_ALIGNED" else (-8 if ema_align == "BULLISH_ALIGNED" else 0)
        ema_1h_mod = 4 if ema9 < ema21 else -4
    score += ema_4h_mod + ema_1h_mod
    if ema_4h_mod != 0: reasons.append(f"EMA 4H {'+'if ema_4h_mod>0 else ''}{ema_4h_mod}")
    if ema_1h_mod != 0: reasons.append(f"EMA 1H {'+'if ema_1h_mod>0 else ''}{ema_1h_mod}")

    # === PRICE POSITION (ref: +/-3) ===
    if price > 0 and ema21 > 0:
        if direction == "BULLISH":
            pos_mod = 3 if price > ema21 else -3
        else:
            pos_mod = 3 if price < ema21 else -3
        score += pos_mod
        if pos_mod != 0:
            reasons.append(f"Price {'above' if pos_mod>0 else 'below'} EMA21 {'+'if pos_mod>0 else ''}{pos_mod}")

    # === VOLUME (low vol weakens signal) ===
    if vol_ratio < 0.7:
        score -= 3; reasons.append("Low volume -3")

    raw = max(20, min(100, score))
    calibrated = int(raw * cal_mult)
    calibrated = max(20, min(100, calibrated))

    return raw, calibrated, reasons, macd_class

def generate_target_invalidation(data, direction, price):
    ind4h = data.get("indicators_4h", {})
    ema9 = ind4h.get("ema9", price)
    ema21 = ind4h.get("ema21", price)
    if direction == "BULLISH":
        target = round(ema21, 6) if ema21 > price else round(price * 1.03, 6)
        invalidation = round(ema9, 6) if ema9 < price else round(price * 0.97, 6)
    else:
        target = round(ema9, 6) if ema9 < price else round(price * 0.97, 6)
        invalidation = round(ema21, 6) if ema21 > price else round(price * 1.03, 6)
    return target, invalidation

def main():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d%H%M%S")
    ts_iso = now.isoformat().replace("+00:00", "Z")

    snap = load_json(SNAP_PATH, {})
    registry = load_json(REG_PATH, {"predictions": [], "summary": {"total": 0, "pending": 0, "verified": 0, "correct": 0}})
    lw = load_json(LW_PATH, {})

    if not snap or "assets" not in snap:
        print(json.dumps({"error": "No snapshot data"}))
        return

    cal_mult = lw.get("calibration_multiplier", 0.85)
    if cal_mult < 0.6:
        cal_mult = 0.85  # safety fallback

    prediction_threshold = 50 if cal_mult >= 0.6 else int(cal_mult * 80)

    # Expire ALL old PREDICTED entries first
    for pred in registry.get("predictions", []):
        if pred.get("status") == "PREDICTED":
            pred["status"] = "EXPIRED"

    # Clean EXPIRED older than 7 days
    cutoff = now.timestamp() - 7 * 86400
    cleaned = []
    expired_kept = 0
    for pred in registry.get("predictions", []):
        if pred.get("status") == "EXPIRED":
            try:
                p_ts = datetime.fromisoformat(pred.get("timestamp", "2000-01-01T00:00:00+00:00")).timestamp()
                if p_ts > cutoff or expired_kept < 50:
                    cleaned.append(pred)
                    if p_ts > cutoff: expired_kept += 1
            except Exception:
                cleaned.append(pred)
        else:
            cleaned.append(pred)
    registry["predictions"] = cleaned

    # Generate predictions
    predictions = []
    watch_list = []
    candidates = []

    for sym, data in snap["assets"].items():
        price = data.get("price", 0)
        if price <= 0:
            continue

        bear_raw, bear_cal, bear_reasons, bear_macd = score_direction(data, "BEARISH", cal_mult)
        bull_raw, bull_cal, bull_reasons, bull_macd = score_direction(data, "BULLISH", cal_mult)

        # Always pick the stronger direction
        if bear_cal >= bull_cal:
            direction, raw, cal, reasons, macd_class = "BEARISH", bear_raw, bear_cal, bear_reasons, bear_macd
            signal = "SELL"
        else:
            direction, raw, cal, reasons, macd_class = "BULLISH", bull_raw, bull_cal, bull_reasons, bull_macd
            signal = "BUY"

        # Add to watch list if below threshold (but still add to candidates for force logic)
        if cal < prediction_threshold:
            watch_list.append({"symbol": sym, "price": price, "direction": direction,
                               "calibrated": cal, "reason": f"Below {prediction_threshold} threshold"})

        ind4h = data.get("indicators_4h", {})
        ind1h = data.get("indicators_1h", {})
        target, invalidation = generate_target_invalidation(data, direction, price)

        tier = "HIGH" if cal >= 70 else "MEDIUM" if cal >= 55 else "LOW" if cal >= 40 else "UNRELIABLE"
        pred_id = generate_pred_id(sym, ts)

        indicators = {
            "rsi": {"value": round(ind4h.get("rsi", 50), 2),
                    "signal": "OVERSOLD" if ind4h.get("rsi", 50) < 30 else "OVERBOUGHT" if ind4h.get("rsi", 50) > 70 else "NEUTRAL"},
            "macd": {"signal": macd_class, "hist": round(ind4h.get("macd_hist", 0), 4)},
            "bb": {"width": round(ind4h.get("bb_width", 0.1), 6), "squeeze": bool(ind4h.get("bb_squeeze", False))},
            "ema": {"alignment": ind4h.get("ema_alignment", "MIXED"),
                    "ema9": round(ind4h.get("ema9", 0), 6), "ema21": round(ind4h.get("ema21", 0), 6)}
        }

        candidates.append({
            "pred_id": pred_id, "symbol": sym, "direction": direction, "signal": signal,
            "target": target, "invalidation": invalidation,
            "raw": raw, "calibrated": cal, "tier": tier,
            "indicators": indicators, "patterns": [p.get("name", "?") for p in data.get("patterns", [])],
            "reasons": reasons, "price": price,
            "change_24h": data.get("change_24h", 0), "vol_ratio": data.get("vol_ratio", 1.0),
        })

    tier_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNRELIABLE": 3}
    candidates.sort(key=lambda x: (tier_order.get(x["tier"], 9), -x["calibrated"]))
    predictions = candidates[:8]

    # Force top-2 if zero natural predictions
    forced_count = 0
    if len(predictions) == 0 and len(candidates) > 0:
        candidates.sort(key=lambda x: -x["calibrated"])
        for c in candidates[:2]:
            c["forced"] = True; c["tier"] = "LOW"
            predictions.append(c)
            forced_count += 1

    # Add to registry
    for p in predictions:
        fg = snap.get("portfolio", {}).get("fear_greed")
        fg_val = fg.get("value") if isinstance(fg, dict) else fg
        pred_entry = {
            "prediction_id": p["pred_id"], "symbol": p["symbol"], "timestamp": ts_iso,
            "model_used": "mimo-v2.5",
            "market_context": {"price": p["price"], "change_24h": p["change_24h"],
                               "vol_ratio": p["vol_ratio"], "fear_greed": fg_val},
            "prediction": {"direction": p["direction"], "signal": p["signal"],
                           "target_price": p["target"], "invalidation_price": p["invalidation"],
                           "timeframe": "4H", "confidence": p["raw"],
                           "confidence_calibrated": p["calibrated"]},
            "indicators_used": p["indicators"], "patterns_detected": p["patterns"],
            "status": "PREDICTED", "forced": p.get("forced", False),
            "scoring_reasons": p["reasons"],
        }
        registry["predictions"].append(pred_entry)

    # Update summary
    preds = registry.get("predictions", [])
    verified = sum(1 for p in preds if p.get("status") == "VERIFIED")
    correct = sum(1 for p in preds if (p.get("verification") or {}).get("result") in ("SUCCESS", "PARTIAL_SUCCESS"))
    pending = sum(1 for p in preds if p.get("status") in ("PREDICTED", "PENDING"))
    registry["summary"] = {
        "total": len(preds), "pending": pending, "verified": verified, "correct": correct,
        "accuracy": round(correct / verified * 100, 1) if verified > 0 else 0,
    }

    os.makedirs(os.path.dirname(REG_PATH), exist_ok=True)
    with open(REG_PATH, "w") as f:
        json.dump(registry, f, indent=2)

    output = {
        "timestamp": ts_iso, "calibration_multiplier": cal_mult,
        "prediction_threshold": prediction_threshold, "forced_predictions": forced_count,
        "total_predictions": len(predictions), "total_watch_list": len(watch_list),
        "registry_summary": registry["summary"],
        "predictions": [{
            "symbol": p["symbol"], "direction": p["direction"], "signal": p["signal"],
            "target_price": p["target"], "invalidation_price": p["invalidation"],
            "raw_confidence": p["raw"], "calibrated_confidence": p["calibrated"],
            "tier": p["tier"], "prediction_id": p["pred_id"], "forced": p.get("forced", False),
            "indicators": p["indicators"], "patterns": p["patterns"], "reasons": p["reasons"],
        } for p in predictions],
        "watch_list": watch_list,
    }
    print(json.dumps(output, indent=2, default=str))

if __name__ == "__main__":
    main()
