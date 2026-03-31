#!/usr/bin/env python3
"""
Telegram formatter for 15-min scan output.
Reads scan JSON from /tmp/scan_result.json (NOT stdin -- avoids pipe-to-interpreter security flag).

Workflow:
  1. Scan script writes JSON to /tmp/scan_result.json via stdout redirect
  2. This formatter reads from that file
  3. Run: cd /home/ubuntu && /home/ubuntu/.hermes-venv/bin/python3 /tmp/format_scan.py

No emoji -- safe for heredocs and Telegram delivery.

Handles BOTH output formats:
  - "analysis" key (scan_and_predict_combined.py, scan_observe_detect_robust.py)
  - "assets" key (scan_observe_detect.py non-robust)
Both use flat indicator keys at asset level (rsi, bb_width, macd_hist, ema_alignment, etc.)
"""
import json, sys

SCAN_FILE = "/tmp/scan_result.json"

try:
    with open(SCAN_FILE) as f:
        data = json.load(f)
except FileNotFoundError:
    print("ERROR: Scan data not found at " + SCAN_FILE)
    print("Run scan_observe_detect.py first and save output to " + SCAN_FILE)
    sys.exit(1)
except json.JSONDecodeError as e:
    print("ERROR: Invalid JSON in " + SCAN_FILE + ": " + str(e))
    sys.exit(1)

ts = data["timestamp"][:19].replace("T", " ")
portfolio = data["portfolio"]

lines = []
lines.append("SCAN -- " + ts)
lines.append("------------------------------")

# Portfolio -- handle both key naming conventions
eq = portfolio.get("total_equity", portfolio.get("equity", 0))
pnl = portfolio.get("total_pnl", portfolio.get("pnl_pct", 0))
positions = portfolio.get("positions", [])
pc = portfolio.get("positions_count", len(positions))

# fear_greed is a plain int/string from scan script (NOT a dict)
fg_raw = portfolio.get("fear_greed", 50)
fg_val = int(fg_raw) if fg_raw not in (None, "", "?") else 50
if fg_val <= 25:
    fg_label = "EXTREME FEAR"
elif fg_val <= 45:
    fg_label = "FEAR"
elif fg_val <= 55:
    fg_label = "NEUTRAL"
elif fg_val <= 75:
    fg_label = "GREED"
else:
    fg_label = "EXTREME GREED"

lines.append("Equity: $" + f"{eq:.2f}" + " | PnL: $" + f"{pnl:.2f}")
lines.append("Positions: " + str(pc) + " | Fear/Greed: " + str(fg_val) + " (" + fg_label + ")")
lines.append("------------------------------")

# Positions detail
if positions:
    lines.append("POSITIONS:")
    for p in positions:
        if isinstance(p, dict):
            entry_val = p.get("entry", p.get("avgPrice", 0))
            entry_str = "$" + f"{entry_val:.2f}" if entry_val and entry_val > 0 else "avgPrice=0"
            lines.append("  " + str(p.get("side","?")) + " " + str(p.get("symbol","?")) + " | Qty: " + str(p.get("size",0)) + " | Entry: " + entry_str)
    lines.append("------------------------------")

# Handle BOTH "analysis" and "assets" top-level keys
# Both use flat indicator keys: rsi, bb_width, macd_hist, ema_alignment, vol_ratio, patterns
assets_data = data.get("analysis", data.get("assets", {}))

