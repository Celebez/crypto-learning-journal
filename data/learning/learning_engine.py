#!/usr/bin/env python3
"""
Hermes Learning System v1.0
Gabungan: Prediction Logger + Accuracy Tracker + Daily Self-Review + Adaptive Confidence + Learning Journal

Cara pakai:
  python3 learning_engine.py --log "BTCUSDT" "BUY" 0.85 "RSI oversold + BB squeeze"
  python3 learning_engine.py --verify
  python3 learning_engine.py --review
  python3 learning_engine.py --status
  python3 learning_engine.py --journal "lesson learned here"
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from decimal import Decimal, ROUND_DOWN

# Paths
BASE_DIR = Path(__file__).parent
PREDICTIONS_FILE = BASE_DIR / "predictions.json"
SCORECARD_FILE = BASE_DIR / "scorecard.json"
JOURNAL_FILE = BASE_DIR / "journal.md"
CONFIG_FILE = BASE_DIR / "config.json"

# Default config
DEFAULT_CONFIG = {
    "confidence_thresholds": {
        "high": 0.80,
        "medium": 0.60,
        "low": 0.40
    },
    "accuracy_targets": {
        "minimum": 0.50,
        "good": 0.65,
        "excellent": 0.80
    },
    "adaptive_learning": {
        "enabled": True,
        "adjustment_rate": 0.05,
        "min_samples": 10
    },
    "token_priority": {
        "tier1": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "HYPEUSDT"],
        "tier2": "all_usdt_perpetuals"
    },
    "tracked_symbols": "universal"
}

def load_json(filepath, default=None):
    """Load JSON file, return default if not exists."""
    if filepath.exists():
        with open(filepath, 'r') as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(filepath, data):
    """Save data to JSON file."""
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def load_config():
    """Load config with defaults."""
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    # Merge with defaults for any missing keys
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
    return config

def log_prediction(symbol, action, confidence, reason):
    """Log a new prediction."""
    predictions = load_json(PREDICTIONS_FILE, {"predictions": [], "next_id": 1})
    
    pred_id = predictions["next_id"]
    prediction = {
        "id": pred_id,
        "symbol": symbol,
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "status": "pending",
        "result": None,
        "verified_at": None,
        "pnl": 0.0
    }
    
    predictions["predictions"].append(prediction)
    predictions["next_id"] = pred_id + 1
    save_json(PREDICTIONS_FILE, predictions)
    
    print(f"✅ Prediction #{pred_id} logged:")
    print(f"   Symbol: {symbol}")
    print(f"   Action: {action}")
    print(f"   Confidence: {confidence*100:.1f}%")
    print(f"   Reason: {reason}")
    
    return pred_id

def verify_predictions():
    """Verify pending predictions against actual prices."""
    from pybit.unified_trading import HTTP
    
    predictions = load_json(PREDICTIONS_FILE, {"predictions": [], "next_id": 1})
    config = load_config()
    
    session = HTTP(demo=True)
    
    verified_count = 0
    for pred in predictions["predictions"]:
        if pred["status"] != "pending":
            continue
        
        try:
            # Get current price
            ticker = session.get_tickers(category="linear", symbol=pred["symbol"])
            current_price = float(ticker["result"]["list"][0]["lastPrice"])
            
            # Get price at prediction time (approximate from klines)
            pred_time = datetime.fromisoformat(pred["timestamp"])
            hours_ago = (datetime.now() - pred_time).total_seconds() / 3600
            
            if hours_ago < 0.5:
                continue  # Too recent to verify
            
            # Get kline data
            klines = session.get_kline(
                category="linear",
                symbol=pred["symbol"],
                interval="60",
                limit=min(int(hours_ago) + 1, 100)
            )
            
            if not klines["result"]["list"]:
                continue
            
            # Find price at prediction time
            entry_price = None
            for k in klines["result"]["list"]:
                k_time = datetime.fromtimestamp(int(k[0]) / 1000)
                if k_time <= pred_time:
                    entry_price = float(k[1])  # Open price
                    break
            
            if entry_price is None:
                entry_price = float(klines["result"]["list"][-1][1])
            
            # Calculate result
            if pred["action"] in ["BUY", "STRONG_BUY"]:
                pnl_pct = (current_price - entry_price) / entry_price * 100
                correct = pnl_pct > 0
            elif pred["action"] in ["SELL", "STRONG_SELL"]:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                correct = pnl_pct > 0
            else:  # HOLD
                pnl_pct = 0
                correct = True  # HOLD is always "correct" if no big move
            
            # Update prediction
            pred["status"] = "verified"
            pred["result"] = "CORRECT" if correct else "WRONG"
            pred["pnl"] = round(pnl_pct, 4)
            pred["verified_at"] = datetime.now().isoformat()
            pred["entry_price"] = entry_price
            pred["current_price"] = current_price
            
            verified_count += 1
            
        except Exception as e:
            print(f"⚠️ Error verifying {pred['symbol']}: {e}")
            continue
    
    save_json(PREDICTIONS_FILE, predictions)
    
    if verified_count > 0:
        print(f"✅ Verified {verified_count} predictions")
        update_scorecard()
    else:
        print("ℹ️ No predictions ready for verification yet")
    
    return verified_count

def update_scorecard():
    """Update accuracy scorecard based on verified predictions."""
    predictions = load_json(PREDICTIONS_FILE, {"predictions": [], "next_id": 1})
    config = load_config()
    
    verified = [p for p in predictions["predictions"] if p["status"] == "verified"]
    
    if not verified:
        return
    
    # Overall stats
    total = len(verified)
    correct = len([p for p in verified if p["result"] == "CORRECT"])
    accuracy = correct / total if total > 0 else 0
    
    # Per-symbol stats
    symbol_stats = {}
    for pred in verified:
        sym = pred["symbol"]
        if sym not in symbol_stats:
            symbol_stats[sym] = {"total": 0, "correct": 0, "pnl": 0}
        symbol_stats[sym]["total"] += 1
        if pred["result"] == "CORRECT":
            symbol_stats[sym]["correct"] += 1
        symbol_stats[sym]["pnl"] += pred.get("pnl", 0)
    
    for sym in symbol_stats:
        s = symbol_stats[sym]
        s["accuracy"] = s["correct"] / s["total"] if s["total"] > 0 else 0
    
    # Per-action stats
    action_stats = {}
    for pred in verified:
        action = pred["action"]
        if action not in action_stats:
            action_stats[action] = {"total": 0, "correct": 0}
        action_stats[action]["total"] += 1
        if pred["result"] == "CORRECT":
            action_stats[action]["correct"] += 1
    
    for action in action_stats:
        s = action_stats[action]
        s["accuracy"] = s["correct"] / s["total"] if s["total"] > 0 else 0
    
    # Confidence calibration
    confidence_buckets = {"high": [], "medium": [], "low": []}
    for pred in verified:
        conf = pred["confidence"]
        if conf >= config["confidence_thresholds"]["high"]:
            confidence_buckets["high"].append(pred)
        elif conf >= config["confidence_thresholds"]["medium"]:
            confidence_buckets["medium"].append(pred)
        else:
            confidence_buckets["low"].append(pred)
    
    calibration = {}
    for bucket, preds in confidence_buckets.items():
        if preds:
            actual_acc = len([p for p in preds if p["result"] == "CORRECT"]) / len(preds)
            avg_conf = sum(p["confidence"] for p in preds) / len(preds)
            calibration[bucket] = {
                "count": len(preds),
                "avg_confidence": round(avg_conf, 3),
                "actual_accuracy": round(actual_acc, 3),
                "overconfident": avg_conf > actual_acc + 0.1,
                "underconfident": actual_acc > avg_conf + 0.1
            }
    
    # Build scorecard
    scorecard = {
        "updated_at": datetime.now().isoformat(),
        "overall": {
            "total_predictions": total,
            "correct": correct,
            "accuracy": round(accuracy, 3),
            "total_pnl": round(sum(p.get("pnl", 0) for p in verified), 4)
        },
        "by_symbol": symbol_stats,
        "by_action": action_stats,
        "confidence_calibration": calibration,
        "performance_rating": (
            "EXCELLENT" if accuracy >= config["accuracy_targets"]["excellent"]
            else "GOOD" if accuracy >= config["accuracy_targets"]["good"]
            else "NEEDS_WORK" if accuracy >= config["accuracy_targets"]["minimum"]
            else "POOR"
        )
    }
    
    save_json(SCORECARD_FILE, scorecard)
    
    # Adaptive threshold adjustment
    if config["adaptive_learning"]["enabled"] and total >= config["adaptive_learning"]["min_samples"]:
        adjust_thresholds(scorecard, config)
    
    return scorecard

def adjust_thresholds(scorecard, config):
    """Adaptively adjust confidence thresholds based on performance."""
    calibration = scorecard.get("confidence_calibration", {})
    adjustment_rate = config["adaptive_learning"]["adjustment_rate"]
    
    adjusted = False
    
    # If high-confidence predictions are overconfident, raise the threshold
    if calibration.get("high", {}).get("overconfident"):
        old = config["confidence_thresholds"]["high"]
        config["confidence_thresholds"]["high"] = min(0.95, old + adjustment_rate)
        adjusted = True
        print(f"📊 Adjusted HIGH threshold: {old:.2f} → {config['confidence_thresholds']['high']:.2f}")
    
    # If low-confidence predictions are underconfident, lower the threshold
    if calibration.get("low", {}).get("underconfident"):
        old = config["confidence_thresholds"]["low"]
        config["confidence_thresholds"]["low"] = max(0.20, old - adjustment_rate)
        adjusted = True
        print(f"📊 Adjusted LOW threshold: {old:.2f} → {config['confidence_thresholds']['low']:.2f}")
    
    if adjusted:
        save_json(CONFIG_FILE, config)

def daily_review():
    """Generate daily self-review."""
    predictions = load_json(PREDICTIONS_FILE, {"predictions": [], "next_id": 1})
    scorecard = load_json(SCORECARD_FILE, {})
    config = load_config()
    
    today = datetime.now().date()
    today_preds = [
        p for p in predictions["predictions"]
        if datetime.fromisoformat(p["timestamp"]).date() == today
    ]
    
    today_verified = [p for p in today_preds if p["status"] == "verified"]
    today_correct = len([p for p in today_verified if p["result"] == "CORRECT"])
    
    # Generate review
    review = []
    review.append(f"📊 **DAILY REVIEW — {today.strftime('%Y-%m-%d')}**")
    review.append("=" * 50)
    review.append("")
    
    # Today's summary
    review.append(f"**Prediksi hari ini:** {len(today_preds)}")
    review.append(f"**Terverifikasi:** {len(today_verified)}")
    review.append(f"**Akurasi hari ini:** {today_correct}/{len(today_verified)} ({today_correct/len(today_verified)*100:.1f}%)" if today_verified else "**Belum ada yang terverifikasi**")
    review.append("")
    
    # Overall performance
    if scorecard:
        overall = scorecard.get("overall", {})
        review.append(f"**Keseluruhan:**")
        review.append(f"  Total: {overall.get('total_predictions', 0)} prediksi")
        review.append(f"  Akurasi: {overall.get('accuracy', 0)*100:.1f}%")
        review.append(f"  Rating: {scorecard.get('performance_rating', 'N/A')}")
        review.append(f"  Total PnL: {overall.get('total_pnl', 0):.4f}%")
        review.append("")
    
    # Today's predictions detail
    if today_preds:
        review.append("**Detail prediksi hari ini:**")
        for pred in today_preds:
            status_icon = "✅" if pred["result"] == "CORRECT" else "❌" if pred["result"] == "WRONG" else "⏳"
            review.append(f"  {status_icon} #{pred['id']} {pred['symbol']} {pred['action']} ({pred['confidence']*100:.0f}%) → {pred.get('pnl', 0):+.2f}%")
        review.append("")
    
    # Lessons learned (auto-detect patterns)
    lessons = detect_patterns(predictions)
    if lessons:
        review.append("**Pelajaran:**")
        for lesson in lessons:
            review.append(f"  • {lesson}")
        review.append("")
    
    # Write to journal
    journal_entry = "\n".join(review)
    append_to_journal(journal_entry)
    
    # Print for cronjob
    print(journal_entry)
    
    return journal_entry

def detect_patterns(predictions):
    """Detect patterns in predictions for lessons learned."""
    verified = [p for p in predictions["predictions"] if p["status"] == "verified"]
    if len(verified) < 10:
        return []
    
    lessons = []
    
    # Check if overconfident
    high_conf = [p for p in verified if p["confidence"] >= 0.8]
    if high_conf:
        high_acc = len([p for p in high_conf if p["result"] == "CORRECT"]) / len(high_conf)
        if high_acc < 0.6:
            lessons.append(f"High confidence ({len(high_conf)} predictions) hanya {high_acc*100:.0f}% akurat — kurangi confidence threshold")
    
    # Check per-symbol accuracy
    symbol_perf = {}
    for p in verified:
        sym = p["symbol"]
        if sym not in symbol_perf:
            symbol_perf[sym] = {"correct": 0, "total": 0}
        symbol_perf[sym]["total"] += 1
        if p["result"] == "CORRECT":
            symbol_perf[sym]["correct"] += 1
    
    for sym, stats in symbol_perf.items():
        acc = stats["correct"] / stats["total"]
        if acc < 0.4 and stats["total"] >= 5:
            lessons.append(f"{sym} akurasi rendah ({acc*100:.0f}%) — hindari atau perbaiki strategi")
        elif acc > 0.8 and stats["total"] >= 5:
            lessons.append(f"{sym} akurasi tinggi ({acc*100:.0f}%) — pertahankan strategi")
    
    # Check action accuracy
    action_perf = {}
    for p in verified:
        action = p["action"]
        if action not in action_perf:
            action_perf[action] = {"correct": 0, "total": 0}
        action_perf[action]["total"] += 1
        if p["result"] == "CORRECT":
            action_perf[action]["correct"] += 1
    
    for action, stats in action_perf.items():
        acc = stats["correct"] / stats["total"]
        if acc < 0.4 and stats["total"] >= 5:
            lessons.append(f"Action '{action}' akurasi rendah ({acc*100:.0f}%) — evaluasi entry conditions")
    
    return lessons

def append_to_journal(entry):
    """Append entry to learning journal."""
    with open(JOURNAL_FILE, 'a') as f:
        f.write(f"\n{entry}\n")

def add_journal_entry(lesson):
    """Manually add a lesson to journal."""
    entry = f"\n📝 **MANUAL ENTRY — {datetime.now().strftime('%Y-%m-%d %H:%M')}**\n{lesson}\n"
    append_to_journal(entry)
    print(f"✅ Lesson added to journal")

def get_all_symbols():
    """Get all USDT perpetual symbols from Bybit, sorted by priority."""
    try:
        from pybit.unified_trading import HTTP
        session = HTTP(demo=True)
        tickers = session.get_tickers(category="linear")
        
        all_symbols = []
        for t in tickers["result"]["list"]:
            if t["symbol"].endswith("USDT"):
                all_symbols.append(t["symbol"])
        
        # Sort by priority: tier1 first, then alphabetical
        config = load_config()
        tier1 = config.get("token_priority", {}).get("tier1", [])
        
        def sort_key(sym):
            if sym in tier1:
                return (0, tier1.index(sym))
            return (1, sym)
        
        all_symbols.sort(key=sort_key)
        return all_symbols
    except Exception as e:
        print(f"⚠️ Error fetching symbols: {e}")
        return []

def show_status():
    """Show current learning system status."""
    predictions = load_json(PREDICTIONS_FILE, {"predictions": [], "next_id": 1})
    scorecard = load_json(SCORECARD_FILE, {})
    config = load_config()
    
    total = len(predictions["predictions"])
    pending = len([p for p in predictions["predictions"] if p["status"] == "pending"])
    verified = len([p for p in predictions["predictions"] if p["status"] == "verified"])
    
    print("📊 **HERMES LEARNING SYSTEM STATUS**")
    print("=" * 50)
    print(f"Total predictions: {total}")
    print(f"Pending: {pending}")
    print(f"Verified: {verified}")
    print()
    
    # Show token priority
    tier1 = config.get("token_priority", {}).get("tier1", [])
    print(f"**Token Priority:**")
    print(f"  Tier 1: {', '.join(tier1)}")
    print(f"  Tier 2: All USDT perpetuals (universal)")
    print()
    
    if scorecard:
        overall = scorecard.get("overall", {})
        print(f"**Performance:**")
        print(f"  Accuracy: {overall.get('accuracy', 0)*100:.1f}%")
        print(f"  Rating: {scorecard.get('performance_rating', 'N/A')}")
        print(f"  Total PnL: {overall.get('total_pnl', 0):.4f}%")
        print()
        
        # Show calibration
        cal = scorecard.get("confidence_calibration", {})
        if cal:
            print("**Confidence Calibration:**")
            for bucket, stats in cal.items():
                status = "⚠️ OVERCONFIDENT" if stats.get("overconfident") else "⚠️ UNDERCONFIDENT" if stats.get("underconfident") else "✅"
                print(f"  {bucket}: {stats['actual_accuracy']*100:.0f}% actual vs {stats['avg_confidence']*100:.0f}% predicted {status}")
    else:
        print("No scorecard yet — need more verified predictions")
    
    print()
    print(f"**Config:**")
    print(f"  HIGH threshold: {config['confidence_thresholds']['high']*100:.0f}%")
    print(f"  MEDIUM threshold: {config['confidence_thresholds']['medium']*100:.0f}%")
    print(f"  LOW threshold: {config['confidence_thresholds']['low']*100:.0f}%")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    command = sys.argv[1]
    
    if command == "--log":
        if len(sys.argv) < 6:
            print("Usage: --log SYMBOL ACTION CONFIDENCE REASON")
            return
        symbol = sys.argv[2]
        action = sys.argv[3]
        confidence = float(sys.argv[4])
        reason = " ".join(sys.argv[5:])
        log_prediction(symbol, action, confidence, reason)
    
    elif command == "--verify":
        verify_predictions()
    
    elif command == "--review":
        daily_review()
    
    elif command == "--status":
        show_status()
    
    elif command == "--journal":
        if len(sys.argv) < 3:
            print("Usage: --journal 'lesson learned'")
            return
        lesson = " ".join(sys.argv[2:])
        add_journal_entry(lesson)
    
    elif command == "--update-scorecard":
        scorecard = update_scorecard()
        if scorecard:
            print(json.dumps(scorecard, indent=2))
    
    else:
        print(f"Unknown command: {command}")
        print(__doc__)

if __name__ == "__main__":
    main()
