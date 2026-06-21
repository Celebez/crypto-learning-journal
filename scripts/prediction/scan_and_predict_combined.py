#!/usr/bin/env python3
"""
Combined cronjob: fetch market data -> detect patterns -> predict -> verify old -> learn.
Single script to avoid multiple terminal calls and pipe-to-interpreter security flags.

Usage:
  cd ~ && PYTHONPATH=~ ~/.hermes-venv/bin/python3 /tmp/scan_and_predict.py > /tmp/scan_result.json

Output: JSON to stdout with sections: portfolio, positions, ticker_data, analysis,
        verification_results, new_predictions, registry_summary

Key behaviors:
- Fetches 4H klines for 8 assets (BTC, ETH, SOL, XRP, ADA, LINK, DOGE, AVAX)
- Calculates EMA(9/21/50), RSI(14), BB(20,2), MACD(12,26,9), ATR(14)
- Detects patterns: BB_SQUEEZE, RSI_OVERSOLD/OVERBOUGHT, VOLUME_EXPANSION, MACD_CROSS
- Classifies MACD properly (BULLISH_CROSS vs BULLISH_RECOVERY)
- Verifies old predictions against current prices (with MIN_VERIFY_AGE_HOURS=2)
- Generates new predictions with confidence calibration
- Prunes stale predictions (expires all PREDICTED entries, cleans EXPIRED >7 days)
- Saves updated registry to prediction_registry.json

v3.39 (2026-06-05): Added MIN_VERIFY_AGE_HOURS=2 check before verification.
  Also added sanity check: BEARISH target must be below entry price, BULLISH target above.
  Without these, same-cycle predictions get trivially verified as SUCCESS, inflating accuracy.

v3.41 (2026-06-05): Fixed NameError: new_accuracy — added accuracy recalculation from
  registry after load. Counts verified predictions (SUCCESS/PARTIAL_SUCCESS/FAILURE),
  calculates correct/total, updates calibration_multiplier from recalculated accuracy.
"""
import sys, json, math, os, hashlib, datetime

sys.path.insert(0, os.path.expanduser("~"))
from hermes_bybit_bridge import session, get_balance, get_positions

TRACKED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]
MIN_VERIFY_AGE_HOURS = 2  # Do NOT verify predictions younger than this
EXPIRED_CLEANUP_DAYS = 7  # Remove EXPIRED entries older than this

# -- Indicator Functions --
def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return ema

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_bollinger(closes, period=20, std_dev=2):
    if len(closes) < period:
        return None, None, None, None
    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((x - sma) ** 2 for x in recent) / period
    std = math.sqrt(variance)
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    width = (upper - lower) / sma if sma > 0 else 0
    return upper, lower, sma, width

def calc_macd(closes):
    if len(closes) < 26:
        return 0, 0, 0
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd_line = ema12 - ema26
    macd_vals = []
    for i in range(26, len(closes) + 1):
        e12 = calc_ema(closes[:i], 12)
        e26 = calc_ema(closes[:i], 26)
        macd_vals.append(e12 - e26)
    signal = calc_ema(macd_vals, 9) if len(macd_vals) >= 9 else macd_line
    histogram = macd_line - signal
    return macd_line, signal, histogram

def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    atr = sum(trs[:period]) / period
    for t in trs[period:]:
        atr = (atr * (period - 1) + t) / period
    return atr

def classify_macd(macd_line, macd_signal, macd_hist, prev_hist=None):
    if prev_hist is not None:
        if prev_hist <= 0 and macd_hist > 0:
            return "BULLISH_CROSS"
        elif prev_hist >= 0 and macd_hist < 0:
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

def classify_rsi(rsi):
    if rsi > 70: return "OVERBOUGHT"
    elif rsi < 30: return "OVERSOLD"
    elif rsi > 55: return "BULLISH"
    elif rsi < 45: return "BEARISH"
    else: return "NEUTRAL"

def classify_bb_position(price, bb_upper, bb_lower, bb_mid):
    if price > bb_upper: return "ABOVE_UPPER"
    elif price < bb_lower: return "BELOW_LOWER"
    elif price > bb_mid: return "UPPER_HALF"
    elif price < bb_mid: return "LOWER_HALF"
    else: return "MIDDLE"

