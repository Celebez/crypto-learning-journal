#!/usr/bin/env python3
"""
Pattern detection and indicator calculation for all tracked assets.
Uses direct import from hermes_bybit_bridge for reliable data fetching.

Indicator calculations: EMA (9/21/50), RSI (14), Bollinger Bands (20,2), MACD (12,26,9), ATR (14)
Pattern detection: BB Squeeze, EMA Cross, RSI Overbought/Oversold, Volume Expansion, MACD Cross
Adaptive thresholds: per-asset from references/adaptive_thresholds.json

Usage:
  cd /home/ubuntu && /home/ubuntu/.hermes-venv/bin/python3 \
    ~/.hermes/skills/trading/crypto_portfolio_monitor_learning/scripts/pattern_detect.py

Output: JSON with portfolio state and per-asset analysis including detected patterns.
"""
import sys, json, math, os
sys.path.insert(0, "/home/ubuntu")

from hermes_bybit_bridge import session, get_balance, get_positions

TRACKED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]

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

# Load adaptive thresholds (fallback to defaults)
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

# Try loading from skill reference
try:
    threshold_path = os.path.expanduser(
        "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/references/adaptive_thresholds.json"
    )
    with open(threshold_path) as f:
        THRESHOLDS = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    THRESHOLDS = DEFAULT_THRESHOLDS

results = {}

for sym in TRACKED:
    try:
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

        # EMA Cross
        ema9_prev = calc_ema(closes[:-1], 9)
        ema21_prev = calc_ema(closes[:-1], 21)
        ema_cross = None
        if ema9_prev <= ema21_prev and ema9 > ema21:
            ema_cross = "BULLISH_CROSS"
        elif ema9_prev >= ema21_prev and ema9 < ema21:
            ema_cross = "BEARISH_CROSS"

        ema_alignment = "BULLISH" if ema9 > ema21 > ema50 else "BEARISH" if ema9 < ema21 < ema50 else "MIXED"

        # Pattern detection
        patterns = []
        th = THRESHOLDS.get(sym, DEFAULT_THRESHOLDS.get(sym, DEFAULT_THRESHOLDS["BTCUSDT"]))

        if bb_width is not None and bb_width < th["bb_squeeze"]:
            patterns.append({"name": "BB_SQUEEZE", "details": f"BB width {bb_width:.4f} < {th['bb_squeeze']}", "timeframe": "4H"})
        if rsi < th["rsi_oversold"]:
            patterns.append({"name": "RSI_OVERSOLD", "details": f"RSI {rsi:.1f} < {th['rsi_oversold']}", "timeframe": "4H"})
        elif rsi > th["rsi_overbought"]:
            patterns.append({"name": "RSI_OVERBOUGHT", "details": f"RSI {rsi:.1f} > {th['rsi_overbought']}", "timeframe": "4H"})
        if ema_cross:
            patterns.append({"name": ema_cross, "details": f"EMA9({ema9:.4f}) x EMA21({ema21:.4f})", "timeframe": "4H"})
        if vol_ratio > th["vol_spike"]:
            patterns.append({"name": "VOLUME_EXPANSION", "details": f"Vol ratio {vol_ratio:.2f}x avg", "timeframe": "4H"})

        # MACD Cross
        try:
            m_l, m_s, m_h = calc_macd(closes[:-1])
            if m_h < 0 and macd_hist > 0:
                patterns.append({"name": "MACD_BULLISH_CROSS", "details": f"MACD hist {macd_hist:.4f}", "timeframe": "4H"})
            elif m_h > 0 and macd_hist < 0:
                patterns.append({"name": "MACD_BEARISH_CROSS", "details": f"MACD hist {macd_hist:.4f}", "timeframe": "4H"})
        except Exception:
            pass

        # Market structure
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

        results[sym] = {
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
        }
    except Exception as e:
        results[sym] = {"error": str(e)}

# Portfolio
balance = get_balance()
positions = get_positions()
total_pnl = sum(float(p.get("pnl", 0)) for p in positions)
equity = balance.get("equity", 0)

print(json.dumps({
    "portfolio": {
        "equity": round(equity, 2),
        "balance": round(balance.get("balance", 0), 2),
        "available": round(balance.get("available", 0), 2),
        "total_pnl": round(total_pnl, 2),
        "pnl_pct": round((total_pnl / equity * 100) if equity > 0 else 0, 2),
        "positions_count": len(positions),
    },
    "positions": positions,
    "analysis": results,
}, indent=2))
