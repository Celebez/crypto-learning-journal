#!/usr/bin/env python3
"""
PREDICT ONLY Cycle — Mode 3 (1-hour lightweight)
Loads latest snapshot, generates predictions, updates registry.
No API calls required — uses existing snapshot data.
"""
import json
import os
import hashlib
import warnings
from datetime import datetime, timezone, timedelta

warnings.filterwarnings("ignore", category=DeprecationWarning)

SNAPSHOT_PATH = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/latest_snapshot.json"
)
REGISTRY_PATH = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/prediction_registry.json"
)
WEIGHTS_PATH = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/learning_weights.json"
)
THRESHOLDS_PATH = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/references/adaptive_thresholds.json"
)

TRACKED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]
TIER1 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

def load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def make_pred_id(symbol, ts):
    h = hashlib.md5(f"{symbol}-{ts}-{os.urandom(2).hex()}".encode()).hexdigest()[:4].upper()
    return f"PRED-{symbol}-{ts}-{h}"

def classify_macd(hist, ema9, ema21):
    """Proper MACD classification per skill rules."""
    if hist > 0:
        if ema9 < ema21:
            return "BULLISH_RECOVERY"
        return "BULLISH"
    elif hist < 0:
        if ema9 > ema21:
            return "BEARISH_RECOVERY"
        return "BEARISH"
    return "NEUTRAL"

def classify_rsi(rsi):
    if rsi > 70: return "OVERBOUGHT"
    elif rsi > 55: return "BULLISH"
    elif rsi > 45: return "NEUTRAL"
    elif rsi > 30: return "BEARISH"
    return "OVERSOLD"

def classify_bb_position(price, ema21):
    if price > ema21 * 1.01: return "UPPER"
    elif price > ema21: return "UPPER_HALF"
    elif price > ema21 * 0.99: return "LOWER_HALF"
    return "LOWER"

def normalize_patterns(raw_patterns):
    result = []
    for p in raw_patterns:
        if isinstance(p, dict):
            result.append(p.get("name", ""))
        else:
            result.append(str(p))
    return result

def parse_snapshot(snapshot):
    """Handle BOTH snapshot formats: 'assets' (15m scan) and 'analysis' (4h cycle)."""
    if "analysis" in snapshot:
        return snapshot["analysis"]
    elif "assets" in snapshot:
        analysis = {}
        for sym, data in snapshot["assets"].items():
            ind4h = data.get("indicators_4h", {})
            ind1h = data.get("indicators_1h", {})
            analysis[sym] = {
                "price": data.get("price", 0),
                "change_24h": data.get("change_24h", 0),
                "rsi_4h": ind4h.get("rsi", 50),
                "rsi_1h": ind1h.get("rsi", 50),
                "bb_width_4h": ind4h.get("bb_width", 0.1),
                "bb_width_1h": ind1h.get("bb_width", 0.1),
                "bb_squeeze_4h": ind4h.get("bb_squeeze", False),
                "bb_squeeze_1h": ind1h.get("bb_squeeze", False),
                "macd_hist_4h": ind4h.get("macd_hist", 0),
                "ema9_4h": ind4h.get("ema9", data.get("price", 0)),
                "ema21_4h": ind4h.get("ema21", data.get("price", 0)),
                "ema_alignment_4h": ind4h.get("ema_alignment", "MIXED"),
                "vol_ratio": data.get("vol_ratio", 1.0),
                "patterns": data.get("patterns", []),
            }
        return analysis
    return {}