def gen_id(symbol, ts):
    h = hashlib.md5(f"{symbol}{ts}".encode()).hexdigest()[:4].upper()
    return f"PRED-{symbol}-{ts}-{h}"

# -- Load Thresholds --
DEFAULT_THRESHOLDS = {
    "BTCUSDT": {"bb_squeeze": 0.02, "rsi_oversold": 32, "rsi_overbought": 68, "vol_spike": 1.8},
    "ETHUSDT": {"bb_squeeze": 0.025, "rsi_oversold": 30, "rsi_overbought": 70, "vol_spike": 2.0},
    "SOLUSDT": {"bb_squeeze": 0.03, "rsi_oversold": 30, "rsi_overbought": 70, "vol_spike": 2.0},
    "XRPUSDT": {"bb_squeeze": 0.025, "rsi_oversold": 30, "rsi_overbought": 70, "vol_spike": 2.0},
    "ADAUSDT": {"bb_squeeze": 0.03, "rsi_oversold": 28, "rsi_overbought": 72, "vol_spike": 2.2},
    "LINKUSDT": {"bb_squeeze": 0.03, "rsi_oversold": 30, "rsi_overbought": 70, "vol_spike": 2.0},
    "DOGEUSDT": {"bb_squeeze": 0.035, "rsi_oversold": 28, "rsi_overbought": 72, "vol_spike": 2.5},
    "AVAXUSDT": {"bb_squeeze": 0.03, "rsi_oversold": 30, "rsi_overbought": 70, "vol_spike": 2.2},
}
try:
    with open(os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning/references/adaptive_thresholds.json")) as f:
        THRESHOLDS = json.load(f)
except Exception:
    THRESHOLDS = DEFAULT_THRESHOLDS

# -- Load Calibration Multiplier --
try:
    with open(os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/learning_weights.json")) as f:
        lw = json.load(f)
        calibration_multiplier = lw.get("calibration_multiplier", 1.0)
except Exception:
    calibration_multiplier = 1.0

# -- Load Prediction Registry --
reg_path = os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/prediction_registry.json")
try:
    with open(reg_path) as f:
        registry = json.load(f)
except Exception:
    registry = {"predictions": [], "summary": {"total": 0, "pending": 0, "verified": 0, "expired": 0}}

# -- Recalculate accuracy from verified predictions (exclude EXPIRED) --
# Without this, calibration_multiplier from disk may be stale or in death spiral.
# Recalculate from registry to get fresh accuracy before generating predictions.
all_verified = [p for p in registry["predictions"]
                if (p.get("verification") or {}).get("result") in
                ("SUCCESS", "PARTIAL_SUCCESS", "FAILURE")]
verified_preds = all_verified
correct_preds = [p for p in all_verified
                 if (p.get("verification") or {}).get("result") in
                 ("SUCCESS", "PARTIAL_SUCCESS")]
new_accuracy = len(correct_preds) / len(verified_preds) if verified_preds else 0.5

# Update calibration multiplier based on recalculated accuracy
if new_accuracy > 0.80:
    calibration_multiplier = 1.0
elif new_accuracy > 0.60:
    calibration_multiplier = 0.85
elif new_accuracy > 0.40:
    calibration_multiplier = 0.7
else:
    calibration_multiplier = 0.5

# -- Portfolio --
balance = get_balance()
positions = get_positions()
total_pnl = sum(float(p.get("pnl", 0)) for p in positions)
equity = balance.get("equity", 0)
portfolio = {
    "equity": round(equity, 2),
    "balance": round(balance.get("balance", 0), 2),
    "available": round(balance.get("available", 0), 2),
    "total_pnl": round(total_pnl, 2),
    "pnl_pct": round((total_pnl / equity * 100) if equity > 0 else 0, 2),
    "positions_count": len(positions),
}

# -- Fetch Tickers + Analysis --
now = datetime.datetime.now(datetime.timezone.utc)
ts = now.strftime("%Y%m%d%H%M%S")
analysis = {}
ticker_data = {}

for sym in TRACKED:
    try:
        t = session.get_tickers(category="linear", symbol=sym)
        info = t["result"]["list"][0]
        ticker_data[sym] = {
            "lastPrice": info.get("lastPrice"),
            "volume24h": info.get("volume24h"),
            "turnover24h": info.get("turnover24h"),
            "highPrice24h": info.get("highPrice24h"),
            "lowPrice24h": info.get("lowPrice24h"),
            "fundingRate": info.get("fundingRate"),
            "openInterest": info.get("openInterest"),
            "price24hPcnt": info.get("price24hPcnt"),
        }

        kl = session.get_kline(category="linear", symbol=sym, interval="240", limit=50)
        candles = list(reversed(kl["result"]["list"]))
        closes = [float(c[4]) for c in candles]
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]
        volumes = [float(c[5]) for c in candles]

        price = closes[-1]
        ema9 = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)
        ema50 = calc_ema(closes, 50) if len(closes) >= 50 else calc_ema(closes, len(closes))
        rsi = calc_rsi(closes)
        bb_upper, bb_lower, bb_mid, bb_width = calc_bollinger(closes)
        macd_line, macd_signal, macd_hist = calc_macd(closes)
        atr = calc_atr(highs, lows, closes)

        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1

        ema_alignment = "BULLISH" if ema9 > ema21 > ema50 else "BEARISH" if ema9 < ema21 < ema50 else "MIXED"

        try:
            prev_closes = closes[:-1]
            _, _, prev_hist = calc_macd(prev_closes)
        except Exception:
            prev_hist = None

        patterns = []
        th = THRESHOLDS.get(sym, DEFAULT_THRESHOLDS.get(sym, DEFAULT_THRESHOLDS["BTCUSDT"]))
        if bb_width is not None and bb_width < th["bb_squeeze"]:
            patterns.append("BB_SQUEEZE")
        if rsi < th["rsi_oversold"]:
            patterns.append("RSI_OVERSOLD")
        elif rsi > th["rsi_overbought"]:
            patterns.append("RSI_OVERBOUGHT")
        if vol_ratio > th["vol_spike"]:
            patterns.append("VOLUME_EXPANSION")
        macd_sig = classify_macd(macd_line, macd_signal, macd_hist, prev_hist)
        if macd_sig == "BULLISH_CROSS":
            patterns.append("MACD_BULLISH_CROSS")
        elif macd_sig == "BEARISH_CROSS":
            patterns.append("MACD_BEARISH_CROSS")

        recent_high = max(highs[-5:])
        recent_low = min(lows[-5:])
        if price > recent_high * 0.998:
            market_structure = "BREAKOUT_HIGH"
        elif price < recent_low * 1.002:
            market_structure = "BREAKDOWN_LOW"
        elif ema_alignment == "BULLISH":
            market_structure = "HIGHER_HL"
        elif ema_alignment == "BEARISH":
            market_structure = "LOWER_LH"
        else:
            market_structure = "RANGING"

        analysis[sym] = {
            "price": price,
            "ema9": round(ema9, 6), "ema21": round(ema21, 6), "ema50": round(ema50, 6),
            "ema_alignment": ema_alignment,
            "rsi": round(rsi, 2),
            "bb_upper": round(bb_upper, 6) if bb_upper else None,
            "bb_lower": round(bb_lower, 6) if bb_lower else None,
            "bb_mid": round(bb_mid, 6) if bb_mid else None,
            "bb_width": round(bb_width, 6) if bb_width else None,
            "macd_line": round(macd_line, 6),
            "macd_signal": round(macd_signal, 6),
            "macd_hist": round(macd_hist, 6),
            "atr": round(atr, 6),
            "atr_pct": round((atr / price * 100) if price > 0 else 0, 2),
            "vol_ratio": round(vol_ratio, 2),
            "patterns": patterns,
            "market_structure": market_structure,
            "macd_signal_class": macd_sig,
        }
    except Exception as e:
        analysis[sym] = {"error": str(e)}

