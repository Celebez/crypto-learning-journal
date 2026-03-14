#!/usr/bin/env python3
"""
Trading Statistics Logger v1.0
==============================
Tracks signal generation, win rate, profit factor, and false entries.
Run daily via cron to monitor performance after rule changes.

Usage:
  python3 hermes_trade_stats.py --log        # Log today's stats
  python3 hermes_trade_stats.py --report     # Generate report
  python3 hermes_trade_stats.py --history    # Show all logs
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List

STATS_FILE = os.path.expanduser("~/hermes_trade_stats.json")
TRADE_LOG = os.path.expanduser("~/hermes_auto_trades.json")
POSITIONS_FILE = os.path.expanduser("~/hermes_positions_snapshot.json")


def load_stats() -> Dict:
    """Load stats history."""
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            return json.load(f)
    return {"daily": [], "summary": {}}


def save_stats(stats: Dict):
    """Save stats history."""
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def get_positions() -> List[Dict]:
    """Get current positions from bridge."""
    try:
        sys.path.insert(0, os.path.expanduser("~"))
        from hermes_bybit_bridge import get_positions
        return get_positions()
    except Exception as e:
        print(f"Error getting positions: {e}")
        return []


def get_balance() -> Dict:
    """Get current balance."""
    try:
        sys.path.insert(0, os.path.expanduser("~"))
        from hermes_bybit_bridge import get_balance
        return get_balance()
    except Exception as e:
        print(f"Error getting balance: {e}")
        return {"equity": 0, "balance": 0}


def log_daily_stats():
    """Log today's trading statistics."""
    today = datetime.now().strftime("%Y-%m-%d")
    stats = load_stats()
    
    # Check if already logged today
    for day in stats["daily"]:
        if day["date"] == today:
            print(f"Already logged for {today}. Updating...")
            stats["daily"].remove(day)
            break
    
    # Get current positions
    positions = get_positions()
    balance = get_balance()
    
    # Calculate stats from positions
    total_pnl = sum(float(p.get("pnl", 0)) for p in positions)
    winning = [p for p in positions if float(p.get("pnl", 0)) > 0]
    losing = [p for p in positions if float(p.get("pnl", 0)) < 0]
    
    win_count = len(winning)
    loss_count = len(losing)
    total_trades = win_count + loss_count
    
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
    
    # Average win/loss
    avg_win = sum(float(p.get("pnl", 0)) for p in winning) / win_count if win_count > 0 else 0
    avg_loss = abs(sum(float(p.get("pnl", 0)) for p in losing) / loss_count) if loss_count > 0 else 1
    
    # R:R ratio
    avg_rr = avg_win / avg_loss if avg_loss > 0 else 0
    
    # Profit factor
    gross_profit = sum(float(p.get("pnl", 0)) for p in winning)
    gross_loss = abs(sum(float(p.get("pnl", 0)) for p in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999
    
    # Exposure
    equity = balance.get("equity", 0)
    exposure_pct = (abs(total_pnl) / equity * 100) if equity > 0 else 0
    
    # False entries (positions with loss > 1.5%)
    false_entries = [p for p in positions if float(p.get("pnl", 0)) < 0 and 
                     abs(float(p.get("pnl", 0))) / float(p.get("entry", 1)) * 100 > 1.5]
    
    day_stats = {
        "date": today,
        "timestamp": datetime.now().isoformat(),
        "positions": {
            "total": len(positions),
            "winning": win_count,
            "losing": loss_count,
        },
        "pnl": {
            "total": round(total_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
        },
        "metrics": {
            "win_rate": round(win_rate, 1),
            "avg_rr": round(avg_rr, 2),
            "profit_factor": round(profit_factor, 2),
            "false_entries": len(false_entries),
        },
        "balance": {
            "equity": round(equity, 2),
            "exposure_pct": round(exposure_pct, 1),
        },
        "signals": {
            "buy": 0,  # Will be updated by auto_trading log
            "sell": 0,
            "hold": 0,
        },
        "positions_detail": [
            {
                "symbol": p["symbol"],
                "side": p["side"],
                "pnl": round(float(p.get("pnl", 0)), 2),
                "entry": float(p.get("entry", 0)),
            }
            for p in positions
        ],
    }
    
    # Load signal counts from auto_trading log if available
    signal_log = os.path.expanduser("~/hermes_signal_log.json")
    if os.path.exists(signal_log):
        try:
            with open(signal_log) as f:
                signals = json.load(f)
            if today in signals:
                day_stats["signals"] = signals[today]
        except:
            pass
    
    stats["daily"].append(day_stats)
    
    # Keep only last 30 days
    stats["daily"] = stats["daily"][-30:]
    
    # Update summary
    if len(stats["daily"]) >= 3:
        recent = stats["daily"][-3:]
        stats["summary"] = {
            "avg_win_rate": round(sum(d["metrics"]["win_rate"] for d in recent) / len(recent), 1),
            "avg_profit_factor": round(sum(d["metrics"]["profit_factor"] for d in recent) / len(recent), 2),
            "avg_rr": round(sum(d["metrics"]["avg_rr"] for d in recent) / len(recent), 2),
            "total_false_entries": sum(d["metrics"]["false_entries"] for d in recent),
            "trend": "IMPROVING" if recent[-1]["metrics"]["profit_factor"] > recent[0]["metrics"]["profit_factor"] else "DECLINING",
        }
    
    save_stats(stats)
    
    # Print report
    print(f"\n📊 Stats logged for {today}")
    print(f"   Positions: {len(positions)} ({win_count}W / {loss_count}L)")
    print(f"   Win Rate: {win_rate:.1f}%")
    print(f"   Avg R:R: {avg_rr:.2f}")
    print(f"   Profit Factor: {profit_factor:.2f}")
    print(f"   False Entries: {len(false_entries)}")
    print(f"   Total PnL: ${total_pnl:+.2f}")
    print(f"   Equity: ${equity:.2f}")
    
    return day_stats


def generate_report() -> str:
    """Generate human-readable report."""
    stats = load_stats()
    
    if not stats["daily"]:
        return "No stats logged yet."
    
    report = []
    report.append("📊 TRADING STATISTICS REPORT")
    report.append("=" * 40)
    
    # Last 7 days
    recent = stats["daily"][-7:]
    
    for day in recent:
        m = day["metrics"]
        s = day["signals"]
        report.append(f"\n📅 {day['date']}")
        report.append(f"   Positions: {day['positions']['total']} ({day['positions']['winning']}W/{day['positions']['losing']}L)")
        report.append(f"   PnL: ${day['pnl']['total']:+.2f}")
        report.append(f"   Win Rate: {m['win_rate']}%")
        report.append(f"   R:R: {m['avg_rr']}")
        report.append(f"   Profit Factor: {m['profit_factor']}")
        report.append(f"   False Entries: {m['false_entries']}")
        report.append(f"   Signals: {s['buy']}B / {s['sell']}S / {s['hold']}H")
    
    # Summary
    if stats.get("summary"):
        sm = stats["summary"]
        report.append(f"\n{'=' * 40}")
        report.append(f"📈 3-DAY SUMMARY")
        report.append(f"   Avg Win Rate: {sm['avg_win_rate']}%")
        report.append(f"   Avg Profit Factor: {sm['avg_profit_factor']}")
        report.append(f"   Avg R:R: {sm['avg_rr']}")
        report.append(f"   Total False Entries: {sm['total_false_entries']}")
        report.append(f"   Trend: {sm['trend']}")
    
    # Alerts
    report.append(f"\n{'=' * 40}")
    report.append("⚠️ ALERTS")
    
    if len(recent) >= 2:
        latest = recent[-1]["metrics"]
        prev = recent[-2]["metrics"]
        
        if latest["profit_factor"] < prev["profit_factor"] * 0.8:
            report.append(f"   🔴 Profit Factor dropped: {prev['profit_factor']} → {latest['profit_factor']}")
            report.append(f"      → Threshold 55 might be too low")
        
        if latest["false_entries"] > prev["false_entries"] + 2:
            report.append(f"   🟡 False entries increased: {prev['false_entries']} → {latest['false_entries']}")
        
        if latest["win_rate"] < 40:
            report.append(f"   🔴 Win rate below 40%: {latest['win_rate']}%")
    
    return "\n".join(report)


def show_history():
    """Show all logged stats."""
    stats = load_stats()
    
    if not stats["daily"]:
        print("No stats logged yet.")
        return
    
    print("📊 STATS HISTORY")
    print(f"{'Date':<12} {'Pos':>4} {'W/L':>5} {'WR%':>6} {'R:R':>5} {'PF':>6} {'FE':>3} {'PnL':>10}")
    print("-" * 60)
    
    for day in stats["daily"]:
        m = day["metrics"]
        p = day["positions"]
        print(f"{day['date']:<12} {p['total']:>4} {p['winning']}/{p['losing']:>3} {m['win_rate']:>5.1f}% {m['avg_rr']:>5.2f} {m['profit_factor']:>6.2f} {m['false_entries']:>3} ${day['pnl']['total']:>+9.2f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: hermes_trade_stats.py [--log|--report|--history]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "--log":
        log_daily_stats()
    elif cmd == "--report":
        print(generate_report())
    elif cmd == "--history":
        show_history()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: hermes_trade_stats.py [--log|--report|--history]")
