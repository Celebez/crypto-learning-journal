"""
Telegram formatter for Mode 2 (4H full cycle) output.
Reads from /tmp/scan_result.json (scan_and_predict_combined.py output).
Usage: cd ~ cd ~ &&cd ~ && ~/.hermes-venv/bin/python3 /tmp/format_cycle.py

Handles camelCase ticker keys (lastPrice, price24hPcnt, etc.) from Bybit v5 API.
"""
import json
import sys

try:
    with open("/tmp/scan_result.json") as f:
        data = json.load(f)
except FileNotFoundError:
    print("ERROR: /tmp/scan_result.json not found")
    sys.exit(1)

port = data.get("portfolio", {})
analysis = data.get("analysis", {})
preds = data.get("new_predictions", [])
reg = data.get("registry_summary", {})
cal = data.get("calibration_multiplier", 0.7)
acc = data.get("accuracy_recalculated", 0.59)
expired = data.get("expired_removed", 0)

lines = []
lines.append("CRYPTO MONITOR v3.44 - 4H Full Cycle")
lines.append("Time: " + str(data.get("timestamp", "N/A"))[:19])
lines.append("")

# Portfolio
eq = port.get("equity", port.get("total_equity", "N/A"))
pnl_pct = port.get("pnl_pct", port.get("total_pnl_pct", "N/A"))
pos_count = port.get("positions_count", len(data.get("positions", [])))
lines.append("PORTFOLIO: $" + str(eq) + " | PnL: " + str(pnl_pct) + "% | Positions: " + str(pos_count))
lines.append("")

# Market Overview
lines.append("MARKET OVERVIEW (4H)")
lines.append("-" * 40)
for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]:
    info = analysis.get(sym, {})
    td = data.get("ticker_data", {}).get(sym, {})
    price = info.get("price", "N/A")
    rsi = info.get("rsi", 50)
    macd = info.get("macd_hist", 0)
    ema = info.get("ema_alignment", "N/A")
    patterns = info.get("patterns", [])
    chg = td.get("price24hPcnt", "N/A")

    rsi_label = "OVERSOLD" if rsi < 30 else "OVERBOUGHT" if rsi > 70 else "NEUTRAL"
    macd_label = "BEAR" if macd < 0 else "BULL"

    sym_short = sym.replace("USDT", "")
    line = sym_short + ": $" + str(price) + " (" + str(chg) + "%)"
    line += " | RSI:" + str(int(rsi)) + " " + rsi_label
    line += " | MACD:" + macd_label + " | EMA:" + ema
    if patterns:
        pat_str = ", ".join(str(p) if isinstance(p, str) else p.get("name", "?") for p in patterns)
        line += " | " + pat_str
    lines.append(line)
lines.append("")

# Predictions
lines.append("PREDICTIONS (" + str(len(preds)) + " new)")
lines.append("-" * 40)
for p in preds:
    sym = p.get("symbol", "N/A")
    direction = p.get("direction", "N/A")
    conf = p.get("confidence", "N/A")
    target = p.get("target_price", "N/A")
    inv = p.get("invalidation_price", "N/A")
    sig = "SELL" if direction == "BEARISH" else "BUY" if direction == "BULLISH" else "HOLD"
    forced = " [FORCED]" if p.get("forced") else ""
    sym_short = sym.replace("USDT", "")
    lines.append(sym_short + ": " + sig + " | Conf:" + str(conf) + " | Target:$" + str(target) + " | Inv:$" + str(inv) + forced)
lines.append("")

# Verification
vr = data.get("verification_results", [])
if vr:
    lines.append("VERIFICATION (" + str(len(vr)) + " results)")
    lines.append("-" * 40)
    for v in vr:
        sym = v.get("symbol", "N/A")
        result = v.get("result", "N/A")
        lines.append(sym + ": " + result)
    lines.append("")

# Learning
lines.append("LEARNING STATUS")
lines.append("-" * 40)
if cal >= 0.6:
    lines.append("Calibration: " + str(round(cal, 2)) + " (MEDIUM)")
else:
    lines.append("Calibration: " + str(round(cal, 2)) + " (LOW - death spiral risk)")
lines.append("Accuracy: " + str(round(acc * 100, 1)) + "%")
lines.append("Registry: " + str(reg.get("total", 0)) + " total | " + str(reg.get("pending", 0)) + " pending | " + str(reg.get("success", 0)) + " success | " + str(reg.get("expired", 0)) + " expired")
if expired > 0:
    lines.append("Cleaned: " + str(expired) + " old EXPIRED entries")
lines.append("")

# Risk Alerts
lines.append("RISK ALERTS")
lines.append("-" * 40)
oversold_count = sum(1 for s, info in analysis.items() if info.get("rsi", 50) < 30)
if oversold_count >= 4:
    lines.append("CRITICAL: " + str(oversold_count) + "/8 assets oversold (RSI<30)")
    lines.append("Market in deep selloff - extreme fear territory")
elif oversold_count >= 2:
    lines.append("WARNING: " + str(oversold_count) + "/8 assets oversold (RSI<30)")

btc_rsi = analysis.get("BTCUSDT", {}).get("rsi", 50)
if btc_rsi < 25:
    lines.append("BTC RSI at " + str(int(btc_rsi)) + " - historically extreme oversold")
lines.append("")

lines.append("--- End Report ---")

print("\n".join(lines))