# -- VERIFY OLD PREDICTIONS --
# CRITICAL: MIN_VERIFY_AGE_HOURS = 2 — do NOT verify predictions younger than this.
# Without this check, same-cycle predictions get verified as SUCCESS instantly,
# inflating accuracy and breaking the learning loop. (Bug documented v3.34)
verification_results = []
for pred in registry["predictions"]:
    if pred.get("status") != "PREDICTED":
        continue
    sym = pred["symbol"]
    if sym not in analysis or "error" in analysis[sym]:
        continue

    # Check minimum age before verification
    try:
        pred_time = datetime.datetime.fromisoformat(pred["timestamp"].replace("Z", "+00:00"))
        age_hours = (now - pred_time).total_seconds() / 3600
        if age_hours < MIN_VERIFY_AGE_HOURS:
            continue  # Too young — skip verification, leave as PREDICTED
    except Exception:
        continue  # Can't parse timestamp — skip

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

    # Sanity check: BEARISH target must be BELOW entry price, BULLISH target ABOVE
    entry_price = pred.get("market_context", {}).get("price", current_price)
    if direction == "BEARISH" and target >= entry_price:
        continue  # Target set above entry — invalid prediction, skip verification
    if direction == "BULLISH" and target <= entry_price:
        continue  # Target set below entry — invalid prediction, skip verification

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

    # Expire after 48h if still PREDICTED
    try:
        if (now - pred_time).total_seconds() > 48 * 3600 and pred.get("status") == "PREDICTED":
            pred["status"] = "EXPIRED"
            pred["verification"] = {"result": "EXPIRED", "reason": "Time expired (48h)"}
    except Exception:
        pass
    verification_results.append({"id": pred["prediction_id"], "symbol": sym, "status": pred.get("status", "PREDICTED")})

