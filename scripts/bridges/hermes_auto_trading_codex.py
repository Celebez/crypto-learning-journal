#!/usr/bin/env python3
"""
Hermes Auto-Trading System v1.0
================================
Model-agnostic trading rules — works with ANY AI model.
Rules are HARDCODED, not dependent on LLM reasoning.

Usage:
  python3 hermes_auto_trading.py --analyze          # Full market analysis
  python3 hermes_auto_trading.py --scan              # Scan for entry signals
  python3 hermes_auto_trading.py --monitor           # Check positions & auto-close
  python3 hermes_auto_trading.py --trade             # Full cycle: analyze + trade
  python3 hermes_auto_trading.py --status            # Quick status
  python3 hermes_auto_trading.py --report            # Generate report for Telegram
"""

import sys
import json
import os
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Learning system integration
LEARNING_ENGINE_PATH = os.path.expanduser("~/hermes_learning_system/learning_engine.py")

# ============================================================
# TRADING RULES (HARDCODED — MODEL-AGNOSTIC) v2.0
# Balanced: Conservative entry, Moderate exit, Tight risk
# ============================================================

# ============================================================
# LEARNING SYSTEM INTEGRATION
# Load calibration data from crypto_portfolio_monitor_learning
# ============================================================
LEARNING_WEIGHTS_PATH = os.path.expanduser(
    "~/.hermes/skills/trading/crypto_portfolio_monitor_learning/data/learning_weights.json"
)

def load_learning_weights() -> Dict:
    """Load learning weights from the learning system.
    
    Returns calibration data:
    - calibration_multiplier: 0.5-1.5 (adjusts confidence)
    - indicator_weights: accuracy per indicator
    - calibration_tier: UNRELIABLE/LOW/MEDIUM/HIGH
    """
    try:
        with open(LEARNING_WEIGHTS_PATH) as f:
            data = json.load(f)
        return {
            "calibration_multiplier": data.get("calibration_multiplier", 1.0),
            "calibration_tier": data.get("calibration_tier", "UNKNOWN"),
            "accuracy_rate": data.get("accuracy_rate", 0),
            "indicator_weights": data.get("indicator_weights", {}),
        }
    except Exception:
        return {
            "calibration_multiplier": 1.0,
            "calibration_tier": "NO_DATA",
            "accuracy_rate": 0,
            "indicator_weights": {},
        }

def apply_learning_calibration(score: int, reasons: List[str], learning: Dict) -> Tuple[int, List[str]]:
    """Apply learning calibration to entry score.
    
    - Low accuracy tier: reduce confidence by 20%
    - High accuracy tier: boost confidence by 10%
    - Adjust individual indicator weights based on historical accuracy
    """
    calibration = learning.get("calibration_multiplier", 1.0)
    tier = learning.get("calibration_tier", "UNKNOWN")
    indicator_weights = learning.get("indicator_weights", {})
    
    # Apply calibration multiplier to score
    adjusted_score = int(score * calibration)
    
    # Log calibration effect
    if calibration < 1.0:
        reasons.append(f"⚠️ Learning calibration: {calibration:.2f}x (tier: {tier})")
    elif calibration > 1.0:
        reasons.append(f"✅ Learning boost: {calibration:.2f}x (tier: {tier})")
    
    return adjusted_score, reasons

RULES = {
    "entry": {
        "rsi_oversold": 40,           # Buy when RSI < 40 (lebih longgar dari 35)
        "rsi_oversold_strong": 30,    # Strong buy when RSI < 30
        "rsi_overbought_penalty": 65, # Penalty if RSI > 65 (hindari beli mahal)
        "bb_squeeze_width": 5.0,      # BB width < 5% = squeeze (lebih longgar)
        "macd_bullish": True,         # MACD must be bullish or crossing
        "ema_fast_above_slow": True,  # EMA7 > EMA20
        "volume_surge_ratio": 1.5,    # Volume > 1.5x average = confirmation
        "min_score": 6,               # Minimum entry score (penalty-based, not hard gates)
        "max_rsi_for_entry": 70,      # Jangan beli jika RSI > 70 (overbought)
        "min_candles": 200,           # Skip symbols without enough indicator history
        "min_24h_volume_usd": 50_000_000, # Skip illiquid contracts
        "consecutive_candles": 3,     # Require 3 candles in signal direction
        "min_adx": 25,                # Prefer clear trends, avoid chop
    },
    # --- EXIT RULES (SELL) ---
    "exit": {
        "take_profit_pct": 2.5,       # Auto-close at +2.5% profit (lebih cepat)
        "take_profit_strong_pct": 4.0,# Strong TP at +4%
        "stop_loss_pct": -2.0,        # Auto-close at -2% loss (lebih ketat)
        "stop_loss_strong_pct": -3.5, # Emergency close at -3.5%
        "rsi_overbought": 70,         # Sell when RSI > 70 (lebih cepat)
        "rsi_oversold_for_short": 30, # Cover shorts when downside is exhausted
        "max_hold_hours": 12,         # Time exit after 12h if trade has not worked
        "time_exit_min_profit_pct": 0.5, # Close stale trades below +0.5%
        "trailing_start_pct": 1.0,    # Start trailing after +1% (was 0.3% — too tight)
        "trailing_stop_pct": 0.8,     # Base trailing: 0.8% from peak (was 0.4%)
        "trailing_stop_tight_pct": 0.5, # Tight trail after +2% (was +1% at 0.25%)
        "breakeven_profit_pct": 1.5,  # Breakeven after +1.5% (was +1%)
        "partial_close_pct": 50,      # Close 50% when +2%, sisanya trailing
        "max_loss_usd": -3.0,         # Hard cap: close any position losing > $3 absolute
    },
    # --- RISK MANAGEMENT ---
    "risk": {
        "max_positions": 10,          # Max open positions (dari 15 → 10)
        "max_per_position_usd": 50,   # Max USD per position (reduced to cap losses)
        "max_total_exposure_pct": 100, # No limit — full risk (updated dari 80%)
        "min_balance_usd": 0,         # Disabled — trade with any balance
        "max_daily_loss_pct": 3.0,    # Stop trading if daily loss > 3% (dari 5% → 3%)
        "max_correlated_positions": 3,# Max 3 posisi di 1 ecosystem (misal: semua L1)
    },
    # --- SYMBOLS TO TRADE (Universal - All USDT Perpetuals) ---
    "symbols": {
        "tier1": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "HYPEUSDT"],  # Top priority
        "tier2": "all_usdt_perpetuals",  # Universal - fetch all from Bybit
        "exclude": [
            # Stablecoins (zero movement, cannot profit)
            "USDCUSDT", "USDEUSDT", "RLUSDUSDT",
            # Tokenized stocks/ETFs (not crypto)
            "AAPLUSDT", "AMZNUSDT", "COINUSDT", "EWJUSDT", "GOOGLUSDT",
            "HYUNDAIUSDT", "IWMUSDT", "METAUSDT", "MSFTUSDT", "MUUSDT",
            "NVDAUSDT", "QQQUSDT", "SPYUSDT", "TSLAUSDT",
            # Other
            "DOGEUSDT",
        ],  # Never scan/trade these tokens
    },
    # --- ANALYSIS TIMEFRAMES ---
    "timeframes": {
        "entry": 15,        # 15m for entry timing
        "confirmation": 60, # 1h for confirmation
        "trend": 240,       # 4h for trend
        "macro": "D",       # Daily for macro
    },
}

# ============================================================
# CONFIGURATION
# ============================================================
CONFIG = {
    "bridge_path": os.path.expanduser("~/hermes_bybit_bridge.py"),
    "trade_log": os.path.expanduser("~/hermes_auto_trades.json"),
    "report_path": os.path.expanduser("~/hermes_trading_report.txt"),
    "analysis_cache": os.path.expanduser("~/hermes_analysis_cache.json"),
}

# ============================================================
# IMPORTS (lazy load for speed)
# ============================================================
def _import_deps():
    """Lazy import heavy dependencies."""
    import pandas as pd
    import numpy as np
    from pybit.unified_trading import HTTP
    
    # Import bridge credentials
    sys.path.insert(0, os.path.expanduser("~"))
    from hermes_bybit_bridge import session as bridge_session
    
    return pd, np, HTTP, bridge_session

