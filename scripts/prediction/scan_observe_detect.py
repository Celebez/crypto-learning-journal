#!/usr/bin/env python3
"""
OBSERVE & DETECT: Lightweight 15-minute scan script.
Fetches prices, calculates indicators (EMA, RSI, BB, MACD), detects patterns,
fetches 1H volume for ratio analysis, fear & greed index, fetches portfolio.
Does NOT update prediction registry (use scan_and_predict_combined.py for that).

Usage:
  cd /home/ubuntu && /home/ubuntu/.hermes-venv/bin/python3 /tmp/scan_observe_detect.py

Output: JSON to stdout with sections: portfolio, positions, analysis, patterns_detected, fear_greed
"""
import sys, json, math, os
from datetime import datetime, timezone

sys.path.insert(0, "/home/ubuntu")
import importlib.util
import os

# Dynamically load the bridge module to avoid ModuleNotFoundError
bridge_path = os.path.expanduser("~/hermes_bybit_bridge.py")
spec = importlib.util.spec_from_file_location("hermes_bybit_bridge", bridge_path)
bridge_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_module)

get_price = bridge_module.get_price
get_positions = bridge_module.get_positions
get_balance = bridge_module.get_balance

TRACKED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]

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

def calc_macd(closes, fast=12, slow=26, signal_period=9):
    """Calculate MACD line, signal line, and histogram.
    Returns (macd_line, signal, histogram).
    Uses simplified signal line: EMA of recent MACD values."""
    if len(closes) < slow + signal_period:
        return 0, 0, 0
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    macd_line = ema_fast - ema_slow
    # Simplified signal line using recent macd values
    macd_vals = []
    for i in range(signal_period):
        idx = len(closes) - i
        if idx >= slow:
            ef = calc_ema(closes[:idx], fast)
            es = calc_ema(closes[:idx], slow)
            macd_vals.append(ef - es)
    if len(macd_vals) >= signal_period:
        signal = sum(macd_vals) / len(macd_vals)
    else:
        signal = macd_line
    hist = macd_line - signal
    return macd_line, signal, hist

def classify_macd(macd_line, signal, hist):
    """Classify MACD signal. Distinguishes CROSS from RECOVERY.
    BULLISH_CROSS: histogram just turned positive (actual cross event)
    BULLISH_RECOVERY: histogram positive but line still below signal
    BULLISH: line above signal, histogram positive and growing
    Same for bearish variants."""
    if macd_line > signal and hist > 0:
        return "BULLISH"
    elif macd_line < signal and hist < 0:
        return "BEARISH"
    elif hist > 0 and macd_line < 0:
        return "BULLISH_RECOVERY"
    elif hist < 0 and macd_line > 0:
        return "BEARISH_RECOVERY"
    return "NEUTRAL"

def classify_rsi(rsi, th):
    """Classify RSI using per-asset thresholds."""
    if rsi > th.get("rsi_overbought", 70):
        return "OVERBOUGHT"
    elif rsi < th.get("rsi_oversold", 30):
        return "OVERSOLD"
    elif rsi > 55:
        return "BULLISH"
    elif rsi < 45:
        return "BEARISH"
    return "NEUTRAL"

def fetch_klines(symbol, interval="240", limit=50):
    """Fetch klines from Bybit v5 API. interval is numeric: 60=1H, 240=4H."""
    import requests
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            klines = list(reversed(data["result"]["list"]))
            closes = [float(c[4]) for c in klines]
            volumes = [float(c[5]) for c in klines]
            return closes, volumes
    except Exception:
        pass
    return [], []

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

# -- Fear & Greed Index --
fear_greed = None
try:
    import requests
    fg_resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
    fg_data = fg_resp.json()
    if fg_data.get("data"):
        fg_item = fg_data["data"][0]
        fear_greed = {
            "value": int(fg_item.get("value", 50)),
            "label": fg_item.get("value_classification", "Neutral"),
        }
except Exception:
    fear_greed = {"value": 50, "label": "Unknown"}

# -- Portfolio --
balance = get_balance()
positions = get_positions()