# -- PRUNE STALE PREDICTIONS --
# CRITICAL: Expire ALL PREDICTED entries, not just keep newest 8.
for pred in registry["predictions"]:
    if pred.get("status") == "PREDICTED":
        pred["status"] = "EXPIRED"
        pred["verification"] = {"result": "EXPIRED", "reason": "Pruned: replaced by newer predictions"}

# -- CLEANUP EXPIRED ENTRIES (>7 days old) --
cutoff = now - datetime.timedelta(days=EXPIRED_CLEANUP_DAYS)
kept_expired = []
removed_count = 0
for pred in registry["predictions"]:
    if pred.get("status") == "EXPIRED":
        try:
            pred_time = datetime.datetime.fromisoformat(pred["timestamp"].replace("Z", "+00:00"))
            if pred_time < cutoff:
                removed_count += 1
                continue  # Remove old EXPIRED
        except Exception:
            pass
    kept_expired.append(pred)
# Keep at most 50 most recent EXPIRED as rolling buffer
expired_entries = [p for p in kept_expired if p.get("status") == "EXPIRED"]
non_expired = [p for p in kept_expired if p.get("status") != "EXPIRED"]
if len(expired_entries) > 50:
    expired_entries = expired_entries[-50:]
registry["predictions"] = non_expired + expired_entries

# -- GENERATE NEW PREDICTIONS --
new_predictions = []
for sym, data in analysis.items():
    if "error" in data:
        continue
    price = data["price"]
    ema_a = data["ema_alignment"]
    rsi = data["rsi"]
    macd_hist = data["macd_hist"]
    macd_line = data["macd_line"]
    macd_signal_val = data["macd_signal"]
    bb_upper = data["bb_upper"]
    bb_lower = data["bb_lower"]
    bb_mid = data["bb_mid"]
    atr = data["atr"]
    vol_ratio = data["vol_ratio"]
    patterns = data["patterns"]
    ms = data["market_structure"]

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
        direction = "BULLISH"
        # Target must be ABOVE current price for BULLISH
        target = bb_upper if bb_upper and bb_upper > price else price + atr * 1.5
        invalidation = bb_lower if bb_lower and bb_lower < price else price - atr * 1.0
    elif net <= -2:
        direction = "BEARISH"
        # Target must be BELOW current price for BEARISH
        target = bb_lower if bb_lower and bb_lower < price else price - atr * 1.5
        invalidation = bb_upper if bb_upper and bb_upper > price else price + atr * 1.0
    else:
        direction = "NEUTRAL"
        target = bb_upper if bb_upper else price * 1.02
        invalidation = bb_lower if bb_lower else price * 0.98

    conf = 50
    if "BB_SQUEEZE" in patterns: conf += 15
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

    if direction == "BULLISH":
        resistance = [bb_upper, round(bb_upper + atr * 0.5, 4)] if bb_upper else [price * 1.02]
        support = [bb_mid, round(bb_lower, 4)] if bb_lower else [price * 0.98]
    elif direction == "BEARISH":
        resistance = [bb_upper, round(bb_upper + atr * 0.5, 4)] if bb_upper else [price * 1.02]
        support = [bb_lower, round(bb_lower - atr * 0.5, 4)] if bb_lower else [price * 0.98]
    else:
        resistance = [bb_upper] if bb_upper else [price * 1.02]
        support = [bb_lower] if bb_lower else [price * 0.98]

    if price > 1000:
        target, invalidation = round(target, 1), round(invalidation, 1)
        resistance = [round(r, 1) for r in resistance]
        support = [round(s, 1) for s in support]
    elif price > 10:
        target, invalidation = round(target, 2), round(invalidation, 2)
        resistance = [round(r, 2) for r in resistance]
        support = [round(s, 2) for s in support]
    elif price > 1:
        target, invalidation = round(target, 4), round(invalidation, 4)
        resistance = [round(r, 4) for r in resistance]
        support = [round(s, 4) for s in support]
    else:
        target, invalidation = round(target, 5), round(invalidation, 5)
        resistance = [round(r, 5) for r in resistance]
        support = [round(s, 5) for s in support]

    bb_pos = classify_bb_position(price, bb_upper, bb_lower, bb_mid)

    new_predictions.append({
        "prediction_id": gen_id(sym, ts),
        "timestamp": now.isoformat(),
        "symbol": sym,
        "direction": direction,
        "target_price": target,
        "invalidation_price": invalidation,
        "timeframe": "4H",
        "confidence": calibrated,
        "confidence_tier": tier,
        "market_context": {"price": price, "daily_trend": ema_a, "ema_alignment": ema_a},
        "indicators": {"rsi": rsi, "macd_hist": macd_hist, "bb_position": bb_pos, "macd_signal": data["macd_signal"]},
        "support_resistance": {"resistance": resistance, "support": support},
        "patterns_detected": patterns,
        "market_structure": ms,
        "status": "PREDICTED"
    })

