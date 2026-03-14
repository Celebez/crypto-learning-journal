#!/usr/bin/env python3
"""
Hermes Crypto Analysis — Model-Independent Trading System
=========================================================
This script is designed to work with ANY AI model, ANY LLM.
It fetches market data, computes technical indicators, generates signals,
and executes trades autonomously via file-based bridge.

Usage:
  python3 hermes_crypto_analysis.py                    # Full analysis
  python3 hermes_crypto_analysis.py --trade            # Analysis + try trade (demo)
  python3 hermes_crypto_analysis.py --symbol ETHUSDT   # Specific symbol
  python3 hermes_crypto_analysis.py --cron daily        # Daily cron output
  python3 hermes_crypto_analysis.py --help              # Full help

Requirements: pip install pybit pandas numpy
"""
import json, os, sys, time
from datetime import datetime

try:
    from pybit.unified_trading import HTTP
    import pandas as pd
    import numpy as np
except ImportError:
    print("❌ Missing dependencies. Install: pip install pybit pandas numpy")
    sys.exit(1)

# ============================================================
# CONFIGURATION
# ============================================================
CONFIG = {
    "api_key": os.environ.get("BYBIT_API_KEY", "REPLACE_WITH_YOUR_DEMO_KEY"),
    "api_secret": os.environ.get("BYBIT_API_SECRET", "REPLACE_WITH_YOUR_DEMO_SECRET"),
    "demo": True,
    "symbols": "universal",  # Fetch all USDT perpetuals from Bybit
    "tier1": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "HYPEUSDT"],  # Priority order
    "intervals": {15: "15m", 60: "1h", 240: "4h", "D": "Daily"},
    "limits": {15: 300, 60: 300, 240: 200, "D": 150},
    "command_file": os.path.expanduser("~/hermes_trade_command.txt"),
    "result_file": os.path.expanduser("~/hermes_trade_result.txt"),
    "log_file": os.path.expanduser("~/hermes_crypto_trades.json"),
}

# Demo/testnet only by default. Override with BYBIT_DEMO=false env var for live.
DEMO_MODE = os.environ.get("BYBIT_DEMO", "true").lower() == "true"
CONFIG["demo"] = DEMO_MODE

session = HTTP(
    api_key=CONFIG["api_key"],
    api_secret=CONFIG["api_secret"],
    demo=CONFIG["demo"],
)

# ============================================================
# DATA FETCHING
# ============================================================
def get_klines(symbol, interval, limit):
    """Fetch OHLCV from Bybit. Interval: 1, 3, 5, 15, 30, 60, 120, 240, 360, 720, D, W, M"""
    k = session.get_kline(
        category="linear", symbol=symbol,
        interval=str(interval), limit=limit
    )
    df = pd.DataFrame(
        k["result"]["list"],
        columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"],
    )
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


# ============================================================
# TECHNICAL INDICATORS
# ============================================================
def add_rsi(df, period=14):
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).ewm(span=period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=period, adjust=False).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    return df