# ============================================================
# ANALYSIS FUNCTIONS
# ============================================================
def compute_rsi(closes, period=14):
    """Compute RSI."""
    import numpy as np
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).ewm(span=period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def compute_macd(closes, fast=12, slow=26, signal=9):
    """Compute MACD."""
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_bollinger(closes, period=20, std=2):
    """Compute Bollinger Bands."""
    middle = closes.rolling(window=period).mean()
    bb_std = closes.rolling(window=period).std()
    upper = middle + (bb_std * std)
    lower = middle - (bb_std * std)
    width = (upper - lower) / middle * 100
    return middle, upper, lower, width

# ============================================================
# MQL5 INDICATORS (ADDED 2026-05-30)
# ============================================================

def compute_stochastic(highs, lows, closes, k_period=14, d_period=3):
    """Stochastic Oscillator (%K and %D)."""
    lowest_low = lows.rolling(window=k_period).min()
    highest_high = highs.rolling(window=k_period).max()
    k = 100 * (closes - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_period).mean()
    return k, d

def compute_adx(highs, lows, closes, period=14):
    """Average Directional Index (+DI, -DI, ADX)."""
    import numpy as np
    plus_dm = highs.diff()
    minus_dm = -lows.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    
    tr1 = highs - lows
    tr2 = (highs - closes.shift(1)).abs()
    tr3 = (lows - closes.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(span=period, adjust=False).mean()
    
    return adx, plus_di, minus_di

def compute_atr(highs, lows, closes, period=14):
    """Average True Range."""
    tr1 = highs - lows
    tr2 = (highs - closes.shift(1)).abs()
    tr3 = (lows - closes.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr

def compute_vwap(highs, lows, closes, volumes):
    """Volume Weighted Average Price (intraday reset)."""
    typical_price = (highs + lows + closes) / 3
    vwap = (typical_price * volumes).cumsum() / volumes.cumsum()
    return vwap

def compute_obv(closes, volumes):
    """On-Balance Volume."""
    obv = volumes.copy()
    obv[closes < closes.shift(1)] = -volumes[closes < closes.shift(1)]
    obv = obv.cumsum()
    return obv

def compute_parabolic_sar(highs, lows, closes, af_start=0.02, af_step=0.02, af_max=0.2):
    """Parabolic SAR."""
    length = len(closes)
    sar = pd.Series(index=closes.index, dtype=float)
    trend = pd.Series(index=closes.index, dtype=float)
    
    # Initialize
    sar.iloc[0] = lows.iloc[0]
    trend.iloc[0] = 1  # 1 = uptrend, -1 = downtrend
    
    af = af_start
    ep = highs.iloc[0] if trend.iloc[0] == 1 else lows.iloc[0]
    
    for i in range(1, length):
        if trend.iloc[i-1] == 1:  # Uptrend
            sar.iloc[i] = sar.iloc[i-1] + af * (ep - sar.iloc[i-1])
            sar.iloc[i] = min(sar.iloc[i], lows.iloc[i-1], lows.iloc[max(0,i-2)])
            
            if lows.iloc[i] < sar.iloc[i]:  # Reversal to downtrend
                trend.iloc[i] = -1
                sar.iloc[i] = ep
                ep = lows.iloc[i]
                af = af_start
            else:
                trend.iloc[i] = 1
                if highs.iloc[i] > ep:
                    ep = highs.iloc[i]
                    af = min(af + af_step, af_max)
        else:  # Downtrend
            sar.iloc[i] = sar.iloc[i-1] + af * (ep - sar.iloc[i-1])
            sar.iloc[i] = max(sar.iloc[i], highs.iloc[i-1], highs.iloc[max(0,i-2)])
            
            if highs.iloc[i] > sar.iloc[i]:  # Reversal to uptrend
                trend.iloc[i] = 1
                sar.iloc[i] = ep
                ep = highs.iloc[i]
                af = af_start
            else:
                trend.iloc[i] = -1
                if lows.iloc[i] < ep:
                    ep = lows.iloc[i]
                    af = min(af + af_step, af_max)
    
    return sar, trend

def compute_ichimoku(highs, lows, closes, tenkan=9, kijun=26, senkou_b=52):
    """Ichimoku Cloud (simplified: tenkan, kijun, senkou_a, senkou_b)."""
    tenkan_sen = (highs.rolling(tenkan).max() + lows.rolling(tenkan).min()) / 2
    kijun_sen = (highs.rolling(kijun).max() + lows.rolling(kijun).min()) / 2
    senkou_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    senkou_b_line = ((highs.rolling(senkou_b).max() + lows.rolling(senkou_b).min()) / 2).shift(kijun)
    return tenkan_sen, kijun_sen, senkou_a, senkou_b_line

def compute_cci(highs, lows, closes, period=20):
    """Commodity Channel Index."""
    tp = (highs + lows + closes) / 3
    sma = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma) / (0.015 * mad)
    return cci

def compute_williams_r(highs, lows, closes, period=14):
    """Williams %R."""
    highest_high = highs.rolling(window=period).max()
    lowest_low = lows.rolling(window=period).min()
    wr = -100 * (highest_high - closes) / (highest_high - lowest_low)
    return wr

def compute_fibonacci(swing_high, swing_low):
    """Fibonacci Retracement levels."""
    diff = swing_high - swing_low
    return {
        "0.0%": swing_high,
        "23.6%": swing_high - 0.236 * diff,
        "38.2%": swing_high - 0.382 * diff,
        "50.0%": swing_high - 0.500 * diff,
        "61.8%": swing_high - 0.618 * diff,
        "78.6%": swing_high - 0.786 * diff,
        "100.0%": swing_low,
    }

# ============================================================
# CRYPTO ANALYSIS ENGINE v3.0
# Microstructure(35%) + TA(35%) + Sentiment(15%) + OI/Funding(15%)
# ============================================================

def analyze_microstructure(session, symbol: str) -> Dict:
    """Analyze market microstructure from Bybit orderbook and trades."""
    try:
        # Get orderbook
        ob = session.get_orderbook(category="linear", symbol=symbol, limit=25)
        bids = ob["result"]["b"]
        asks = ob["result"]["a"]
        
        # Bid/Ask analysis
        total_bid_vol = sum(float(b[1]) for b in bids)
        total_ask_vol = sum(float(a[1]) for a in asks)
        spread = float(asks[0][0]) - float(bids[0][0]) if bids and asks else 0
        spread_pct = (spread / float(asks[0][0]) * 100) if asks and float(asks[0][0]) > 0 else 0
        
        # Whale detection (top 5 orders = large orders)
        whale_bids = sum(float(b[1]) for b in bids[:5])
        whale_asks = sum(float(a[1]) for a in asks[:5])
        
        # Taker analysis (approximate from orderbook imbalance)
        bid_ask_ratio = total_bid_vol / total_ask_vol if total_ask_vol > 0 else 1
        taker_bias = "BUY" if bid_ask_ratio > 1.1 else "SELL" if bid_ask_ratio < 0.9 else "NEUTRAL"
        
        # Net flow approximation
        net_flow = total_bid_vol - total_ask_vol
        net_flow_pct = (net_flow / (total_bid_vol + total_ask_vol) * 100) if (total_bid_vol + total_ask_vol) > 0 else 0
        
        # Whale accumulation/distribution
        whale_bias = "ACCUMULATION" if whale_bids > whale_asks * 1.2 else "DISTRIBUTION" if whale_asks > whale_bids * 1.2 else "NEUTRAL"
        
        # Liquidity assessment
        liquidity = "GOOD" if spread_pct < 0.1 else "MODERATE" if spread_pct < 0.3 else "LOW"
        
        return {
            "spread": {"value": spread, "pct": spread_pct, "liquidity": liquidity},
            "bid_ask": {"bid_vol": total_bid_vol, "ask_vol": total_ask_vol, "ratio": bid_ask_ratio},
            "whale": {"bid_vol": whale_bids, "ask_vol": whale_asks, "bias": whale_bias},
            "taker": {"bias": taker_bias},
            "net_flow": {"value": net_flow, "pct": net_flow_pct},
            "score": 50,  # Base score, will be adjusted
        }
    except Exception as e:
        return {"error": str(e), "score": 50}

def compute_microstructure_score(micro: Dict) -> Tuple[int, List[str]]:
    """Compute microstructure score (0-100)."""
    if "error" in micro:
        return 50, [f"Micro error: {micro['error']}"]
    
    score = 50  # Base
    reasons = []
    
    # Whale Flow (+/- 20)
    if micro["whale"]["bias"] == "ACCUMULATION":
        score += 20
        reasons.append(f"Whale ACCUMULATION (bid: {micro['whale']['bid_vol']:.0f} > ask: {micro['whale']['ask_vol']:.0f})")
    elif micro["whale"]["bias"] == "DISTRIBUTION":
        score -= 20
        reasons.append(f"Whale DISTRIBUTION (ask: {micro['whale']['ask_vol']:.0f} > bid: {micro['whale']['bid_vol']:.0f})")
    
    # Net Flow (+/- 15)
    if micro["net_flow"]["pct"] > 5:
        score += 15
        reasons.append(f"Net INFLOW (+{micro['net_flow']['pct']:.1f}%)")
    elif micro["net_flow"]["pct"] < -5:
        score -= 15
        reasons.append(f"Net OUTFLOW ({micro['net_flow']['pct']:.1f}%)")
    
    # Taker Volume (+/- 15)
    if micro["taker"]["bias"] == "BUY":
        score += 15
        reasons.append("Taker BUY dominant")
    elif micro["taker"]["bias"] == "SELL":
        score -= 15
        reasons.append("Taker SELL dominant")
    
    # Spread (+/- 5)
    if micro["spread"]["liquidity"] == "GOOD":
        score += 5
        reasons.append("Tight spread (good liquidity)")
    elif micro["spread"]["liquidity"] == "LOW":
        score -= 5
        reasons.append("Wide spread (low liquidity)")
    
    return max(0, min(100, score)), reasons

def compute_technical_score(analysis: Dict) -> Tuple[int, List[str]]:
    """Compute technical analysis score (0-100)."""
    if "error" in analysis:
        return 50, [f"TA error: {analysis['error']}"]
    
    score = 50  # Base
    reasons = []
    
    # EMA Alignment (+/- 20)
    if analysis["ema"]["fast_above_slow"]:
        score += 20
        reasons.append("EMA bullish alignment")
    else:
        score -= 20
        reasons.append("EMA bearish alignment")
    
    # RSI (+/- 15)
    if analysis["rsi"] < 30:
        score += 15
        reasons.append(f"RSI oversold ({analysis['rsi']:.1f})")
    elif analysis["rsi"] > 70:
        score -= 15
        reasons.append(f"RSI overbought ({analysis['rsi']:.1f})")
    
    # MACD (+/- 15)
    if analysis["macd"]["bullish"]:
        score += 15
        reasons.append("MACD bullish")
    else:
        score -= 15
        reasons.append("MACD bearish")
    
    # Volume (+/- 10)
    if analysis["volume"]["surge"]:
        score += 10
        reasons.append(f"Volume surge ({analysis['volume']['ratio']:.1f}x)")
    elif analysis["volume"]["ratio"] < 0.5:
        score -= 10
        reasons.append("Volume declining")
    
    # Market Structure (+/- 10)
    if analysis.get("trend") == "BULL":
        score += 10
        reasons.append("Bullish market structure")
    else:
        score -= 10
        reasons.append("Bearish market structure")
    
    return max(0, min(100, score)), reasons

def compute_sentiment_score(symbol: str) -> Tuple[int, List[str]]:
    """Compute sentiment score (0-100).
    
    FIX v2: Sentiment is PLACEHOLDER — returns neutral 50.
    Weighted at 15% in total but contributes nothing useful.
    TODO: Integrate CoinGecko, LunarCrush, or News API.
    """
    score = 50  # Neutral base — placeholder
    reasons = ["Sentiment: neutral (placeholder — no API)"]
    
    return score, reasons

def compute_oi_funding_score(session, symbol: str) -> Tuple[int, List[str], float, float]:
    """Compute Open Interest and Funding score (0-100). Returns (score, reasons, funding_rate, oi_change)."""
    try:
        # Get funding rate history
        funding = session.get_funding_rate_history(category="linear", symbol=symbol, limit=1)
        funding_list = funding["result"]["list"]
        funding_rate = float(funding_list[0]["fundingRate"]) * 100 if funding_list else 0
        
        # Get open interest
        oi = session.get_open_interest(category="linear", symbol=symbol, intervalTime="1h", limit=24)
        oi_list = oi["result"]["list"]
        
        if len(oi_list) >= 2:
            current_oi = float(oi_list[-1]["openInterest"])
            prev_oi = float(oi_list[-2]["openInterest"])
            oi_change = ((current_oi - prev_oi) / prev_oi * 100) if prev_oi > 0 else 0
        else:
            oi_change = 0
            current_oi = 0
        
        score = 50  # Base
        reasons = []
        
        # OI Trend (+/- 25)
        if oi_change > 5:
            score += 25
            reasons.append(f"OI rising (+{oi_change:.1f}%)")
        elif oi_change < -5:
            score -= 25
            reasons.append(f"OI falling ({oi_change:.1f}%)")
        
        # Funding Rate (+/- 25)
        if -0.01 <= funding_rate <= 0.01:
            score += 25
            reasons.append(f"Funding neutral ({funding_rate:.4f}%)")
        elif funding_rate > 0.05:
            score -= 15
            reasons.append(f"High funding ({funding_rate:.4f}%) - Long squeeze risk")
        elif funding_rate < -0.05:
            score += 15
            reasons.append(f"Low funding ({funding_rate:.4f}%) - Short squeeze potential")
        
        return max(0, min(100, score)), reasons, funding_rate, oi_change
    except Exception as e:
        return 50, [f"OI/Funding error: {e}"], 0, 0

def crypto_analysis_engine(session, symbol: str) -> Dict:
    """Full Crypto Analysis Engine v3.0."""
    # Get technical analysis
    analysis = analyze_symbol(session, symbol)
    
    if "error" in analysis:
        return {"error": analysis["error"], "symbol": symbol}
    
    # Compute all scores
    micro_score, micro_reasons = compute_microstructure_score(
        analyze_microstructure(session, symbol)
    )
    ta_score, ta_reasons = compute_technical_score(analysis)
    sentiment_score, sentiment_reasons = compute_sentiment_score(symbol)
    oi_score, oi_reasons, funding_rate, oi_change = compute_oi_funding_score(session, symbol)
    
    # Weighted total
    # FIX v2: Exclude sentiment (placeholder=50) from weighted total
    # Micro 40% + TA 40% + OI 20% = 100% (sentiment excluded until API ready)
    total_score = (
        micro_score * 0.40 +
        ta_score * 0.40 +
        oi_score * 0.20
    )
    
    # Apply learning calibration
    learning = load_learning_weights()
    total_score, cal_reasons = apply_learning_calibration(int(total_score), [], learning)
    
    # Determine signal with filters
    signal = "HOLD"
    confidence = 0
    risk = "NORMAL"
    
    # FIX v2: Relaxed thresholds + TA override
    # BUY: 55 (was 65) — let TA drive entries
    # SELL: 40 (was 35) — let TA drive exits
    # Filters only block if 2+ negative signals (not 1)
    
    if total_score >= 55:
        # Count negative filters (need 2+ to block)
        neg_count = 0
        if any("DISTRIBUTION" in r for r in micro_reasons): neg_count += 1
        if any("OUTFLOW" in r for r in micro_reasons): neg_count += 1
        if any("SELL dominant" in r for r in micro_reasons): neg_count += 1
        if any("falling" in r.lower() for r in oi_reasons): neg_count += 1
        
        # Check for TA strength override
        has_strong_ta = ta_score >= 70
        has_breakout = analysis["bb"]["position"] == "ABOVE" and analysis["volume"]["surge"]
        
        # BUY if: not too many negatives OR TA is strong
        if neg_count < 2 or has_strong_ta or has_breakout:
            signal = "BUY"
            confidence = min(95, int(total_score))
        else:
            signal = "HOLD"
            confidence = int(total_score)
    elif total_score <= 40:
        # Count positive filters (need 2+ to block sell)
        pos_count = 0
        if any("ACCUMULATION" in r for r in micro_reasons): pos_count += 1
        if any("INFLOW" in r for r in micro_reasons): pos_count += 1
        if any("BUY dominant" in r for r in micro_reasons): pos_count += 1
        if any("rising" in r.lower() for r in oi_reasons): pos_count += 1
        
        # SELL if: not too many positives
        if pos_count < 2:
            signal = "SELL"
            confidence = min(95, int(100 - total_score))
        else:
            signal = "HOLD"
            confidence = int(total_score)
    
    # Risk assessment
    if analysis.get("atr", {}).get("high_volatility"):
        risk = "HIGH"
    elif total_score > 70 or total_score < 30:
        risk = "LOW"
    else:
        risk = "NORMAL"
    
    # Market structure
    market_structure = "BULLISH" if total_score > 60 else "BEARISH" if total_score < 40 else "NEUTRAL"
    
    # Trade setup
    price = analysis["price"]
    atr = analysis.get("atr", {}).get("value", price * 0.02)
    sl = price - (atr * 1.5) if signal == "BUY" else price + (atr * 1.5) if signal == "SELL" else price
    tp1 = price + (atr * 2) if signal == "BUY" else price - (atr * 2) if signal == "SELL" else price
    tp2 = price + (atr * 3) if signal == "BUY" else price - (atr * 3) if signal == "SELL" else price
    tp3 = price + (atr * 5) if signal == "BUY" else price - (atr * 5) if signal == "SELL" else price
    
    # Log signal for statistics tracking
    try:
        from hermes_signal_logger import log_signal
        log_signal(signal, symbol, total_score, {
            "micro": micro_score,
            "ta": ta_score,
            "oi": oi_score,
        })
    except Exception:
        pass  # Don't fail trading if logging fails
    
    # ALSO log prediction to learning engine (for accuracy tracking)
    if signal in ["BUY", "SELL"]:
        try:
            import sys
            sys.path.insert(0, os.path.expanduser("~/hermes_learning_system"))
            from learning_engine import log_prediction
            confidence = total_score / 100.0  # Convert score to confidence
            reason = f"{signal} signal: " + ", ".join(ta_reasons[:3]) if ta_reasons else "signals"
            log_prediction(symbol, signal, confidence, reason)
        except Exception:
            pass  # Don't fail trading if learning log fails
    
    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": confidence,
        "risk": risk,
        "market_structure": market_structure,
        "total_score": round(total_score, 1),
        "scores": {
            "microstructure": micro_score,
            "technical": ta_score,
            "sentiment": sentiment_score,
            "oi_funding": oi_score,
        },
        "reasons": {
            "microstructure": micro_reasons,
            "technical": ta_reasons,
            "sentiment": sentiment_reasons,
            "oi_funding": oi_reasons,
        },
        "trade_setup": {
            "entry": price,
            "stop_loss": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
        },
        "data": {
            "funding_rate": funding_rate,
            "oi_change": oi_change,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def analyze_symbol(session, symbol: str, interval: int = 15, limit: int = 200) -> Dict:
    """Full technical analysis for a single symbol."""
    pd, np, _, _ = _import_deps()
    
    try:
        k = session.get_kline(category="linear", symbol=symbol, interval=str(interval), limit=limit)
        df = pd.DataFrame(k["result"]["list"], 
                         columns=["ts", "open", "high", "low", "close", "vol", "tv"])
        for c in ["open", "high", "low", "close", "vol"]:
            df[c] = df[c].astype(float)
        df = df.sort_values("ts").reset_index(drop=True)
        candle_count = len(df)
        
        closes = df["close"]
        latest = df.iloc[-1]
        
        # RSI
        rsi = compute_rsi(closes)
        rsi_val = float(rsi.iloc[-1])
        
        # MACD
        macd_line, signal_line, histogram = compute_macd(closes)
        macd_val = float(macd_line.iloc[-1])
        signal_val = float(signal_line.iloc[-1])
        hist_val = float(histogram.iloc[-1])
        macd_bullish = macd_val > signal_val
        macd_cross_up = float(histogram.iloc[-2]) < 0 and hist_val > 0
        macd_cross_down = float(histogram.iloc[-2]) > 0 and hist_val < 0
        
        # Bollinger Bands
        bb_mid, bb_upper, bb_lower, bb_width = compute_bollinger(closes)
        bb_width_val = float(bb_width.iloc[-1])
        bb_squeeze = bb_width_val < RULES["entry"]["bb_squeeze_width"]
        price = float(latest["close"])
        bb_position = "ABOVE" if price > float(bb_upper.iloc[-1]) else "BELOW" if price < float(bb_lower.iloc[-1]) else "MIDDLE"
        
        # EMA
        ema7 = closes.ewm(span=7, adjust=False).mean()
        ema20 = closes.ewm(span=20, adjust=False).mean()
        ema50 = closes.ewm(span=50, adjust=False).mean()
        ema200 = closes.ewm(span=200, adjust=False).mean()
        ema_bullish = float(ema7.iloc[-1]) > float(ema20.iloc[-1])
        price_above_ema50 = price > float(ema50.iloc[-1])
        
        # Volume
        vol_avg = df["vol"].rolling(20).mean()
        vol_ratio = float(latest["vol"] / float(vol_avg.iloc[-1])) if float(vol_avg.iloc[-1]) > 0 else 1.0
        
        # Support/Resistance (simple)
        recent_high = float(df["high"].iloc[-20:].max())
        recent_low = float(df["low"].iloc[-20:].min())
        
        # Trend
        sma50 = closes.rolling(50).mean()
        sma200 = closes.rolling(200).mean()
        if candle_count >= 200 and not pd.isna(sma200.iloc[-1]):
            trend = "BULL" if float(sma50.iloc[-1]) > float(sma200.iloc[-1]) else "BEAR"
        else:
            trend = "BULL" if float(ema50.iloc[-1]) > float(ema200.iloc[-1]) else "BEAR"

        candle_direction = np.where(closes > df["open"], 1, np.where(closes < df["open"], -1, 0))
        bullish_streak = 0
        bearish_streak = 0
        for direction in candle_direction[::-1]:
            if direction == 1 and bearish_streak == 0:
                bullish_streak += 1
            elif direction == -1 and bullish_streak == 0:
                bearish_streak += 1
            else:
                break
        
        # MQL5 INDICATORS
        highs = df["high"]
        lows = df["low"]
        volumes = df["vol"]
        
        # Stochastic
        stoch_k, stoch_d = compute_stochastic(highs, lows, closes)
        stoch_k_val = float(stoch_k.iloc[-1])
        stoch_d_val = float(stoch_d.iloc[-1])
        
        # ADX
        adx, plus_di, minus_di = compute_adx(highs, lows, closes)
        adx_val = float(adx.iloc[-1])
        
        # ATR
        atr = compute_atr(highs, lows, closes)
        atr_val = float(atr.iloc[-1])
        atr_pct = (atr_val / price) * 100  # ATR as % of price
        
        # VWAP
        vwap = compute_vwap(highs, lows, closes, volumes)
        vwap_val = float(vwap.iloc[-1])
        vwap_bias = "BULL" if price > vwap_val else "BEAR"
        
        # OBV
        obv = compute_obv(closes, volumes)
        obv_trend = "UP" if float(obv.iloc[-1]) > float(obv.iloc[-5]) else "DOWN"
        
        # Parabolic SAR
        psar, psar_trend = compute_parabolic_sar(highs, lows, closes)
        psar_val = float(psar.iloc[-1])
        psar_signal = "BUY" if float(psar_trend.iloc[-1]) == 1 else "SELL"
        
        # Fibonacci
        fib = compute_fibonacci(recent_high, recent_low)
        
        return {
            "symbol": symbol,
            "price": price,
            "interval": interval,
            "candle_count": candle_count,
            "rsi": rsi_val,
            "rsi_signal": "OVERSOLD" if rsi_val < 30 else "OVERBOUGHT" if rsi_val > 70 else "NEUTRAL",
            "macd": {"value": macd_val, "signal": signal_val, "histogram": hist_val, 
                     "bullish": macd_bullish, "cross_up": macd_cross_up, "cross_down": macd_cross_down},
            "bb": {"width": bb_width_val, "squeeze": bb_squeeze, "position": bb_position,
                   "upper": float(bb_upper.iloc[-1]), "lower": float(bb_lower.iloc[-1])},
            "ema": {"fast_above_slow": ema_bullish, "ema7": float(ema7.iloc[-1]), 
                    "ema20": float(ema20.iloc[-1]), "ema50": float(ema50.iloc[-1]),
                    "ema200": float(ema200.iloc[-1]), "price_above_ema50": price_above_ema50},
            "volume": {"ratio": vol_ratio, "surge": vol_ratio > RULES["entry"]["volume_surge_ratio"]},
            "candles": {"bullish_streak": bullish_streak, "bearish_streak": bearish_streak},
            "support": recent_low,
            "resistance": recent_high,
            "trend": trend,
            # MQL5 Indicators
            "stochastic": {"k": stoch_k_val, "d": stoch_d_val, 
                          "oversold": stoch_k_val < 20, "overbought": stoch_k_val > 80},
            "adx": {"value": adx_val, "strong": adx_val > 25, "weak": adx_val < 20,
                   "plus_di": float(plus_di.iloc[-1]), "minus_di": float(minus_di.iloc[-1])},
            "atr": {"value": atr_val, "pct": atr_pct, "high_volatility": atr_pct > 3},
            "vwap": {"value": vwap_val, "bias": vwap_bias},
            "obv": {"trend": obv_trend, "value": float(obv.iloc[-1])},
            "parabolic_sar": {"value": psar_val, "signal": psar_signal},
            "fibonacci": fib,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

def compute_entry_score(analysis: Dict) -> Tuple[int, List[str]]:
    """Compute entry score based on HARDCODED rules v2.0. Returns (score, reasons)."""
    if "error" in analysis:
        return 0, [f"Analysis error: {analysis['error']}"]
    
    score = 0
    reasons = []
    rules = RULES["entry"]
    min_candles = rules.get("min_candles", 200)
    min_streak = rules.get("consecutive_candles", 3)
    volume_ratio = analysis.get("volume", {}).get("ratio", 0)
    confirmations = analysis.get("confirmation", {})
    confirmation_trend = confirmations.get("confirmation", {}).get("trend")
    trend_4h = confirmations.get("trend", {}).get("trend")
    
    # Hard gates: long entries only in confirmed liquid momentum.
    if analysis.get("candle_count", 0) < min_candles:
        return 0, [f"SKIP: insufficient history ({analysis.get('candle_count', 0)} < {min_candles})"]
    # Essential filters (not hard gates — score penalty instead)
    if analysis.get("trend") != "BULL":
        score -= 2
        reasons.append(f"15m trend not bullish ({analysis.get('trend')})")
    if confirmation_trend and confirmation_trend != "BULL":
        score -= 1
        reasons.append(f"1H trend not bullish ({confirmation_trend})")
    if trend_4h and trend_4h != "BULL":
        score -= 1
        reasons.append(f"4H trend not bullish ({trend_4h})")
    if not analysis.get("ema", {}).get("price_above_ema50", False):
        score -= 1
        reasons.append("price below EMA50")
    if volume_ratio < rules.get("volume_surge_ratio", 1.5):
        score -= 1
        reasons.append(f"volume low ({volume_ratio:.1f}x)")
    if analysis.get("candles", {}).get("bullish_streak", 0) < min_streak:
        score -= 1
        reasons.append(f"needs {min_streak} bullish candles")
    if analysis.get("adx", {}).get("value", 0) < rules.get("min_adx", 25):
        return 0, [f"SKIP: ADX too weak ({analysis.get('adx', {}).get('value', 0):.1f})"]
    
    # 0. CRITICAL: Skip if RSI too high (overbought = don't buy)
    if analysis["rsi"] > rules.get("max_rsi_for_entry", 70):
        return 0, [f"SKIP: RSI overbought ({analysis['rsi']:.1f} > {rules['max_rsi_for_entry']})"]
    
    # 1. RSI Oversold (dengan penalty untuk overbought)
    if analysis["rsi"] < rules["rsi_oversold_strong"]:
        score += 2
        reasons.append(f"RSI STRONG OVERSOLD ({analysis['rsi']:.1f})")
    elif analysis["rsi"] < rules["rsi_oversold"]:
        score += 1
        reasons.append(f"RSI oversold ({analysis['rsi']:.1f})")
    
    # RSI penalty jika terlalu tinggi (mendekati overbought)
    if analysis["rsi"] > rules.get("rsi_overbought_penalty", 65):
        score -= 1
        reasons.append(f"RSI penalty ({analysis['rsi']:.1f} > {rules['rsi_overbought_penalty']})")
    
    # 2. BB Squeeze
    if analysis["bb"]["squeeze"]:
        score += 1
        reasons.append(f"BB SQUEEZE ({analysis['bb']['width']:.1f}%)")
    
    # 3. MACD Bullish
    if analysis["macd"]["bullish"]:
        score += 1
        reasons.append("MACD bullish")
    if analysis["macd"]["cross_up"]:
        score += 1
        reasons.append("MACD CROSS UP!")
    
    # 4. EMA Trend
    if analysis["ema"]["fast_above_slow"]:
        score += 1
        reasons.append("EMA7 > EMA20")
    if analysis.get("ema", {}).get("price_above_ema50"):
        score += 1
        reasons.append("Price > EMA50")
    
    # 5. Volume Confirmation
    if analysis["volume"]["surge"]:
        score += 2
        reasons.append(f"Volume surge ({analysis['volume']['ratio']:.1f}x)")
    
    if analysis.get("candles", {}).get("bullish_streak", 0) >= min_streak:
        score += 1
        reasons.append(f"{analysis['candles']['bullish_streak']} bullish candles")
    
    # 6. BB Position (bonus)
    if analysis["bb"]["position"] == "BELOW":
        score += 1
        reasons.append("Price below BB lower")
    
    # === MQL5 INDICATORS (BONUS) ===
    
    # 7. Stochastic Oversold (konfirmasi RSI)
    if analysis.get("stochastic", {}).get("oversold"):
        score += 1
        reasons.append(f"Stoch OVERSOLD ({analysis['stochastic']['k']:.1f})")
    
    # 8. ADX Strong Trend (filter sideways)
    if analysis.get("adx", {}).get("strong"):
        score += 1
        reasons.append(f"ADX strong ({analysis['adx']['value']:.1f})")
    elif analysis.get("adx", {}).get("weak"):
        score -= 1
        reasons.append(f"ADX weak/sideways ({analysis['adx']['value']:.1f})")
    
    # 9. VWAP Bullish Bias
    if analysis.get("vwap", {}).get("bias") == "BULL":
        score += 1
        reasons.append("VWAP bullish")
    
    # 10. OBV Accumulation
    if analysis.get("obv", {}).get("trend") == "UP":
        score += 1
        reasons.append("OBV accumulation")
    
    # 11. Parabolic SAR Buy Signal
    if analysis.get("parabolic_sar", {}).get("signal") == "BUY":
        score += 1
        reasons.append("PSAR buy signal")
    
    if confirmation_trend == "BULL" and trend_4h == "BULL":
        score += 2
        reasons.append("1H/4H bullish confirmation")
    
    return score, reasons

def compute_short_score(analysis: Dict) -> Tuple[int, List[str]]:
    """Compute SHORT entry score. Inverse of entry logic — looking for bearish signals.
    
    Returns (score, reasons). Score >= 4 = SHORT signal.
    For perpetual contracts: can profit from both directions.
    """
    if "error" in analysis:
        return 0, [f"Analysis error: {analysis['error']}"]
    
    score = 0
    reasons = []
    rules = RULES["entry"]
    min_candles = rules.get("min_candles", 200)
    min_streak = rules.get("consecutive_candles", 3)
    volume_ratio = analysis.get("volume", {}).get("ratio", 0)
    confirmations = analysis.get("confirmation", {})
    confirmation_trend = confirmations.get("confirmation", {}).get("trend")
    trend_4h = confirmations.get("trend", {}).get("trend")
    
    # Hard gates: shorts were the main loser, so require full downtrend alignment.
    if analysis.get("candle_count", 0) < min_candles:
        return 0, [f"SKIP SHORT: insufficient history ({analysis.get('candle_count', 0)} < {min_candles})"]
    # Essential filters (score penalty, not hard gate)
    if analysis.get("trend") != "BEAR":
        score -= 2
        reasons.append(f"15m trend not bearish ({analysis.get('trend')})")
    if confirmation_trend and confirmation_trend != "BEAR":
        score -= 1
        reasons.append(f"1H trend not bearish ({confirmation_trend})")
    if trend_4h and trend_4h != "BEAR":
        score -= 1
        reasons.append(f"4H trend not bearish ({trend_4h})")
    if analysis.get("ema", {}).get("price_above_ema50", True):
        score -= 1
        reasons.append("price above EMA50")
    if volume_ratio < rules.get("volume_surge_ratio", 1.5):
        score -= 1
        reasons.append(f"volume low ({volume_ratio:.1f}x)")
    if analysis.get("candles", {}).get("bearish_streak", 0) < min_streak:
        score -= 1
        reasons.append(f"needs {min_streak} bearish candles")
    if analysis.get("adx", {}).get("value", 0) < rules.get("min_adx", 25):
        return 0, [f"SKIP SHORT: ADX too weak ({analysis.get('adx', {}).get('value', 0):.1f})"]
    
    # 1. RSI Overbought (SHORT opportunity)
    if analysis["rsi"] > 75:
        score += 2
        reasons.append(f"RSI STRONG OVERBOUGHT ({analysis['rsi']:.1f})")
    elif analysis["rsi"] > 70:
        score += 1
        reasons.append(f"RSI overbought ({analysis['rsi']:.1f})")
    
    # RSI penalty if oversold (don't short when cheap)
    if analysis["rsi"] < 35:
        score -= 1
        reasons.append(f"RSI oversold penalty ({analysis['rsi']:.1f})")
    
    # 2. BB Overbought (price above upper band)
    if analysis["bb"]["position"] == "ABOVE":
        score += 1
        reasons.append("Price above BB upper (overbought)")
    
    # 3. MACD Bearish
    if not analysis["macd"]["bullish"]:
        score += 1
        reasons.append("MACD bearish")
    if analysis["macd"].get("cross_down"):
        score += 1
        reasons.append("MACD CROSS DOWN!")
    
    # 4. EMA Bearish (fast below slow)
    if not analysis["ema"]["fast_above_slow"]:
        score += 1
        reasons.append("EMA7 < EMA20 (bearish)")
    
    # 5. Volume confirmation (surge + bearish)
    if analysis["volume"]["surge"] and not analysis["macd"]["bullish"]:
        score += 2
        reasons.append(f"Volume surge + bearish ({analysis['volume']['ratio']:.1f}x)")
    
    if analysis.get("candles", {}).get("bearish_streak", 0) >= min_streak:
        score += 1
        reasons.append(f"{analysis['candles']['bearish_streak']} bearish candles")
    
    # 6. Trend bearish
    if analysis.get("trend") == "BEAR":
        score += 1
        reasons.append("Bearish trend")
    
    # 7. ADX strong (trending, not sideways)
    if analysis.get("adx", {}).get("strong"):
        score += 1
        reasons.append(f"ADX strong ({analysis['adx']['value']:.1f})")
    
    # 8. VWAP Bearish
    if analysis.get("vwap", {}).get("bias") == "BEAR":
        score += 1
        reasons.append("VWAP bearish")
    
    # 9. OBV Distribution
    if analysis.get("obv", {}).get("trend") == "DOWN":
        score += 1
        reasons.append("OBV distribution")
    
    # 10. Parabolic SAR Sell Signal
    if analysis.get("parabolic_sar", {}).get("signal") == "SELL":
        score += 1
        reasons.append("PSAR sell signal")
    
    if confirmation_trend == "BEAR" and trend_4h == "BEAR":
        score += 2
        reasons.append("1H/4H bearish confirmation")
    
    return score, reasons

def compute_exit_score(analysis: Dict, entry_price: float, current_price: float, 
                       peak_price: float, hold_hours: float, side: str = "Buy") -> Tuple[int, List[str], str]:
    """Compute exit score. Returns (score, reasons, action)."""
    if "error" in analysis:
        return 0, ["Analysis error"], "HOLD"
    
    score = 0
    reasons = []
    action = "HOLD"
    rules = RULES["exit"]
    
    is_short = str(side).lower() == "sell"
    if entry_price > 0:
        pnl_pct = ((entry_price - current_price) / entry_price) * 100 if is_short else ((current_price - entry_price) / entry_price) * 100
    else:
        pnl_pct = 0
    if peak_price > 0:
        drawdown_from_peak = ((current_price - peak_price) / peak_price) * 100 if is_short else ((peak_price - current_price) / peak_price) * 100
    else:
        drawdown_from_peak = 0
    
    # 1. Take Profit
    if pnl_pct >= rules["take_profit_strong_pct"]:
        score += 3
        reasons.append(f"STRONG TP: +{pnl_pct:.1f}%")
        action = "CLOSE"
    elif pnl_pct >= rules["take_profit_pct"]:
        score += 2
        reasons.append(f"TP hit: +{pnl_pct:.1f}%")
        action = "CLOSE"
    
    # 2. Stop Loss
    if pnl_pct <= rules["stop_loss_strong_pct"]:
        score += 3
        reasons.append(f"EMERGENCY SL: {pnl_pct:.1f}%")
        action = "CLOSE"
    elif pnl_pct <= rules["stop_loss_pct"]:
        score += 2
        reasons.append(f"SL hit: {pnl_pct:.1f}%")
        action = "CLOSE"
    
    # 3. Breakeven and Trailing Stop
    breakeven_profit = rules.get("breakeven_profit_pct", 1.0)
    reached_breakeven_trigger = False
    if entry_price > 0 and peak_price > 0:
        if is_short:
            reached_breakeven_trigger = peak_price <= entry_price * (1 - breakeven_profit / 100)
        else:
            reached_breakeven_trigger = peak_price >= entry_price * (1 + breakeven_profit / 100)
    
    if reached_breakeven_trigger and pnl_pct <= 0:
        score += 3
        reasons.append(f"Breakeven stop: gave back +{breakeven_profit:.1f}% move")
        action = "CLOSE"
    elif pnl_pct >= breakeven_profit:
        reasons.append(f"Breakeven protected: +{pnl_pct:.1f}%")
    
    trailing_start = rules.get("trailing_start_pct", 0.3)
    trailing_stop = rules.get("trailing_stop_tight_pct", rules["trailing_stop_pct"]) if pnl_pct >= 1.0 else rules["trailing_stop_pct"]
    if pnl_pct >= trailing_start and drawdown_from_peak >= trailing_stop:
        score += 2
        reasons.append(f"Trailing stop: -{drawdown_from_peak:.1f}% from peak")
        action = "CLOSE"
    
    # 4. RSI Exhaustion
    if not is_short and analysis["rsi"] > rules["rsi_overbought"]:
        score += 1
        reasons.append(f"RSI overbought ({analysis['rsi']:.1f})")
        if score >= 2:
            action = "CLOSE"
    elif is_short and analysis["rsi"] < rules.get("rsi_oversold_for_short", 30):
        score += 1
        reasons.append(f"RSI oversold against short ({analysis['rsi']:.1f})")
        if score >= 2:
            action = "CLOSE"
    
    # 5. Time Exit
    if hold_hours >= rules["max_hold_hours"] and pnl_pct < rules.get("time_exit_min_profit_pct", 0.5):
        score += 2
        reasons.append(f"Time exit: {hold_hours:.0f}h and PnL {pnl_pct:+.1f}%")
        action = "CLOSE"
    
    # 6. MACD Bearish Cross
    if not is_short and not analysis["macd"]["bullish"] and analysis["macd"]["histogram"] < 0:
        score += 1
        reasons.append("MACD bearish")
    elif is_short and analysis["macd"]["bullish"] and analysis["macd"]["histogram"] > 0:
        score += 1
        reasons.append("MACD bullish against short")
    
    return score, reasons, action

# ============================================================
# TRADING FUNCTIONS
# ============================================================
def get_portfolio_status(session) -> Dict:
    """Get current portfolio status."""
    pd, np, _, _ = _import_deps()
    
    # Balance
    bal = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
    wallet = float(bal["result"]["list"][0]["totalWalletBalance"])
    equity = float(bal["result"]["list"][0]["totalEquity"])
    available = float(bal["result"]["list"][0]["totalAvailableBalance"])
    
    # Positions — use settleCoin to avoid "missing symbol" error
    pos = session.get_positions(category="linear", settleCoin="USDT")
    positions = []
    for p in pos["result"]["list"]:
        size = float(p.get("size", 0))
        if size > 0:
            positions.append({
                "symbol": p["symbol"],
                "side": p["side"],
                "size": str(size),
                "entry": float(p.get("avgPrice", 0)),
                "mark": float(p.get("markPrice", 0)),
                "pnl": float(p.get("unrealisedPnl", 0)),
                "leverage": p.get("leverage", "1"),
                "created_at": p.get("createdTime", ""),
            })
    
    return {
        "wallet": wallet,
        "equity": equity,
        "available": available,
        "positions": positions,
        "position_count": len(positions),
        "total_pnl": sum(p["pnl"] for p in positions),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def scan_entry_signals(session, symbols=None) -> List[Dict]:
    """Scan multiple symbols for LONG and SHORT entry signals.
    
    For perpetual contracts: can profit from both directions.
    - BUY = Open LONG (score >= min_score)
    - SELL = Open SHORT (short_score >= 4)
    - WATCH = Close to threshold
    - PASS = No signal
    """
    # Flatten symbols from dict or use as-is if list
    if symbols is None:
        symbols = RULES["symbols"]
    
    if isinstance(symbols, dict):
        # Flatten all tiers into a single list
        all_symbols = []
        tickers = session.get_tickers(category="linear")
        ticker_map = {t["symbol"]: t for t in tickers["result"]["list"]}
        for tier, syms in symbols.items():
            if syms == "all_usdt_perpetuals":
                # Fetch all USDT perpetuals from Bybit
                for t in tickers["result"]["list"]:
                    if t["symbol"].endswith("USDT"):
                        all_symbols.append(t["symbol"])
            elif isinstance(syms, list):
                all_symbols.extend(syms)
        symbols = all_symbols
    else:
        tickers = session.get_tickers(category="linear")
        ticker_map = {t["symbol"]: t for t in tickers["result"]["list"]}
    # Filter out excluded symbols (e.g., DOGEUSDT)
    exclude_list = RULES["symbols"].get("exclude", [])
    symbols = [s for s in symbols if s not in exclude_list]
    
    min_24h_volume = RULES["entry"].get("min_24h_volume_usd", 50_000_000)
    liquid_symbols = []
    for sym in symbols:
        ticker = ticker_map.get(sym, {})
        turnover_24h = float(ticker.get("turnover24h") or 0)
        if turnover_24h <= 0:
            volume_24h = float(ticker.get("volume24h") or 0)
            last_price = float(ticker.get("lastPrice") or 0)
            turnover_24h = volume_24h * last_price
        if turnover_24h >= min_24h_volume:
            liquid_symbols.append(sym)
    symbols = liquid_symbols

    # Sort by priority: tier1 first
    tier1 = RULES["symbols"].get("tier1", [])
    def sort_key(sym):
        if sym in tier1:
            return (0, tier1.index(sym))
        return (1, sym)
    symbols.sort(key=sort_key)
    
    results = []
    for sym in symbols:
        try:
            analysis = analyze_symbol(
                session, sym, interval=RULES["timeframes"]["entry"], 
                limit=RULES["entry"].get("min_candles", 200),
            )
            if "error" not in analysis:
                confirmation = analyze_symbol(
                    session, sym, interval=RULES["timeframes"]["confirmation"], 
                    limit=RULES["entry"].get("min_candles", 200),
                )
                trend = analyze_symbol(
                    session, sym, interval=RULES["timeframes"]["trend"], 
                    limit=RULES["entry"].get("min_candles", 200),
                )
                if "error" in confirmation or "error" in trend:
                    continue
                analysis["confirmation"] = {
                    "confirmation": {
                        "interval": confirmation["interval"],
                        "trend": confirmation["trend"],
                        "price_above_ema50": confirmation["ema"]["price_above_ema50"],
                        "adx": confirmation["adx"]["value"],
                    },
                    "trend": {
                        "interval": trend["interval"],
                        "trend": trend["trend"],
                        "price_above_ema50": trend["ema"]["price_above_ema50"],
                        "adx": trend["adx"]["value"],
                    },
                }
                ticker = ticker_map.get(sym, {})
                turnover_24h = float(ticker.get("turnover24h") or 0)
                if turnover_24h <= 0:
                    turnover_24h = float(ticker.get("volume24h") or 0) * float(ticker.get("lastPrice") or 0)
                analysis["volume"]["turnover_24h"] = turnover_24h
                
                # LONG score
                score, reasons = compute_entry_score(analysis)
                min_score = RULES["entry"]["min_score"]
                short_min = 4  # SHORT threshold separate (original 4/13)
                
                # SHORT score (for perpetual contracts)
                short_score, short_reasons = compute_short_score(analysis)
                
                # Determine signal: BUY, SELL, WATCH, or PASS
                # Compare scores — pick the STRONGER direction
                # This prevents BUY bias when both scores are high
                if score >= min_score and short_score >= short_min:
                    # Both signals active — pick the stronger one
                    if short_score > score:
                        signal = "SELL"
                    else:
                        signal = "BUY"
                elif score >= min_score:
                    signal = "BUY"
                elif short_score >= short_min:
                    signal = "SELL"  # SHORT entry
                elif score >= min_score - 1 or short_score >= short_min - 1:
                    signal = "WATCH"
                else:
                    signal = "PASS"
                
                results.append({
                    "symbol": sym,
                    "score": score,
                    "short_score": short_score,
                    "signal": signal,
                    "reasons": reasons if signal == "BUY" else short_reasons if signal == "SELL" else reasons,
                    "price": analysis["price"],
                    "rsi": analysis["rsi"],
                    "bb_width": analysis["bb"]["width"],
                    "volume_24h": analysis["volume"]["turnover_24h"],
                    "tier": 1 if sym in tier1 else 2,
                })
        except Exception as e:
            pass
    
    # Deduplicate: keep only the first occurrence of each symbol
    seen = set()
    unique_results = []
    for r in results:
        if r["symbol"] not in seen:
            seen.add(r["symbol"])
            unique_results.append(r)
    results = unique_results

    # Sort by: tier (1 first), then score (highest first)
    results.sort(key=lambda x: (0 if x["tier"] == 1 else 1, -x["score"]))
    return results

def monitor_positions(session) -> List[Dict]:
    """Monitor all positions and decide which to close."""
    pd, np, _, _ = _import_deps()
    
    portfolio = get_portfolio_status(session)
    actions = []
    
    for pos in portfolio["positions"]:
        try:
            # Get current price analysis
            analysis = analyze_symbol(session, pos["symbol"], interval=RULES["timeframes"]["entry"])
            if "error" in analysis:
                continue
            
            # Calculate hold time
            created_ms = int(pos.get("created_at", "0"))
            hold_hours = (datetime.now(timezone.utc).timestamp() * 1000 - created_ms) / 3600000 if created_ms > 0 else 0
            
            # Compute exit score. For shorts, the favorable extreme is the recent low.
            is_short = str(pos["side"]).lower() == "sell"
            if is_short:
                peak_price = min(pos["entry"], analysis["support"]) if analysis["support"] < pos["entry"] else pos["mark"]
            else:
                peak_price = max(pos["entry"], analysis["resistance"]) if analysis["resistance"] > pos["entry"] else pos["mark"]
            
            score, reasons, action = compute_exit_score(
                analysis, 
                entry_price=pos["entry"],
                current_price=pos["mark"],
                peak_price=peak_price,
                hold_hours=hold_hours,
                side=pos["side"],
            )
            
            # Hard cap: close if absolute loss exceeds max_loss_usd
            max_loss = RULES["exit"].get("max_loss_usd", -3.0)
            if pos["pnl"] <= max_loss:
                score += 5
                reasons.append(f"MAX LOSS HIT: ${pos['pnl']:.2f} <= ${max_loss}")
                action = "CLOSE"

            if pos["entry"] > 0:
                pnl_pct = ((pos["entry"] - pos["mark"]) / pos["entry"]) * 100 if is_short else ((pos["mark"] - pos["entry"]) / pos["entry"]) * 100
            else:
                pnl_pct = 0
            
            actions.append({
                "symbol": pos["symbol"],
                "side": pos["side"],
                "entry": pos["entry"],
                "mark": pos["mark"],
                "pnl": pos["pnl"],
                "pnl_pct": pnl_pct,
                "hold_hours": hold_hours,
                "exit_score": score,
                "exit_reasons": reasons,
                "action": action,
            })
        except Exception as e:
            pass
    
    # Sort by urgency (highest exit score first)
    actions.sort(key=lambda x: x["exit_score"], reverse=True)
    return actions

def execute_close(session, symbol: str) -> Dict:
    """Execute close position."""
    try:
        # Get current position
        pos = session.get_positions(category="linear", symbol=symbol)
        position = None
        for p in pos["result"]["list"]:
            if float(p.get("size", 0)) > 0:
                position = p
                break
        
        if not position:
            return {"success": False, "error": "No position found"}
        
        side = position["side"]
        size = position["size"]
        
        # Close: sell if long, buy if short
        close_side = "Sell" if side == "Buy" else "Buy"
        
        order = session.place_order(
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=size,
            timeInForce="IOC",
        )
        
        return {
            "success": True,
            "symbol": symbol,
            "side": close_side,
            "qty": size,
            "orderId": order["result"]["orderId"],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def execute_buy(session, symbol: str, usd_amount: float) -> Dict:
    """Execute market buy order with proper qty rounding."""
    try:
        # Get current price
        tickers = session.get_tickers(category="linear", symbol=symbol)
        price = float(tickers["result"]["list"][0]["lastPrice"])
        
        # Get instrument info for min qty
        info = session.get_instruments_info(category="linear", symbol=symbol)
        lot_size = info["result"]["list"][0]["lotSizeFilter"]
        min_qty = float(lot_size["minOrderQty"])
        qty_step = float(lot_size["qtyStep"])
        
        # Calculate quantity
        raw_qty = usd_amount / price
        
        # Determine decimal places from qty_step
        if qty_step >= 1:
            decimals = 0
        elif qty_step >= 0.1:
            decimals = 1
        elif qty_step >= 0.01:
            decimals = 2
        elif qty_step >= 0.001:
            decimals = 3
        elif qty_step >= 0.0001:
            decimals = 4
        elif qty_step >= 0.00001:
            decimals = 5
        else:
            decimals = 8
        
        # Round properly using Decimal for precision
        from decimal import Decimal, ROUND_DOWN
        # Fix: use int string for whole number steps to avoid decimal precision issues
        step_str = str(int(qty_step)) if qty_step == int(qty_step) else str(qty_step)
        qty = float(Decimal(str(raw_qty)).quantize(Decimal(step_str), rounding=ROUND_DOWN))
        qty = max(qty, min_qty)
        
        if qty < min_qty:
            return {"success": False, "error": f"Qty {qty} below min {min_qty}"}
        
        order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=str(qty),
            timeInForce="IOC",
        )
        
        return {
            "success": True,
            "symbol": symbol,
            "side": "Buy",
            "qty": str(qty),
            "price": price,
            "orderId": order["result"]["orderId"],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
def execute_short(session, symbol: str, usd_amount: float) -> Dict:
    """Execute market SHORT order with proper qty rounding.
    
    Opens a short position on perpetual contracts.
    For perpetual: sell first, buy back later to profit from price drop.
    """
    try:
        # Get current price
        tickers = session.get_tickers(category="linear", symbol=symbol)
        price = float(tickers["result"]["list"][0]["lastPrice"])

        # Get instrument info for min qty
        info = session.get_instruments_info(category="linear", symbol=symbol)
        lot_size = info["result"]["list"][0]["lotSizeFilter"]
        min_qty = float(lot_size["minOrderQty"])
        qty_step = float(lot_size["qtyStep"])

        # Calculate quantity
        raw_qty = usd_amount / price

        # Round properly using Decimal for precision
        from decimal import Decimal, ROUND_DOWN
        step_str = str(int(qty_step)) if qty_step == int(qty_step) else str(qty_step)
        qty = float(Decimal(str(raw_qty)).quantize(Decimal(step_str), rounding=ROUND_DOWN))
        qty = max(qty, min_qty)

        if qty < min_qty:
            return {"success": False, "error": f"Qty {qty} below min {min_qty}"}

        # SELL side = open SHORT position
        order = session.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=str(qty),
            timeInForce="IOC",
        )

        return {
            "success": True,
            "symbol": symbol,
            "side": "Sell",
            "qty": str(qty),
            "price": price,
            "orderId": order["result"]["orderId"],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def check_risk_management(portfolio: Dict) -> Tuple[bool, str]:
    """Check if we can open new positions."""
    rules = RULES["risk"]
    
    # Check max positions
    if portfolio["position_count"] >= rules["max_positions"]:
        return False, f"Max positions reached ({portfolio['position_count']}/{rules['max_positions']})"
    
    # Check min balance
    if portfolio["available"] < rules["min_balance_usd"]:
        return False, f"Insufficient balance (${portfolio['available']:.2f} < ${rules['min_balance_usd']})"
    
    # Check total exposure
    total_exposure = sum(abs(p["pnl"]) + float(p["entry"]) * float(p["size"]) for p in portfolio["positions"])
    exposure_pct = (total_exposure / portfolio["equity"] * 100) if portfolio["equity"] > 0 else 0
    if exposure_pct >= rules["max_total_exposure_pct"]:
        return False, f"Max exposure reached ({exposure_pct:.1f}% >= {rules['max_total_exposure_pct']}%)"
    
    return True, "OK"

# ============================================================
# MAIN COMMANDS
# ============================================================
def cmd_analyze():
    """Full market analysis."""
    pd, np, _, session = _import_deps()
    
    print("=== FULL MARKET ANALYSIS ===")
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()
    
    # Analyze all symbols (universal)
    symbols_config = RULES["symbols"]
    if isinstance(symbols_config, dict):
        all_symbols = []
        for tier, syms in symbols_config.items():
            if syms == "all_usdt_perpetuals":
                tickers = session.get_tickers(category="linear")
                for t in tickers["result"]["list"]:
                    if t["symbol"].endswith("USDT"):
                        all_symbols.append(t["symbol"])
            elif isinstance(syms, list):
                all_symbols.extend(syms)
        # Sort by priority
        tier1 = symbols_config.get("tier1", [])
        def sort_key(sym):
            if sym in tier1:
                return (0, tier1.index(sym))
            return (1, sym)
        all_symbols.sort(key=sort_key)
    else:
        all_symbols = symbols_config
    
    for sym in all_symbols:
        analysis = analyze_symbol(session, sym, interval=RULES["timeframes"]["entry"])
        if "error" in analysis:
            print(f"{sym}: ERROR - {analysis['error']}")
            continue
        
        score, reasons = compute_entry_score(analysis)
        signal = "BUY" if score >= RULES["entry"]["min_score"] else "WATCH" if score >= RULES["entry"]["min_score"] - 1 else "PASS"
        
        print(f"{sym:12s} | ${analysis['price']:>10,.2f} | RSI: {analysis['rsi']:5.1f} | "
              f"BB: {analysis['bb']['width']:5.1f}% | MACD: {'UP' if analysis['macd']['bullish'] else 'DN'} | "
              f"Score: {score:+d} | {signal}")
        if reasons:
            print(f"             | Reasons: {', '.join(reasons)}")
    
    # Portfolio status
    print()
    portfolio = get_portfolio_status(session)
    print(f"=== PORTFOLIO ===")
    print(f"Equity: ${portfolio['equity']:.2f} | Available: ${portfolio['available']:.2f}")
    print(f"Positions: {portfolio['position_count']}/{RULES['risk']['max_positions']}")
    print(f"Total PnL: ${portfolio['total_pnl']:+.2f}")
    
    # Risk check
    can_trade, risk_msg = check_risk_management(portfolio)
    print(f"Risk Status: {'OK' if can_trade else 'BLOCKED'} - {risk_msg}")

def cmd_scan():
    """Scan for entry signals."""
    pd, np, _, session = _import_deps()
    
    print("=== SCANNING FOR ENTRY SIGNALS ===")
    signals = scan_entry_signals(session)
    
    buy_signals = [s for s in signals if s["signal"] == "BUY"]
    sell_signals = [s for s in signals if s["signal"] == "SELL"]
    watch_signals = [s for s in signals if s["signal"] == "WATCH"]

    # Separate by tier
    tier1 = RULES["symbols"].get("tier1", [])
    buy_tier1 = [s for s in buy_signals if s["symbol"] in tier1]
    buy_tier2 = [s for s in buy_signals if s["symbol"] not in tier1]
    sell_tier1 = [s for s in sell_signals if s["symbol"] in tier1]
    sell_tier2 = [s for s in sell_signals if s["symbol"] not in tier1]
    
    if buy_tier1 or buy_tier2:
        print(f"\n🟢 BUY (LONG) SIGNALS ({len(buy_signals)}):")
        if buy_tier1:
            print(f"  ⭐ Tier 1:")
            for s in buy_tier1:
                print(f"    {s['symbol']:12s} | Score: {s['score']} | ${s['price']:,.2f} | RSI: {s['rsi']:.1f}")
                print(f"      Reasons: {', '.join(s['reasons'])}")
        if buy_tier2:
            print(f"  📊 Tier 2:")
            for s in buy_tier2[:5]:  # Show max 5 tier2
                print(f"    {s['symbol']:12s} | Score: {s['score']} | ${s['price']:,.2f} | RSI: {s['rsi']:.1f}")

    if sell_tier1 or sell_tier2:
        print(f"\n🔴 SELL (SHORT) SIGNALS ({len(sell_signals)}):")
        if sell_tier1:
            print(f"  ⭐ Tier 1:")
            for s in sell_tier1:
                print(f"    {s['symbol']:12s} | Short Score: {s['short_score']} | ${s['price']:,.2f} | RSI: {s['rsi']:.1f}")
                print(f"      Reasons: {', '.join(s['reasons'])}")
        if sell_tier2:
            print(f"  📊 Tier 2:")
            for s in sell_tier2[:5]:  # Show max 5 tier2
                print(f"    {s['symbol']:12s} | Short Score: {s['short_score']} | ${s['price']:,.2f} | RSI: {s['rsi']:.1f}")
    
    if watch_signals:
        print(f"\n🟡 WATCH ({len(watch_signals)}):")
        for s in watch_signals:
            print(f"  {s['symbol']:12s} | Score: {s['score']} | ${s['price']:,.2f}")
    
    if not buy_signals and not sell_signals and not watch_signals:
        print("\n❌ No signals found. Market conditions not favorable.")

def cmd_monitor():
    """Monitor positions and auto-close if needed."""
    pd, np, _, session = _import_deps()
    
    print("=== POSITION MONITOR ===")
    actions = monitor_positions(session)
    
    closes = [a for a in actions if a["action"] == "CLOSE"]
    holds = [a for a in actions if a["action"] == "HOLD"]
    
    print(f"\n📊 Positions: {len(actions)} total")
    print(f"🔴 CLOSE: {len(closes)} | 🟢 HOLD: {len(holds)}")
    
    if closes:
        print("\n=== AUTO-CLOSE RECOMMENDATIONS ===")
        for a in closes:
            print(f"  {a['symbol']:12s} | PnL: ${a['pnl']:+.2f} ({a['pnl_pct']:+.1f}%) | Exit Score: {a['exit_score']}")
            print(f"    Reasons: {', '.join(a['exit_reasons'])}")
    
    # Execute closes if any
    closed = []
    for a in closes:
        print(f"\n⏳ Closing {a['symbol']}...")
        result = execute_close(session, a["symbol"])
        if result["success"]:
            print(f"  ✅ Closed {a['symbol']} | Order: {result['orderId']}")
            closed.append(a["symbol"])
        else:
            print(f"  ❌ Failed: {result['error']}")
    
    return {"closes_recommended": len(closes), "closes_executed": len(closed), "closed_symbols": closed}

def cmd_trade():
    """Full trading cycle: analyze + execute."""
    pd, np, _, session = _import_deps()
    
    print("=== AUTO-TRADING CYCLE ===")
    
    # 1. Get portfolio
    portfolio = get_portfolio_status(session)
    print(f"Portfolio: ${portfolio['equity']:.2f} equity, {portfolio['position_count']} positions")
    
    # 2. Risk check
    can_trade, risk_msg = check_risk_management(portfolio)
    if not can_trade:
        print(f"\n⛔ BLOCKED: {risk_msg}")
        return
    
    # 3. Monitor existing positions (auto-close)
    print("\n--- Monitoring Positions ---")
    monitor_result = cmd_monitor()
    
    # 4. Scan for new entries
    print("\n--- Scanning for Entries ---")
    signals = scan_entry_signals(session)
    buy_signals = [s for s in signals if s["signal"] == "BUY"]
    sell_signals = [s for s in signals if s["signal"] == "SELL"]

    # Separate by tier: Tier 1 (BTC, ETH, BNB, SOL, HYPE) first
    tier1 = RULES["symbols"].get("tier1", [])
    buy_tier1 = [s for s in buy_signals if s["symbol"] in tier1]
    buy_tier2 = [s for s in buy_signals if s["symbol"] not in tier1]
    sell_tier1 = [s for s in sell_signals if s["symbol"] in tier1]
    sell_tier2 = [s for s in sell_signals if s["symbol"] not in tier1]

    # Execute: Tier 1 first, then Tier 2
    buy_ordered = buy_tier1 + buy_tier2
    sell_ordered = sell_tier1 + sell_tier2

    # Interleave BUY and SELL — alternate between both directions
    # This prevents the system from only going LONG
    all_entries = []
    for i in range(max(len(buy_ordered), len(sell_ordered))):
        if i < len(buy_ordered):
            all_entries.append(("LONG", buy_ordered[i]))
        if i < len(sell_ordered):
            all_entries.append(("SHORT", sell_ordered[i]))

    max_entries = 3
    entries_executed = 0

    if buy_ordered or sell_ordered:
        print(f"\n📊 Found {len(buy_ordered)} BUY + {len(sell_ordered)} SELL signals!")
        print(f"   Executing interleaved (max {max_entries} total)...")

        available = portfolio["available"]
        max_per_pos = RULES["risk"]["max_per_position_usd"]

        for direction, s in all_entries:
            if entries_executed >= max_entries:
                break

            portfolio = get_portfolio_status(session)
            can_trade, _ = check_risk_management(portfolio)
            if not can_trade:
                break

            size_usd = min(max_per_pos, available * 0.2)
            if size_usd < 10:
                continue

            if direction == "LONG":
                print(f"\n  ⏳ Opening LONG {s['symbol']} (${size_usd:.2f})...")
                result = execute_buy(session, s["symbol"], size_usd)
                if result["success"]:
                    print(f"  ✅ LONG {s['symbol']} | Qty: {result['qty']} @ ~${result['price']:,.2f}")
                    print(f"    Score: {s['score']} | Reasons: {', '.join(s['reasons'])}")
                    entries_executed += 1
                else:
                    print(f"  ❌ Failed: {result['error']}")
            else:
                print(f"\n  ⏳ Opening SHORT {s['symbol']} (${size_usd:.2f})...")
                result = execute_short(session, s["symbol"], size_usd)
                if result["success"]:
                    print(f"  ✅ SHORT {s['symbol']} | Qty: {result['qty']} @ ~${result['price']:,.2f}")
                    print(f"    Score: {s['short_score']} | Reasons: {', '.join(s['reasons'])}")
                    entries_executed += 1
                else:
                    print(f"  ❌ Failed: {result['error']}")

        print(f"\n  Total entries: {entries_executed}/{max_entries}")
    else:
        print("\n❌ No entry signals found (BUY or SELL).")
    
    # 5. Final status
    print("\n=== FINAL STATUS ===")
    portfolio = get_portfolio_status(session)
    print(f"Equity: ${portfolio['equity']:.2f} | PnL: ${portfolio['total_pnl']:+.2f} | Positions: {portfolio['position_count']}")

def cmd_status():
    """Quick status."""
    pd, np, _, session = _import_deps()
    
    portfolio = get_portfolio_status(session)
    
    print(f"=== QUICK STATUS ===")
    print(f"Equity: ${portfolio['equity']:.2f}")
    print(f"Available: ${portfolio['available']:.2f}")
    print(f"Positions: {portfolio['position_count']}/{RULES['risk']['max_positions']}")
    print(f"Total PnL: ${portfolio['total_pnl']:+.2f}")
    
    if portfolio["positions"]:
        longs = [p for p in portfolio["positions"] if p["side"] == "Buy"]
        shorts = [p for p in portfolio["positions"] if p["side"] == "Sell"]

        if longs:
            print(f"\n🟢 LONG ({len(longs)}):")
            for p in sorted(longs, key=lambda x: x["pnl"], reverse=True)[:5]:
                pnl_pct = ((p["mark"] - p["entry"]) / p["entry"]) * 100 if p["entry"] > 0 else 0
                emoji = "+" if p["pnl"] >= 0 else ""
                print(f"  {p['symbol']:12s} | {pnl_pct:+.1f}% | {emoji}${p['pnl']:.2f}")

        if shorts:
            print(f"\n🔴 SHORT ({len(shorts)}):")
            for p in sorted(shorts, key=lambda x: x["pnl"], reverse=True)[:5]:
                pnl_pct = ((p["entry"] - p["mark"]) / p["entry"]) * 100 if p["entry"] > 0 else 0
                emoji = "+" if p["pnl"] >= 0 else ""
                print(f"  {p['symbol']:12s} | {pnl_pct:+.1f}% | {emoji}${p['pnl']:.2f}")

def cmd_report():
    """Generate report for Telegram."""
    pd, np, _, session = _import_deps()
    
    portfolio = get_portfolio_status(session)
    
    # Get BTC price for reference
    try:
        tickers = session.get_tickers(category="linear", symbol="BTCUSDT")
        btc_price = float(tickers["result"]["list"][0]["lastPrice"])
        btc_chg = float(tickers["result"]["list"][0]["price24hPcnt"]) * 100
    except:
        btc_price = 0
        btc_chg = 0
    
    lines = []
    lines.append("📊 *TRADING REPORT*")
    lines.append(f"⏰ {datetime.now(timezone.utc).strftime('%d %b %H:%M UTC')}")
    lines.append("")
    lines.append(f"💰 *Equity:* ${portfolio['equity']:.2f}")
    lines.append(f"💵 *Available:* ${portfolio['available']:.2f}")
    lines.append(f"📈 *Positions:* {portfolio['position_count']}/{RULES['risk']['max_positions']}")
    lines.append(f"📊 *Total PnL:* ${portfolio['total_pnl']:+.2f}")
    lines.append("")
    lines.append(f"🪙 *BTC:* ${btc_price:,.2f} ({btc_chg:+.2f}%)")
    lines.append("")
    
    if portfolio["positions"]:
        longs = [p for p in portfolio["positions"] if p["side"] == "Buy"]
        shorts = [p for p in portfolio["positions"] if p["side"] == "Sell"]

        if longs:
            lines.append(f"*LONG Positions ({len(longs)}):*")
            for p in longs:
                pnl_pct = ((p["mark"] - p["entry"]) / p["entry"]) * 100 if p["entry"] > 0 else 0
                emoji = "+" if p["pnl"] >= 0 else ""
                lines.append(f"• 🟢 {p['symbol']}: {pnl_pct:+.1f}% ({emoji}${p['pnl']:.2f})")

        if shorts:
            lines.append(f"*SHORT Positions ({len(shorts)}):*")
            for p in shorts:
                pnl_pct = ((p["entry"] - p["mark"]) / p["entry"]) * 100 if p["entry"] > 0 else 0
                emoji = "+" if p["pnl"] >= 0 else ""
                lines.append(f"• 🔴 {p['symbol']}: {pnl_pct:+.1f}% ({emoji}${p['pnl']:.2f})")
    
    report = "\n".join(lines)
    print(report)
    
    # Save to file
    with open(CONFIG["report_path"], "w") as f:
        f.write(report)
    
    return report

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Hermes Auto-Trading System")
    parser.add_argument("--analyze", action="store_true", help="Full market analysis")
    parser.add_argument("--scan", action="store_true", help="Scan for entry signals")
    parser.add_argument("--monitor", action="store_true", help="Monitor positions & auto-close")
    parser.add_argument("--trade", action="store_true", help="Full trading cycle")
    parser.add_argument("--status", action="store_true", help="Quick status")
    parser.add_argument("--report", action="store_true", help="Generate report")
    
    args = parser.parse_args()
    
    if args.analyze:
        cmd_analyze()
    elif args.scan:
        cmd_scan()
    elif args.monitor:
        cmd_monitor()
    elif args.trade:
        cmd_trade()
    elif args.status:
        cmd_status()
    elif args.report:
        cmd_report()
    else:
        parser.print_help()
