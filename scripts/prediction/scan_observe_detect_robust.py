#!/usr/bin/env python3
"""
15-minute OBSERVE & DETECT scan - ROBUST VERSION.
Suppresses deprecation warnings and handles stderr properly.

This version fixes the "stderr breaks JSON output" pitfall by:
1. Suppressing DeprecationWarning for datetime.utcnow()
2. Using timezone-aware datetime (datetime.now(datetime.UTC))
3. Designed to be run with: python3 scan_observe_detect_robust.py 2>/dev/null

Usage:
  cd ~ && ~/.hermes-venv/bin/python3 /tmp/scan_observe_detect_robust.py > /tmp/scan_result.json
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Suppress deprecation warnings that break JSON output
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Add home directory to path for hermes_bybit_bridge import
sys.path.insert(0, os.path.expanduser("~"))

try:
    from hermes_bybit_bridge import get_price, get_positions, get_balance, session
except ImportError as e:
    print(json.dumps({"error": f"Failed to import hermes_bybit_bridge: {e}"}))
    sys.exit(1)

import numpy as np

# Tracked assets
TRACKED_ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]
TIER1_ASSETS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "HYPEUSDT"]

# Default adaptive thresholds (fallback)
DEFAULT_THRESHOLDS = {
    "BTCUSDT": {"bb_squeeze_threshold": 0.02, "rsi_oversold": 32, "rsi_overbought": 68, "volume_spike_multiplier": 1.8},
    "ETHUSDT": {"bb_squeeze_threshold": 0.025, "rsi_oversold": 30, "rsi_overbought": 70, "volume_spike_multiplier": 2.0},
    "SOLUSDT": {"bb_squeeze_threshold": 0.03, "rsi_oversold": 28, "rsi_overbought": 72, "volume_spike_multiplier": 2.0},
    "XRPUSDT": {"bb_squeeze_threshold": 0.035, "rsi_oversold": 28, "rsi_overbought": 72, "volume_spike_multiplier": 2.2},
    "ADAUSDT": {"bb_squeeze_threshold": 0.04, "rsi_oversold": 26, "rsi_overbought": 74, "volume_spike_multiplier": 2.3},
    "LINKUSDT": {"bb_squeeze_threshold": 0.03, "rsi_oversold": 28, "rsi_overbought": 72, "volume_spike_multiplier": 2.0},
    "DOGEUSDT": {"bb_squeeze_threshold": 0.05, "rsi_oversold": 25, "rsi_overbought": 75, "volume_spike_multiplier": 2.5},
    "AVAXUSDT": {"bb_squeeze_threshold": 0.035, "rsi_oversold": 28, "rsi_overbought": 72, "volume_spike_multiplier": 2.1},
}

def load_adaptive_thresholds():
    """Load adaptive thresholds from skill references."""
    threshold_path = os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning/references/adaptive_thresholds.json")
    try:
        with open(threshold_path, "r") as f:
            data = json.load(f)
            # Merge with defaults for any missing assets
            merged = DEFAULT_THRESHOLDS.copy()
            merged.update(data)
            return merged
    except Exception:
        return DEFAULT_THRESHOLDS

def fetch_klines(symbol, interval, limit=200):
    """Fetch klines from Bybit API. Returns (closes, highs, lows, vols) or empty lists on failure."""
    try:
        resp = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
        if resp.get("retCode") != 0:
            return [], [], [], []
        klines = resp.get("result", resp)
        if not isinstance(klines, dict):
            return [], [], [], []
        data = klines.get("list", [])
        if not data:
            return [], [], [], []
        closes = [float(d[4]) for d in data]
        highs = [float(d[2]) for d in data]
        lows = [float(d[3]) for d in data]
        vols = [float(d[5]) for d in data]
        return closes, highs, lows, vols
    except Exception:
        return [], [], [], []

def ema(closes, period):
    """Calculate EMA."""
    if len(closes) < period:
        return closes[-1] if closes else 0.0
    arr = np.array(closes, dtype=float)
    ema_val = arr[-1]
    weight = 2 / (period + 1)
    for i in range(len(arr) - 2, -1, -1):
        ema_val = arr[i] * weight + ema_val * (1 - weight)
    return float(ema_val)

def rsi(closes, period=14):
    """Calculate RSI."""
    if len(closes) < period + 1:
        return 50.0
    arr = np.array(closes[-(period+1):], dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))

def bollinger_bands(closes, period=20):
    """Calculate Bollinger Bands."""
    if len(closes) < period:
        return {"width": 0.1, "squeeze": False, "upper": 0, "lower": 0, "position": "UNKNOWN"}
    arr = np.array(closes[-period:], dtype=float)
    sma = float(np.mean(arr))
    std = float(np.std(arr))
    upper = sma + 2 * std
    lower = sma - 2 * std
    width = (upper - lower) / sma if sma > 0 else 0.1
    last_price = closes[-1] if closes else sma
    if last_price > upper:
        position = "ABOVE_UPPER"
    elif last_price < lower:
        position = "BELOW_LOWER"
    elif last_price > sma:
        position = "UPPER_HALF"
    else:
        position = "LOWER_HALF"
    squeeze = bool(width < 0.02)
    return {"width": float(width), "squeeze": squeeze, "upper": float(upper), "lower": float(lower), "position": position}

def macd(closes, fast=12, slow=26, signal_period=9):
    """Calculate MACD."""
    if len(closes) < slow + signal_period:
        return {"line": 0, "signal": 0, "hist": 0, "cross": "NEUTRAL", "direction": "NEUTRAL"}
    arr = np.array(closes, dtype=float)
    ema_fast = ema(arr.tolist(), fast)
    ema_slow = ema(arr.tolist(), slow)
    line = ema_fast - ema_slow
    # Simplified signal line (use same EMA on line)
    line_history = []
    for i in range(len(arr) - slow):
        ef = ema(arr[i:].tolist(), fast)
        es = ema(arr[i:].tolist(), slow)
        line_history.append(ef - es)
    if len(line_history) < signal_period:
        signal = line
    else:
        signal = np.mean(line_history[-signal_period:])
    hist = line - signal
    if hist > 0.001:
        direction = "BULLISH"
    elif hist < -0.001:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    return {"line": float(line), "signal": float(signal), "hist": float(hist), "direction": direction}

def detect_patterns(symbol, indicators, thresholds):
    """Detect trading patterns based on indicators."""
    patterns = []
    th = thresholds.get(symbol, DEFAULT_THRESHOLDS.get(symbol, DEFAULT_THRESHOLDS["BTCUSDT"]))
    bb_4h = indicators.get("bb_4h", {})
    bb_1h = indicators.get("bb_1h", {})
    rsi_4h = indicators.get("rsi_4h", 50)
    rsi_1h = indicators.get("rsi_1h", 50)
    vol_ratio = indicators.get("vol_ratio", 1.0)
    oi_change = indicators.get("oi_change", 0)
    taker_ratio = indicators.get("taker_ratio", 0.5)
    ema_alignment = indicators.get("ema_alignment", "NEUTRAL")
    macd_dir = indicators.get("macd_direction", "NEUTRAL")
    
    # BB Squeeze Multi-TF
    if bb_4h.get("squeeze", False) and bb_1h.get("squeeze", False):
        patterns.append({"name": "BB_SQUEEZE_MULTI_TF", "severity": "HIGH", "details": f"BB squeeze on 1H & 4H"})
    elif bb_4h.get("squeeze", False):
        patterns.append({"name": "BB_SQUEEZE_4H", "severity": "MEDIUM", "details": f"BB squeeze on 4H"})
    
    # EMA Alignment
    if ema_alignment == "BULL_ALIGNED":
        patterns.append({"name": "EMA_BULL_ALIGN", "severity": "MEDIUM", "details": "EMA 9>21>50"})
    elif ema_alignment == "BEAR_ALIGNED":
        patterns.append({"name": "EMA_BEAR_ALIGN", "severity": "MEDIUM", "details": "EMA 9<21<50"})
    
    # MACD Direction
    if macd_dir == "BULLISH":
        patterns.append({"name": "MACD_BULLISH", "severity": "LOW", "details": "MACD histogram positive"})
    elif macd_dir == "BEARISH":
        patterns.append({"name": "MACD_BEARISH", "severity": "LOW", "details": "MACD histogram negative"})
    
    # Volume Expansion
    if vol_ratio > th.get("volume_spike_multiplier", 2.0):
        patterns.append({"name": "VOLUME_EXPANSION", "severity": "MEDIUM", "details": f"Volume {vol_ratio:.1f}x average"})
    
    # OI Expansion
    if abs(oi_change) > 5:
        side = "INCREASE" if oi_change > 0 else "DECREASE"
        patterns.append({"name": "OI_EXPANSION", "severity": "LOW", "details": f"OI {side} {abs(oi_change):.1f}%"})
    
    # RSI Extremes
    if rsi_4h < th.get("rsi_oversold", 30):
        patterns.append({"name": "RSI_OVERSOLD", "severity": "HIGH", "details": f"4H RSI {rsi_4h:.1f}"})
    elif rsi_4h > th.get("rsi_overbought", 70):
        patterns.append({"name": "RSI_OVERBOUGHT", "severity": "HIGH", "details": f"4H RSI {rsi_4h:.1f}"})
    
    # Taker Dominance
    if taker_ratio > 0.6:
        patterns.append({"name": "TAKER_BUY_DOM", "severity": "MEDIUM", "details": f"Taker buy {taker_ratio*100:.0f}%"})
    elif taker_ratio < 0.4:
        patterns.append({"name": "TAKER_SELL_DOM", "severity": "MEDIUM", "details": f"Taker sell {(1-taker_ratio)*100:.0f}%"})
    
    return patterns

def calculate_emas(closes):
    """Calculate EMA 9, 21, 50."""
    if len(closes) < 50:
        return {"ema9": 0, "ema21": 0, "ema50": 0, "alignment": "NEUTRAL"}
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50)
    if ema9 > ema21 > ema50:
        alignment = "BULL_ALIGNED"
    elif ema9 < ema21 < ema50:
        alignment = "BEAR_ALIGNED"
    else:
        alignment = "MIXED"
    return {"ema9": float(ema9), "ema21": float(ema21), "ema50": float(ema50), "alignment": alignment}

def analyze_asset(symbol, thresholds):
    """Analyze a single asset."""
    price_data = get_price(symbol)
    if not price_data or "last" not in price_data:
        return None
    
    price = price_data["last"]
    change_24h = float(price_data.get("change_24h", "0").rstrip("%")) if isinstance(price_data.get("change_24h"), str) else price_data.get("change_24h", 0)
    
    # Fetch 4H and 1H klines
    closes_4h, _, _, _ = fetch_klines(symbol, "240", 200)
    closes_1h, _, _, _ = fetch_klines(symbol, "60", 200)
    
    if not closes_4h or not closes_1h:
        # Use defaults if klines fail
        indicators = {
            "price": price, "change_24h": change_24h,
            "rsi_4h": 50, "rsi_1h": 50,
            "bb_4h": {"width": 0.1, "squeeze": False}, "bb_1h": {"width": 0.1, "squeeze": False},
            "macd_direction": "NEUTRAL", "ema_alignment": "NEUTRAL",
            "vol_ratio": 1.0, "oi_change": 0, "taker_ratio": 0.5
        }
    else:
        # Calculate indicators
        rsi_4h = rsi(closes_4h, 14)
        rsi_1h = rsi(closes_1h, 14)
        bb_4h = bollinger_bands(closes_4h, 20)
        bb_1h = bollinger_bands(closes_1h, 20)
        macd_4h = macd(closes_4h, 12, 26, 9)
        emas_4h = calculate_emas(closes_4h)
        
        # Volume ratio (simplified - using current vs avg)
        vols_1h = []
        if len(closes_1h) > 20:
            _, _, _, vols_1h = fetch_klines(symbol, "60", 50)
            vol_ratio = float(np.mean(vols_1h[-1:])) / float(np.mean(vols_1h[:-20])) if len(vols_1h) > 20 and np.mean(vols_1h[:-20]) > 0 else 1.0
        else:
            vol_ratio = 1.0
        
        # OI change (fetch from ticker)
        try:
            ticker_resp = session.get_tickers(category="linear", symbol=symbol)
            ticker = ticker_resp.get("result", {}).get("list", [{}])[0] if ticker_resp.get("retCode") == 0 else {}
            # OI change not directly available, use default
            oi_change = 0
        except Exception:
            oi_change = 0
        
        # Taker ratio (not available via current API, default)
        taker_ratio = 0.5
        
        indicators = {
            "price": price, "change_24h": change_24h,
            "rsi_4h": rsi_4h, "rsi_1h": rsi_1h,
            "bb_4h": bb_4h, "bb_1h": bb_1h,
            "macd_direction": macd_4h["direction"],
            "ema_alignment": emas_4h["alignment"],
            "vol_ratio": vol_ratio, "oi_change": oi_change, "taker_ratio": taker_ratio
        }
    
    patterns = detect_patterns(symbol, indicators, thresholds)
    
    return {
        "symbol": symbol,
        "price": price,
        "change_24h": change_24h,
        "indicators_4h": {
            "rsi": indicators["rsi_4h"],
            "bb_width": indicators["bb_4h"]["width"],
            "bb_squeeze": indicators["bb_4h"]["squeeze"],
            "macd_hist": macd(closes_4h, 12, 26, 9)["hist"] if closes_4h else 0,
            "ema9": calculate_emas(closes_4h)["ema9"],
            "ema21": calculate_emas(closes_4h)["ema21"],
            "ema_alignment": indicators["ema_alignment"],
        },
        "indicators_1h": {
            "rsi": indicators["rsi_1h"],
            "bb_width": indicators["bb_1h"]["width"],
            "bb_squeeze": indicators["bb_1h"]["squeeze"],
        },
        "vol_ratio": indicators["vol_ratio"],
        "patterns": patterns
    }

def get_portfolio_state():
    """Get current portfolio state."""
    try:
        balance = get_balance()
        positions = get_positions()
        
        # Calculate total equity and PnL
        total_equity = balance.get("equity", 0) if isinstance(balance, dict) else 0
        
        # Get current prices for position PnL calculation
        positions_data = []
        total_pnl = 0
        for pos in positions.get("list", []) if isinstance(positions, dict) else positions:
            sym = pos.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            price_data = get_price(sym)
            price = price_data.get("last", 0) if isinstance(price_data, dict) else 0
            entry = pos.get("avgPrice", 0) or 0
            size = abs(float(pos.get("size", 0)))
            side = pos.get("side", "NONE")
            
            if entry > 0 and price > 0:
                if side == "Buy":
                    pnl = (price - entry) * size
                else:
                    pnl = (entry - price) * size
                total_pnl += pnl
            
            positions_data.append({
                "symbol": sym, "side": side, "size": size,
                "entry": entry, "price": price, "pnl": pnl if entry > 0 and price > 0 else 0
            })
        
        # Get fear & greed index
        try:
            import urllib.request
            with urllib.request.urlopen("https://api.alternative.me/fng/", timeout=5) as resp:
                fng_data = json.loads(resp.read())
                fear_greed = int(fng_data.get("data", [{}])[0].get("value", 50))
        except Exception:
            fear_greed = 50
        
        return {
            "total_equity": total_equity,
            "total_pnl": total_pnl,
            "positions": positions_data,
            "fear_greed": fear_greed
        }
    except Exception as e:
        return {"error": str(e), "total_equity": 0, "total_pnl": 0, "positions": [], "fear_greed": 50}


if __name__ == "__main__":
    # Use timezone-aware datetime (no warnings)
    start_time = datetime.now(timezone.utc)
    timestamp = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Load thresholds
    thresholds = load_adaptive_thresholds()
    
    # Scan all tracked assets
    assets_data = {}
    for symbol in TRACKED_ASSETS:
        try:
            assets_data[symbol] = analyze_asset(symbol, thresholds)
        except Exception as e:
            assets_data[symbol] = {"error": str(e)}
    
    # Get portfolio state
    portfolio = get_portfolio_state()
    
    # Build snapshot
    snapshot = {
        "timestamp": timestamp,
        "scan_duration": "OBSERVE_DETECT",
        "assets": assets_data,
        "portfolio": portfolio,
        "patterns_detected": [
            {"symbol": sym, **p}
            for sym, data in assets_data.items()
            if data and "patterns" in data
            for p in data["patterns"]
        ]
    }
    
    # Save snapshot
    snapshot_dir = os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning/snapshots")
    os.makedirs(snapshot_dir, exist_ok=True)
    snapshot_file = os.path.join(snapshot_dir, f"scan_{start_time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(snapshot_file, "w") as f:
        json.dump(snapshot, f, indent=2)
    
    # Also save as latest_snapshot
    latest_path = os.path.expanduser("~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/latest_snapshot.json")
    os.makedirs(os.path.dirname(latest_path), exist_ok=True)
    with open(latest_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    
    # Output JSON to stdout (no stderr, no warnings)
    print(json.dumps(snapshot, indent=2))