# Load previous snapshot for entry price fallback (avgPrice=0 is common)
prev_snapshot = {}
try:
    with open(os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/latest_snapshot.json")) as f:
        prev_snapshot = json.load(f)
except Exception:
    pass
prev_entries = {}
for p in prev_snapshot.get("positions", []):
    sym = p.get("symbol", "")
    avg = float(p.get("entry", 0) or p.get("avgPrice", 0))
    if sym and avg > 0:
        prev_entries[sym] = avg

total_pnl = 0
positions_data = []
for p in positions:
    sym = p.get("symbol", "")
    entry = float(p.get("avgPrice", 0))
    if entry == 0 and sym in prev_entries:
        entry = prev_entries[sym]
    qty = float(p.get("size", 0))
    side = p.get("side", "")
    unrealised_pnl = float(p.get("unrealisedPnl", 0))
    total_pnl += unrealised_pnl
    positions_data.append({
        "symbol": sym,
        "side": side,
        "entry": entry,
        "size": qty,
        "unrealised_pnl": round(unrealised_pnl, 2),
    })

equity = float(balance.get("equity", 0))
portfolio = {
    "equity": round(equity, 2),
    "balance": round(float(balance.get("balance", 0)), 2),
    "available": round(float(balance.get("available", 0)), 2),
    "total_pnl": round(total_pnl, 2),
    "pnl_pct": round((total_pnl / equity * 100) if equity > 0 else 0, 2),
    "positions_count": len(positions),
}

# -- Fetch Prices + Analysis --
now = datetime.now(timezone.utc).isoformat()
analysis = {}
patterns_detected = []

for sym in TRACKED:
    try:
        ticker = get_price(sym)
        price = ticker.get("last", 0)
        change_24h = ticker.get("change_24h", "0%")
        th = THRESHOLDS.get(sym, DEFAULT_THRESHOLDS.get("BTCUSDT"))

        # Fetch 4H klines for indicators
        closes_4h, volumes_4h = fetch_klines(sym, interval="240", limit=50)
        # Fetch 1H klines for volume analysis
        closes_1h, volumes_1h = fetch_klines(sym, interval="60", limit=50)

        result = {"price": price, "change_24h": change_24h}

        if closes_4h:
            ema9 = calc_ema(closes_4h, 9)
            ema21 = calc_ema(closes_4h, 21)
            ema50 = calc_ema(closes_4h, 50)
            rsi = calc_rsi(closes_4h)
            bb_upper, bb_lower, bb_mid, bb_width = calc_bollinger(closes_4h)
            macd_line, macd_signal, macd_hist = calc_macd(closes_4h)
            macd_class = classify_macd(macd_line, macd_signal, macd_hist)

            # Volume analysis (1H)
            avg_vol = sum(volumes_1h[-20:]) / 20 if len(volumes_1h) >= 20 else 1
            current_vol = volumes_1h[-1] if volumes_1h else 0
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1

            # EMA alignment
            if ema9 > ema21 > ema50:
                ema_alignment = "FULL_BULL"
            elif ema9 < ema21 < ema50:
                ema_alignment = "FULL_BEAR"
            else:
                ema_alignment = "MIXED"

            result.update({
                "ema9": round(ema9, 6),
                "ema21": round(ema21, 6),
                "ema50": round(ema50, 6),
                "ema_cross": "BULLISH" if ema9 > ema21 else "BEARISH",
                "ema_alignment": ema_alignment,
                "rsi": round(rsi, 2),
                "rsi_signal": classify_rsi(rsi, th),
                "bb_upper": round(bb_upper, 2) if bb_upper else None,
                "bb_lower": round(bb_lower, 2) if bb_lower else None,
                "bb_mid": round(bb_mid, 2) if bb_mid else None,
                "bb_width": round(bb_width, 4) if bb_width else None,
                "macd_line": round(macd_line, 4),
                "macd_signal": round(macd_signal, 4),
                "macd_hist": round(macd_hist, 4),
                "macd_signal_label": macd_class,
                "vol_ratio": round(vol_ratio, 2),
            })

            # Detect patterns
            patterns = []
            if bb_width is not None and bb_width < th.get("bb_squeeze", 0.02):
                patterns.append("BB_SQUEEZE")
            if rsi < th.get("rsi_oversold", 30):
                patterns.append("RSI_OVERSOLD")
            elif rsi > th.get("rsi_overbought", 70):
                patterns.append("RSI_OVERBOUGHT")
            if vol_ratio > th.get("vol_spike", 2.0):
                patterns.append("VOLUME_SPIKE")
            if ema_alignment == "FULL_BULL":
                patterns.append("EMA_BULL_ALIGN")
            elif ema_alignment == "FULL_BEAR":
                patterns.append("EMA_BEAR_ALIGN")
            if macd_class in ("BULLISH_CROSS", "BULLISH"):
                patterns.append("MACD_BULLISH")
            elif macd_class in ("BEARISH_CROSS", "BEARISH"):
                patterns.append("MACD_BEARISH")
            elif macd_class == "BULLISH_RECOVERY":
                patterns.append("MACD_RECOVERY")
            elif macd_class == "BEARISH_RECOVERY":
                patterns.append("MACD_FADE")

            result["patterns"] = patterns
            if patterns:
                patterns_detected.append({"symbol": sym, "patterns": patterns})
        else:
            result["error"] = "No kline data"

        analysis[sym] = result
    except Exception as e:
        analysis[sym] = {"error": str(e)}

# -- Output --
result = {
    "timestamp": now,
    "portfolio": portfolio,
    "positions": positions_data,
    "analysis": analysis,
    "patterns_detected": patterns_detected,
    "fear_greed": fear_greed,
}

print(json.dumps(result, indent=2))