# -- UPDATE REGISTRY --
registry["predictions"].extend(new_predictions)
registry["last_updated"] = now.isoformat()
pending = len([p for p in registry["predictions"] if p.get("status") == "PREDICTED"])
success = len([p for p in registry["predictions"] if p.get("status") == "SUCCESS"])
failure = len([p for p in registry["predictions"] if p.get("status") == "FAILURE"])
partial = len([p for p in registry["predictions"] if p.get("status") == "PARTIAL"])
expired = len([p for p in registry["predictions"] if p.get("status") == "EXPIRED"])
registry["summary"] = {"total": len(registry["predictions"]), "pending": pending, "success": success, "partial_success": partial, "failure": failure, "expired": expired}

os.makedirs(os.path.dirname(reg_path), exist_ok=True)
with open(reg_path, "w") as f:
    json.dump(registry, f, indent=2)

# -- PERSIST RECALCULATED ACCURACY TO LEARNING WEIGHTS --
# Without this, learning_weights.json on disk (and synced to Redis/SB) has stale accuracy.
# The combined script recalculates at startup for local use, but must also write back.
lw_path = os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/learning_weights.json")
try:
    with open(lw_path) as f:
        lw = json.load(f)
except Exception:
    lw = {}
lw["accuracy_rate"] = new_accuracy
lw["calibration_multiplier"] = calibration_multiplier
lw["calibration_tier"] = "HIGH" if new_accuracy > 0.8 else "MEDIUM" if new_accuracy > 0.6 else "LOW" if new_accuracy > 0.4 else "UNRELIABLE"
lw["verified_predictions"] = len(verified_preds)
lw["correct_predictions"] = len(correct_preds)
lw["total_predictions"] = len(registry["predictions"])
lw["pending_predictions"] = pending
lw["last_updated"] = now.isoformat()
os.makedirs(os.path.dirname(lw_path), exist_ok=True)
with open(lw_path, "w") as f:
    json.dump(lw, f, indent=2)

# -- OUTPUT --
result = {
    "timestamp": now.isoformat(),
    "portfolio": portfolio,
    "positions": positions,
    "ticker_data": ticker_data,
    "analysis": analysis,
    "verification_results": verification_results,
    "new_predictions": new_predictions,
    "registry_summary": registry["summary"],
    "calibration_multiplier": calibration_multiplier,
    "expired_removed": removed_count,
    "accuracy_recalculated": round(new_accuracy, 4),
}

print(json.dumps(result, indent=2))