def recalculate_accuracy(registry):
    """Recalculate accuracy from verified predictions (exclude EXPIRED)."""
    verified_results = []
    for p in registry.get("predictions", []):
        v = p.get("verification") or {}
        result_v = v.get("result")
        if result_v in ("SUCCESS", "PARTIAL_SUCCESS", "FAILURE"):
            verified_results.append(result_v)

    correct = sum(1 for r in verified_results if r in ("SUCCESS", "PARTIAL_SUCCESS"))
    total = len(verified_results)

    if total > 0:
        accuracy = correct / total
    else:
        accuracy = 0.5

    if accuracy > 0.8: cal_mult = 1.0; tier = "HIGH"
    elif accuracy > 0.6: cal_mult = 0.85; tier = "MEDIUM"
    elif accuracy > 0.4: cal_mult = 0.70; tier = "LOW"
    else: cal_mult = 0.50; tier = "UNRELIABLE"

    # Override with file value if it exists and is higher (prevent death spiral)
    return accuracy, correct, total, cal_mult, tier

def score_direction(data, direction, price):
    """Score a specific direction (BULLISH or BEARISH) for an asset."""
    rsi_4h = data.get("rsi_4h", data.get("rsi", 50))
    rsi_1h = data.get("rsi_1h", 50)
    ma = data.get("ema_alignment_4h", data.get("ema_alignment", "MIXED"))
    macd_hist = data.get("macd_hist_4h", data.get("macd_hist", 0))
    bb_squeeze_4h = data.get("bb_squeeze_4h", data.get("bb_squeeze", False))
    bb_squeeze_1h = data.get("bb_squeeze_1h", False)
    ema9 = data.get("ema9_4h", data.get("ema9", price))
    ema21 = data.get("ema21_4h", data.get("ema21", price))
    vol_ratio = data.get("vol_ratio", 1.0)
    change_24h = data.get("change_24h", 0)

    raw = 50  # base
    # Multi-TF squeeze
    if bb_squeeze_4h and bb_squeeze_1h:
        raw += 15
    elif bb_squeeze_4h or bb_squeeze_1h:
        raw += 5
    # EMA/MACD alignment
    macd_class = classify_macd(macd_hist, ema9, ema21)
    if direction == "BEARISH":
        if ma in ("BEAR_ALIGNED", "FULL_BEAR"):
            raw += 10
        elif macd_class == "BEARISH":
            raw += 5
    else:
        if ma in ("BULL_ALIGNED", "FULL_BULL"):
            raw += 10
        elif macd_class == "BULLISH":
            raw += 5
    # RSI confirmation
    if direction == "BEARISH":
        if rsi_4h < 50: raw += 10
        elif rsi_4h < 55: raw += 3
    else:
        if rsi_4h > 50: raw += 10
        elif rsi_4h > 45: raw += 3
        if rsi_4h < 25: raw += 8  # strong oversold bounce
        elif rsi_4h < 30: raw += 5
    # Price position
    if direction == "BEARISH" and price < ema21: raw += 10
    elif direction == "BULLISH" and price > ema21: raw += 10
    # PnL stable
    raw += 5
    # Negative factors
    if direction == "BEARISH" and ma in ("BULL_ALIGNED", "FULL_BULL"):
        raw -= 15
    elif direction == "BULLISH" and ma in ("BEAR_ALIGNED", "FULL_BEAR"):
        raw -= 15
    if vol_ratio < 0.3: raw -= 10
    if not bb_squeeze_4h and not bb_squeeze_1h: raw -= 5
    else: raw -= 10
    abs_change = abs(change_24h) if isinstance(change_24h, (int, float)) else 0
    if abs_change > 5: raw -= 10
    elif abs_change > 3: raw -= 5
    return max(raw, 0)

def calc_support_resistance(price, bb_width, ema21):
    band_range = price * bb_width
    resistance = [round(ema21 + band_range * 0.5, 4), round(ema21 + band_range, 4)]
    support = [round(ema21 - band_range * 0.5, 4), round(ema21 - band_range, 4)]
    return {"resistance": resistance, "support": support}