def add_macd(df, fast=12, slow=26, signal=9):
    df["MACD"] = df["close"].ewm(span=fast, adjust=False).mean() - df["close"].ewm(span=slow, adjust=False).mean()
    df["MACD_Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
    df["MACD_Dir"] = df["MACD_Hist"].apply(lambda x: "BULLISH" if x > 0 else "BEARISH")
    return df

def add_ema(df, periods=[10, 20, 50]):
    for p in periods:
        df[f"EMA_{p}"] = df["close"].ewm(span=p, adjust=False).mean()
    return df

def add_bollinger(df, period=20, std=2):
    df["BB_mid"] = df["close"].rolling(period).mean()
    bb_std = df["close"].rolling(period).std()
    df["BB_up"] = df["BB_mid"] + (bb_std * std)
    df["BB_low"] = df["BB_mid"] - (bb_std * std)
    df["BB_width"] = (df["BB_up"] - df["BB_low"]) / df["BB_mid"] * 100
    return df

def add_support_resistance(df, lookback=20):
    df["swing_high"] = df["high"].rolling(window=lookback, center=True).max()
    df["swing_low"] = df["low"].rolling(window=lookback, center=True).min()
    df["is_resistance"] = df["high"] == df["swing_high"]
    df["is_support"] = df["low"] == df["swing_low"]
    return df


# ============================================================
# ANALYSIS ENGINE
# ============================================================
def analyze_dataframe(df):
    """Apply all indicators to a dataframe and return latest analysis + signal."""
    df = add_rsi(df)
    df = add_macd(df)
    df = add_ema(df)
    df = add_bollinger(df)
    df = add_support_resistance(df)

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    # RSI signal
    if latest["RSI"] < 30:
        rsi_sig = "OVERSOLD"
    elif latest["RSI"] > 70:
        rsi_sig = "OVERBOUGHT"
    else:
        rsi_sig = "NEUTRAL"

    # BB signal
    if latest["close"] > latest["BB_up"]:
        bb_sig = "OVERBOUGHT"
    elif latest["close"] < latest["BB_low"]:
        bb_sig = "OVERSOLD"
    else:
        bb_sig = "NEUTRAL"

    ema_trend = "BULLISH" if latest["EMA_10"] > latest["EMA_50"] else "BEARISH"

    analysis = {
        "price": round(float(latest["close"]), 2),
        "open": round(float(latest["open"]), 2),
        "high": round(float(latest["high"]), 2),
        "low": round(float(latest["low"]), 2),
        "volume": float(latest["volume"]),
        "change_24h": round(float((latest["close"] - df.iloc[-24]["close"]) / df.iloc[-24]["close"] * 100), 2) if len(df) > 24 else 0,
        "rsi": round(float(latest["RSI"]), 1),
        "rsi_signal": rsi_sig,
        "macd_dir": latest["MACD_Dir"],
        "macd_hist": round(float(latest["MACD_Hist"]), 2),
        "ema_10": round(float(latest["EMA_10"]), 2),
        "ema_50": round(float(latest["EMA_50"]), 2),
        "ema_trend": ema_trend,
        "bb_up": round(float(latest["BB_up"]), 2),
        "bb_low": round(float(latest["BB_low"]), 2),
        "bb_width": round(float(latest["BB_width"]), 1),
        "bb_signal": bb_sig,
    }
    return analysis


def generate_signal(analysis):
    """Generate trading signal from analysis data."""
    score = 0
    reasons = []

    # RSI (weight: 2)
    if analysis["rsi_signal"] == "OVERSOLD":
        score += 2
        reasons.append(f"RSI oversold ({analysis['rsi']})")
    elif analysis["rsi_signal"] == "OVERBOUGHT":
        score -= 2
        reasons.append(f"RSI overbought ({analysis['rsi']})")

    # MACD (weight: 1)
    if analysis["macd_dir"] == "BULLISH":
        score += 1
        reasons.append("MACD bullish")
    else:
        score -= 1
        reasons.append("MACD bearish")

    # EMA Trend (weight: 1)
    if analysis["ema_trend"] == "BULLISH":
        score += 1
        reasons.append("EMA bullish")
    else:
        score -= 1
        reasons.append("EMA bearish")

    # Bollinger (weight: 1)
    if analysis["bb_signal"] == "OVERSOLD":
        score += 1
        reasons.append("BB oversold")
    elif analysis["bb_signal"] == "OVERBOUGHT":
        score -= 1
        reasons.append("BB overbought")

    # Classification
    if score >= 3:
        signal = "STRONG_BUY"
    elif score >= 1:
        signal = "BUY"
    elif score <= -3:
        signal = "STRONG_SELL"
    elif score <= -1:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    return {"signal": signal, "score": score, "reasons": reasons}


def full_analysis(symbol, interval_code, limit=None):
    """Complete pipeline: fetch → analyze → signal for one symbol/interval."""
    if limit is None:
        limit = CONFIG["limits"].get(interval_code, 150)
    df = get_klines(symbol, interval_code, limit)
    if len(df) < 50:
        return {"error": f"Insufficient data: {len(df)} candles"}
    analysis = analyze_dataframe(df)
    signal = generate_signal(analysis)
    return {"analysis": analysis, "signal": signal}


# ============================================================
# TRADING EXECUTION (via file-based bridge)
# ============================================================
def write_command(cmd):
    """Write command to bridge file."""
    with open(CONFIG["command_file"], "w") as f:
        f.write(cmd)

def read_result(timeout=5):
    """Read bridge result with timeout."""
    for _ in range(timeout):
        if os.path.exists(CONFIG["result_file"]):
            with open(CONFIG["result_file"], "r") as f:
                result = f.read().strip()
            os.remove(CONFIG["result_file"])
            return result
        time.sleep(1)
    return "TIMEOUT"

def execute_order(symbol, side, qty):
    """Send order via bridge and wait for result."""
    cmd = f"{side}|{symbol}|{qty}"
    write_command(cmd)
    result = read_result()
    return result

def get_balance():
    """Get current balance directly via API."""
    b = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
    data = b["result"]["list"][0]
    return {
        "balance": float(data["totalWalletBalance"]),
        "equity": float(data["totalEquity"]),
        "available": float(data["totalAvailableBalance"]),
    }

def get_positions():
    """Get open positions directly via API."""
    pos = session.get_positions(category="linear", settleCoin="USDT")
    result = []
    for p in pos["result"]["list"]:
        if float(p["size"]) > 0:
            result.append({
                "symbol": p["symbol"],
                "side": p["side"],
                "size": float(p["size"]),
                "entry": float(p["avgPrice"]),
                "pnl": float(p["unrealisedPnl"]),
            })
    return result


# ============================================================
# AUTONOMOUS DECISION ENGINE
# ============================================================
def autonomous_decision(multi_tf):
    """
    Decide whether to trade based on multi-timeframe analysis.
    Returns: {"action": "BUY"/"SELL"/"HOLD", "symbol": "...", "reason": "...", "qty": ...}
    """
    decisions = []

    for sym in multi_tf:
        daily = multi_tf[sym].get("D", {})
        h4 = multi_tf[sym].get(240, {})
        h1 = multi_tf[sym].get(60, {})
        m15 = multi_tf[sym].get(15, {})

        # Skip if any timeframe has errors
        if "error" in daily or "error" in h4 or "error" in h1:
            continue

        d_sig = daily.get("signal", {}).get("signal", "NEUTRAL")
        h4_sig = h4.get("signal", {}).get("signal", "NEUTRAL")
        h1_sig = h1.get("signal", {}).get("signal", "NEUTRAL")
        m15_sig = m15.get("signal", {}).get("signal", "NEUTRAL")

        # Strategy 1: Trend following (Daily + 4H confluent)
        if d_sig in ("BUY", "STRONG_BUY") and h4_sig in ("BUY", "STRONG_BUY"):
            decisions.append({
                "symbol": sym, "action": "BUY",
                "confidence": "HIGH", "qty": 0.001,
                "reason": f"Bullish confluent: Daily={d_sig}, 4H={h4_sig}, 1H={h1_sig}"
            })
        elif d_sig in ("SELL", "STRONG_SELL") and h4_sig in ("SELL", "STRONG_SELL"):
            decisions.append({
                "symbol": sym, "action": "SELL",
                "confidence": "HIGH", "qty": 0.001,
                "reason": f"Bearish confluent: Daily={d_sig}, 4H={h4_sig}, 1H={h1_sig}"
            })

        # Strategy 2: Squeeze breakout (BB narrow + momentum)
        h1_price = h1.get("analysis", {}).get("price", 0)
        h1_bb_w = h1.get("analysis", {}).get("bb_width", 100)
        if h1_bb_w < 3 and h1_sig in ("BUY", "STRONG_BUY"):
            decisions.append({
                "symbol": sym, "action": "BUY",
                "confidence": "MEDIUM", "qty": 0.001,
                "reason": f"BB squeeze ({h1_bb_w}%) + bullish momentum on 1H"
            })

        # Strategy 3: Reversal (RSI oversold on daily + 4H bounce)
        d_rsi = daily.get("analysis", {}).get("rsi", 50)
        if d_rsi < 35 and h4_sig in ("BUY", "STRONG_BUY"):
            decisions.append({
                "symbol": sym, "action": "BUY",
                "confidence": "MEDIUM", "qty": 0.001,
                "reason": f"Daily RSI oversold ({d_rsi}) + 4H bullish bounce"
            })

    if not decisions:
        return {"action": "HOLD", "symbol": list(multi_tf.keys())[0] if multi_tf else "BTCUSDT", "reason": "No clear signal across any timeframe confluence"}

    # Pick highest confidence decision
    conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    decisions.sort(key=lambda d: conf_order.get(d["confidence"], 99))
    return decisions[0]


# ============================================================
# FORMATTED OUTPUT
# ============================================================
def format_analysis(multi_tf):
    """Format multi-timeframe analysis for display."""
    lines = []
    lines.append(f"\n{'═'*60}")
    lines.append(f"  📊 CRYPTO MARKET ANALYSIS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"{'═'*60}")

    # Get all symbols from multi_tf (universal)
    all_symbols = list(multi_tf.keys()) if multi_tf else []
    
    # Sort by priority
    tier1 = CONFIG.get("tier1", [])
    def sort_key(sym):
        if sym in tier1:
            return (0, tier1.index(sym))
        return (1, sym)
    all_symbols.sort(key=sort_key)

    for sym in all_symbols:
        lines.append(f"\n  {'─'*56}")
        lines.append(f"  {sym}")
        lines.append(f"  {'─'*56}")

        for iv_code, iv_name in sorted(CONFIG["intervals"].items(), key=lambda x: str(x[0])):
            if iv_code not in multi_tf.get(sym, {}):
                continue
            entry = multi_tf[sym][iv_code]
            if "error" in entry:
                lines.append(f"  [{iv_name:5s}] ❌ {entry['error']}")
                continue

            a = entry.get("analysis", {})
            s = entry.get("signal", {})
            sig = s.get("signal", "?")
            score = s.get("score", 0)

            # Emoji
            if sig in ("STRONG_BUY", "BUY"):
                emoji = "🟢"
            elif sig in ("STRONG_SELL", "SELL"):
                emoji = "🔴"
            else:
                emoji = "⚪"

            line = (
                f"  {emoji} [{iv_name:5s}] ${a.get('price',0):>8.2f} | "
                f"RSI: {a.get('rsi',0):5.1f} {a.get('rsi_signal','?'):>10s} | "
                f"MACD: {a.get('macd_dir','?'):>8s} | "
                f"EMA: {a.get('ema_trend','?'):>8s} | "
                f"BB: {a.get('bb_signal','?'):>10s} (w:{a.get('bb_width',0):.1f}%)"
            )
            reason_str = ", ".join(s.get("reasons", []))
            lines.append(line)
            lines.append(f"  {'':8s}{sig:12s} (score: {score:+d}) → {reason_str}")

    # Summary
    lines.append(f"\n  {'─'*56}")
    bearish = sum(1 for sym in CONFIG["symbols"] if multi_tf.get(sym, {}).get("D", {}).get("signal", {}).get("signal") in ("SELL", "STRONG_SELL"))
    bullish = sum(1 for sym in CONFIG["symbols"] if multi_tf.get(sym, {}).get("D", {}).get("signal", {}).get("signal") in ("BUY", "STRONG_BUY"))
    lines.append(f"  📈 Daily Bias: 🟢{bullish} / 🔴{bearish} / ⚪{len(CONFIG['symbols'])-bullish-bearish}")
    lines.append(f"{'═'*60}")
    return "\n".join(lines)


def format_signal(symbol, action, reason):
    """Format trading signal for display."""
    if action == "HOLD":
        emoji = "⏸️"
    elif action == "BUY":
        emoji = "🟢"
    else:
        emoji = "🔴"
    return f"\n  🤖 AUTONOMOUS DECISION: {emoji} {action} {symbol}\n  📝 Reason: {reason}"


def log_trade(entry):
    """Log trade to persistent JSON file."""
    log = []
    if os.path.exists(CONFIG["log_file"]):
        try:
            with open(CONFIG["log_file"], "r") as f:
                log = json.load(f)
        except:
            log = []
    log.append(entry)
    with open(CONFIG["log_file"], "w") as f:
        json.dump(log, f, indent=2)


# ============================================================
# MAIN
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes Crypto Analysis & Trading")
    parser.add_argument("--trade", action="store_true", help="Execute autonomous trade if signal found")
    parser.add_argument("--symbol", type=str, default=None, help="Single symbol to analyze")
    parser.add_argument("--cron", type=str, default=None, help="Cron mode: daily, hourly")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    parser.add_argument("--setup", action="store_true", help="Check system readiness")
    parser.add_argument("--squeeze", type=str, default=None, help="BB squeeze scan for symbol")
    parser.add_argument("--portfolio", action="store_true", help="Scan portfolio for entry signals")
    args = parser.parse_args()
    
    if args.setup:
        # import json (already imported at top)
        s = setup_check()
        print(json.dumps(s, indent=2))
        return
    
    if args.squeeze:
        # import json (already imported at top)
        s = bb_squeeze_scan(args.squeeze)
        print(json.dumps(s, indent=2))
        return
    
    if args.symbol:
        symbols = [args.symbol]
    else:
        # Universal: fetch all USDT perpetuals from Bybit
        tickers = session.get_tickers(category="linear")
        all_symbols = []
        for t in tickers["result"]["list"]:
            if t["symbol"].endswith("USDT"):
                all_symbols.append(t["symbol"])
        
        # Sort by priority
        tier1 = CONFIG.get("tier1", [])
        def sort_key(sym):
            if sym in tier1:
                return (0, tier1.index(sym))
            return (1, sym)
        all_symbols.sort(key=sort_key)
        symbols = all_symbols

    # Run multi-timeframe analysis for all symbols
    multi_tf = {}
    for sym in symbols:
        multi_tf[sym] = {}
        for iv_code in CONFIG["intervals"]:
            result = full_analysis(sym, iv_code)
            multi_tf[sym][iv_code] = result

    # Display formatted analysis
    output = format_analysis(multi_tf)
    print(output)

    # Autonomous decision
    decision = autonomous_decision(multi_tf)
    print(f"\n{format_signal(decision['symbol'], decision['action'], decision['reason'])}")

    # Execute trade if --trade flag and signal found
    if args.trade and decision["action"] != "HOLD":
        sym = decision["symbol"]
        side = decision["action"]
        qty = decision["qty"]

        print(f"\n  🚀 Executing: {side} {qty} {sym}...")

        # Check balance first
        bal = get_balance()
        if bal["available"] < 10:
            print(f"  ❌ Insufficient balance: ${bal['available']:.2f} available")
            decision["status"] = "FAILED"
            decision["balance"] = bal
            log_trade(decision)
            sys.exit(1)

        result = execute_order(sym, side, qty)
        print(f"  Result: {result}")

        # Check position after trade
        time.sleep(2)
        positions = get_positions()
        print(f"  Positions: {len(positions)} open")
        for p in positions:
            print(f"    {p['symbol']} {p['side']} {p['size']} @ ${p['entry']} PnL: ${p['pnl']:.2f}")

        # Check new balance
        new_bal = get_balance()
        print(f"  Balance: ${new_bal['balance']:.2f} | Equity: ${new_bal['equity']:.2f}")

        decision["status"] = "EXECUTED"
        decision["result"] = result
        decision["positions"] = positions
        decision["balance_before"] = bal
        decision["balance_after"] = new_bal
        log_trade(decision)

    elif args.trade and decision["action"] == "HOLD":
        print("\n  ⏸️  No trade executed — market conditions not favorable")
        decision["status"] = "SKIPPED"
        decision["balance"] = get_balance()
        log_trade(decision)

    # Save full analysis to file if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump({"analysis": multi_tf, "decision": decision}, f, indent=2, default=str)
        print(f"\n  💾 Saved to {args.output}")

    # Cron mode: return structured data (no decorative chars)
    if args.cron:
        result = {"timestamp": datetime.now().isoformat(), "symbols": {}}
        for sym in symbols:
            result["symbols"][sym] = {}
            for iv_code in CONFIG["intervals"]:
                entry = multi_tf.get(sym, {}).get(iv_code, {})
                if "error" in entry:
                    result["symbols"][sym][str(iv_code)] = {"error": entry["error"]}
                else:
                    result["symbols"][sym][str(iv_code)] = {
                        "analysis": entry.get("analysis", {}),
                        "signal": entry.get("signal", {}),
                    }
        result["decision"] = decision
        print("\n---CRON_JSON---")
        # import json (already imported at top)\n        print(json.dumps(result))\n        return

    return multi_tf, decision


def bb_squeeze_scan(symbol="BTCUSDT"):
    """
    Multi-timeframe BB squeeze detector.
    Returns dict of squeeze levels for 1m/5m/15m/1h/4h.
    When 3+ timeframes show squeeze (BBw < 3%), breakout imminent.
    """
    timeframes = {1: "1m", 5: "5m", 15: "15m", 60: "1h", 240: "4h"}
    results = {}
    
    for iv_code, iv_name in timeframes.items():
        df = get_klines(symbol, iv_code, 100)
        bb_mid = df["close"].rolling(20).mean()
        bb_std = df["close"].rolling(20).std()
        bb_w = (bb_mid + 2*bb_std - (bb_mid - 2*bb_std)) / bb_mid * 100
        bw = bb_w.iloc[-1]
        
        if bw < 1: level = "💥 EXTREME"
        elif bw < 3: level = "💥 SQUEEZE"
        elif bw < 5: level = "⚠️ Tight"
        elif bw < 10: level = "Normal"
        else: level = "Wide"
        
        results[iv_name] = {"bb_width": round(bw, 2), "level": level}
    
    squeeze_count = sum(1 for v in results.values() if v["bb_width"] < 3)
    results["squeeze_count"] = squeeze_count
    results["verdict"] = "BREAKOUT SOON" if squeeze_count >= 3 else "Normal"
    return results


def setup_check():
    """
    Run this on first use by any AI model.
    Verifies everything is working and returns a status dict.
    """
    status = {"system": "Hermes Crypto Trading", "ready": False}
    
    # Check bridge
    import subprocess
    bridge_pid = subprocess.run(["pgrep", "-f", "hermes_bybit_bridge"],
                                capture_output=True, text=True).stdout.strip()
    status["bridge_running"] = bool(bridge_pid)
    status["bridge_pid"] = bridge_pid if bridge_pid else None
    
    # Check API connection
    try:
        b = get_balance()
        status["api_connected"] = True
        status["balance"] = b["balance"]
        status["equity"] = b["equity"]
    except:
        status["api_connected"] = False
    
    # Check positions
    try:
        positions = get_positions()
        status["active_positions"] = len(positions)
        status["positions"] = positions
    except:
        status["active_positions"] = 0
        status["positions"] = []
    
    # Check files
    for f in ["~/hermes_bybit_bridge.py", "~/hermes_crypto_analysis.py",
              "~/hermes_crypto_setup.sh"]:
        path = os.path.expanduser(f)
        status[os.path.basename(f)] = os.path.exists(path)
    
    status["ready"] = all([
        status.get("api_connected", False),
        status.get("bridge_running", False),
    ])
    
    return status


if __name__ == "__main__":
    main()