lines.append("ANALYSIS:")
for sym, info in assets_data.items():
    if not isinstance(info, dict):
        continue
    if "error" in info:
        lines.append("  " + sym + ": ERROR - " + info["error"])
        continue

    price = info.get("price", 0)
    chg = info.get("change_24h", "?")

    # Indicators -- flat keys (both formats use same flat structure)
    rsi_val = info.get("rsi", info.get("indicators_4h", {}).get("rsi", 50))
    bb_w = info.get("bb_width", info.get("indicators_4h", {}).get("bb_width", 0))
    bb_sq = info.get("bb_squeeze", info.get("indicators_4h", {}).get("bb_squeeze", False))
    macd_h = info.get("macd_hist", info.get("indicators_4h", {}).get("macd_hist", 0))
    ema_align = info.get("ema_alignment", info.get("indicators_4h", {}).get("ema_alignment", "?"))
    vol = info.get("vol_ratio", 1)
    patterns = info.get("patterns", [])

    # Classify MACD
    if macd_h > 0.001:
        macd_label = "BULLISH"
    elif macd_h < -0.001:
        macd_label = "BEARISH"
    else:
        macd_label = "NEUTRAL"

    # Classify RSI
    if rsi_val < 30:
        rsi_label = "OVERSOLD"
    elif rsi_val > 70:
        rsi_label = "OVERBOUGHT"
    else:
        rsi_label = "NEUTRAL"

    sq_str = " [SQ]" if bb_sq else ""
    lines.append("  " + sym + ": $" + f"{price:,.4g}" + " (" + f"{chg}" + "%)")
    lines.append("    RSI: " + f"{rsi_val:.1f}" + " " + rsi_label + " | BB: " + f"{bb_w:.4f}" + sq_str + " | MACD: " + macd_label)
    lines.append("    EMA: " + ema_align + " | Vol: " + f"{vol:.2f}x")

    # Pattern names (patterns are dicts with "name" key, or flat strings)
    pattern_names = []
    for p in patterns:
        if isinstance(p, dict):
            pattern_names.append(p.get("name", "UNKNOWN"))
        elif isinstance(p, str):
            pattern_names.append(p)
    if pattern_names:
        lines.append("    Patterns: " + ", ".join(pattern_names))
    lines.append("")

lines.append("------------------------------")

# Patterns summary -- collect from ALL assets
all_patterns = []
for sym, info in assets_data.items():
    if isinstance(info, dict):
        for p in info.get("patterns", []):
            if isinstance(p, dict):
                all_patterns.append(p)
            elif isinstance(p, str):
                all_patterns.append({"name": p, "severity": "UNKNOWN"})

# Also check top-level patterns_detected (some scripts put patterns here)
for p in data.get("patterns_detected", []):
    if isinstance(p, dict):
        all_patterns.append(p)

if all_patterns:
    total = len(all_patterns)
    lines.append("Patterns Found: " + str(total))

    # Count by type
    type_counts = {}
    for p in all_patterns:
        name = p.get("name", "UNKNOWN")
        type_counts[name] = type_counts.get(name, 0) + 1
    for name, count in sorted(type_counts.items()):
        lines.append("  " + name + ": " + str(count))

    # Count by severity
    sev_counts = {}
    for p in all_patterns:
        sev = p.get("severity", "?")
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
    sev_str = " | ".join([k + ": " + str(v) for k, v in sorted(sev_counts.items())])
    lines.append("  Severity: " + sev_str)
else:
    lines.append("No patterns detected")

lines.append("------------------------------")

# Key signals
lines.append("KEY SIGNALS:")
high_patterns = [p for p in all_patterns if p.get("severity") == "HIGH"]
if high_patterns:
    for p in high_patterns:
        sym_name = p.get("symbol", "?")
        lines.append("  [HIGH] " + sym_name + ": " + p.get("name","?") + " - " + p.get("details", ""))
else:
    lines.append("  No HIGH severity signals")

squeeze_assets = [sym for sym, info in assets_data.items()
                  if isinstance(info, dict) and
                  (info.get("bb_squeeze", False) or info.get("bb_width", 1) < 0.02)]
if squeeze_assets:
    lines.append("  BB Squeeze Watch: " + ", ".join(squeeze_assets))

lines.append("------------------------------")

# Market bias
bear_count = sum(1 for s, d in assets_data.items()
                 if isinstance(d, dict) and
                 d.get("ema_alignment", d.get("indicators_4h", {}).get("ema_alignment")) in ("BEAR_ALIGNED", "BEARISH"))
bull_count = sum(1 for s, d in assets_data.items()
                 if isinstance(d, dict) and
                 d.get("ema_alignment", d.get("indicators_4h", {}).get("ema_alignment")) in ("BULL_ALIGNED", "BULLISH"))

if bear_count > 6:
    bias = "STRONG BEARISH (" + str(bear_count) + "/8 bear-aligned)"
elif bear_count > 4:
    bias = "BEARISH (" + str(bear_count) + "/8 bear-aligned)"
elif bull_count > 6:
    bias = "STRONG BULLISH (" + str(bull_count) + "/8 bull-aligned)"
elif bull_count > 4:
    bias = "BULLISH (" + str(bull_count) + "/8 bull-aligned)"
else:
    bias = "MIXED"

lines.append("Market Bias: " + bias)
lines.append("------------------------------")

print("\n".join(lines))