def main():
    snapshot = load_json(SNAPSHOT_PATH)
    registry = load_json(REGISTRY_PATH, {"version": "1.0", "predictions": []})
    weights = load_json(WEIGHTS_PATH)
    thresholds = load_json(THRESHOLDS_PATH)

    now = datetime.now(timezone.utc)
    ts_str = now.strftime("%Y%m%d%H%M%S")
    ts_iso = now.isoformat()

    # Check snapshot freshness
    snap_ts = snapshot.get("timestamp", "")
    age_min = 0
    if snap_ts:
        try:
            snap_dt = datetime.fromisoformat(snap_ts.replace("Z", "+00:00"))
            age_min = (now - snap_dt).total_seconds() / 60
        except Exception:
            pass

    # Recalculate accuracy from verified predictions
    recalc_accuracy, correct_count, total_verified, file_cal, file_tier = recalculate_accuracy(registry)
    file_cal_from_weights = weights.get("calibration_multiplier", file_cal)
    cal_mult = max(file_cal, file_cal_from_weights)  # use higher of recalculated vs file

    if cal_mult > 0.8: cal_tier = "HIGH"
    elif cal_mult > 0.6: cal_tier = "MEDIUM"
    elif cal_mult > 0.4: cal_tier = "LOW"
    else: cal_tier = "UNRELIABLE"

    # Parse snapshot (handles both formats)
    analysis = parse_snapshot(snapshot)
    portfolio = snapshot.get("portfolio", {})
    positions = {p["symbol"]: p for p in snapshot.get("positions", [])}
    fear_greed = portfolio.get("fear_greed", 50)

    # Dynamic threshold (death spiral fix)
    prediction_threshold = 50 if cal_mult >= 0.6 else int(cal_mult * 80)

    # Expire ALL old PREDICTED entries
    for pred in registry.get("predictions", []):
        if pred.get("status") == "PREDICTED":
            pred["status"] = "EXPIRED"

    # Clean EXPIRED entries older than 7 days
    cutoff = now - timedelta(days=7)
    cleaned = []
    for pred in registry.get("predictions", []):
        if pred.get("status") == "EXPIRED":
            try:
                ts = datetime.fromisoformat(pred.get("timestamp", "2000-01-01T00:00:00+00:00"))
                if ts > cutoff:
                    cleaned.append(pred)
            except Exception:
                cleaned.append(pred)
        else:
            cleaned.append(pred)
    registry["predictions"] = cleaned

    # Score and categorize each asset
    candidates = []
    watch_list = []

    for sym in TRACKED:
        if sym not in analysis:
            continue
        data = analysis[sym]
        price = data.get("price", 0)
        if price <= 0:
            continue

        rsi_4h = data.get("rsi_4h", data.get("rsi", 50))
        rsi_1h = data.get("rsi_1h", 50)
        ema_align = data.get("ema_alignment_4h", data.get("ema_alignment", "MIXED"))
        macd_hist = data.get("macd_hist_4h", data.get("macd_hist", 0))
        bb_squeeze_4h = data.get("bb_squeeze_4h", data.get("bb_squeeze", False))
        bb_squeeze_1h = data.get("bb_squeeze_1h", False)
        ema9 = data.get("ema9_4h", data.get("ema9", price))
        ema21 = data.get("ema21_4h", data.get("ema21", price))
        vol_ratio = data.get("vol_ratio", 1.0)
        bb_width = data.get("bb_width_4h", data.get("bb_width", 0.1))
        patterns_raw = data.get("patterns", [])
        pattern_names = normalize_patterns(patterns_raw)

        # Score both directions
        bullish_raw = score_direction(data, "BULLISH", price)
        bearish_raw = score_direction(data, "BEARISH", price)
        bullish_cal = int(bullish_raw * cal_mult)
        bearish_cal = int(bearish_raw * cal_mult)

        # Pick best direction
        if bullish_cal > bearish_cal:
            best_dir, best_signal, best_raw, best_cal = "BULLISH", "BUY", bullish_raw, bullish_cal
        elif bearish_cal > bullish_cal:
            best_dir, best_signal, best_raw, best_cal = "BEARISH", "SELL", bearish_raw, bearish_cal
        else:
            if ema_align in ("BEAR_ALIGNED", "FULL_BEAR"):
                best_dir, best_signal = "BEARISH", "SELL"
            else:
                best_dir, best_signal = "BULLISH", "BUY"
            best_raw = bearish_raw if best_dir == "BEARISH" else bullish_raw
            best_cal = bearish_cal if best_dir == "BEARISH" else bullish_cal

        rsi_signal = classify_rsi(rsi_4h)
        macd_signal = classify_macd(macd_hist, ema9, ema21)
        bb_position = classify_bb_position(price, ema21)
        sr = calc_support_resistance(price, bb_width, ema21)

        passes = best_cal >= prediction_threshold

        entry = {
            "symbol": sym,
            "price": price,
            "change_24h": data.get("change_24h", 0),
            "direction": best_dir,
            "signal": best_signal,
            "raw_confidence": best_raw,
            "calibrated_confidence": best_cal,
            "passes_threshold": passes,
            "tier": "TIER1" if sym in TIER1 else "TIER2",
            "rsi_4h": rsi_4h,
            "rsi_signal": rsi_signal,
            "macd_hist": macd_hist,
            "macd_signal": macd_signal,
            "bb_width_4h": bb_width,
            "bb_squeeze_4h": bb_squeeze_4h,
            "bb_squeeze_1h": bb_squeeze_1h,
            "bb_position": bb_position,
                "support_resistance": sr,
            "ema9": ema9,
            "ema21": ema21,
            "ema_alignment": ema_align,
            "vol_ratio": vol_ratio,
            "patterns": pattern_names,
        }

        if passes:
            candidates.append(entry)
        else:
            watch_list.append(entry)

    # Sort: tier1 first, then by calibrated score
    candidates.sort(key=lambda x: (0 if x["tier"] == "TIER1" else 1, -x["calibrated_confidence"]))

    # Force top-2 if zero natural predictions
    forced_count = 0
    if len(candidates) == 0:
        all_sorted = sorted(watch_list, key=lambda x: -x["calibrated_confidence"])
        for entry in all_sorted[:2]:
            entry["forced"] = True
            entry["passes_threshold"] = True
            candidates.append(entry)
            forced_count += 1

    # Generate prediction entries
    new_predictions = []
    for entry in candidates:
        sym = entry["symbol"]
        price = entry["price"]
        direction = entry["direction"]

        if direction == "BEARISH":
            supports = entry["support_resistance"]["support"]
            target = supports[0] if supports else price * 0.97
            resistances = entry["support_resistance"]["resistance"]
            invalidation = resistances[-1] if resistances else price * 1.03
        else:
            resistances = entry["support_resistance"]["resistance"]
            target = resistances[0] if resistances else price * 1.03
            supports = entry["support_resistance"]["support"]
            invalidation = supports[-1] if supports else price * 0.97

        pred_id = make_pred_id(sym, ts_str)
        is_forced = entry.get("forced", False)

        pred_entry = {
            "prediction_id": pred_id,
            "symbol": sym,
            "timestamp": ts_iso,
            "model_used": "hermes-agent",
            "market_context": {
                "price": price,
                "change_24h": entry["change_24h"],
                "fear_greed": fear_greed,
                "fear_greed_label": "Extreme Fear" if fear_greed < 25 else "Fear" if fear_greed < 45 else "Neutral",
            },
            "prediction": {
                "direction": direction,
                "signal": entry["signal"],
                "target_price": target,
                "invalidation_price": invalidation,
                "timeframe": "4H",
                "confidence_raw": entry["raw_confidence"],
                "confidence": entry["calibrated_confidence"],
                "tier": cal_tier,
                "forced": is_forced,
            },
            "support_resistance": entry["support_resistance"],
            "indicators": {
                "rsi": {"value": entry["rsi_4h"], "signal": entry["rsi_signal"]},
                "macd": {"signal": entry["macd_signal"], "hist": entry["macd_hist"]},
                "bb": {"width": entry["bb_width_4h"], "squeeze": entry["bb_squeeze_4h"], "position": entry["bb_position"]},
                "ema": {"cross": "BEARISH" if "BEAR" in entry["ema_alignment"] else "BULLISH", "alignment": entry["ema_alignment"]},
            },
            "patterns": entry["patterns"],
            "status": "PREDICTED",
        }

        new_predictions.append(pred_entry)

    # Save updated registry
    registry["predictions"].extend(new_predictions)
    registry["last_updated"] = ts_iso
    registry["total_predictions"] = len(registry["predictions"])
    registry["pending_predictions"] = sum(1 for p in registry["predictions"] if p.get("status") == "PREDICTED")

    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)

    # Build output
    avg_cal = (sum(p["prediction"]["confidence"] for p in new_predictions) / len(new_predictions)) if new_predictions else 0

    result = {
        "timestamp": ts_iso,
        "snapshot_age_min": round(age_min),
        "portfolio": {
            "total_equity": portfolio.get("equity", 0),
            "positions": len(positions),
            "fear_greed": fear_greed,
        },
        "calibration": {
            "accuracy": round(recalc_accuracy, 4),
            "correct": correct_count,
            "total_verified": total_verified,
            "cal_mult": cal_mult,
            "tier": cal_tier,
            "threshold": prediction_threshold,
        },
        "predictions": [],
        "watch_list": [],
        "forced_count": forced_count,
        "avg_confidence": round(avg_cal),
    }

    for p in new_predictions:
        result["predictions"].append({
            "symbol": p["symbol"],
            "price": p["market_context"]["price"],
            "direction": p["prediction"]["direction"],
            "signal": p["prediction"]["signal"],
            "target": p["prediction"]["target_price"],
            "invalidation": p["prediction"]["invalidation_price"],
            "confidence_raw": p["prediction"]["confidence_raw"],
            "confidence_calibrated": p["prediction"]["confidence"],
            "forced": p["prediction"].get("forced", False),
            "prediction_id": p["prediction_id"],
            "rsi_4h": p["indicators"]["rsi"]["value"],
            "rsi_signal": p["indicators"]["rsi"]["signal"],
            "macd_signal": p["indicators"]["macd"]["signal"],
            "bb_position": p["indicators"]["bb"]["position"],
            "bb_squeeze": p["indicators"]["bb"]["squeeze"],
            "ema_alignment": p["indicators"]["ema"]["alignment"],
            "tier": "TIER1" if p["symbol"] in TIER1 else "TIER2",
        })

    predicted_syms = {p["symbol"] for p in new_predictions}
    for w in watch_list:
        if w["symbol"] not in predicted_syms:
            result["watch_list"].append({
                "symbol": w["symbol"],
                "price": w["price"],
                "rsi_4h": w["rsi_4h"],
                "bullish_cal": w["bullish_cal"] if "bullish_cal" in w else "",
                "bearish_cal": w["bearish_cal"] if "bearish_cal" in w else "",
                "reason": f"Both directions below {prediction_threshold} threshold",
            })

    # Registry summary
    all_preds = registry.get("predictions", [])
    status_counts = {}
    for p in all_preds:
        s = p.get("status", "UNKNOWN")
        status_counts[s] = status_counts.get(s, 0) + 1
    result["registry_summary"] = {
        "total": len(all_preds),
        "predicted": status_counts.get("PREDICTED", 0),
        "verified": sum(1 for p in all_preds if ((p.get("verification") or {}).get("result") in ("SUCCESS", "PARTIAL_SUCCESS", "FAILURE"))),
        "expired": status_counts.get("EXPIRED", 0),
    }

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()