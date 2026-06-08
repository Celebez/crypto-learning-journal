# Codex Trading System — Analysis Brief

## 🎯 Mission
Analyze and improve the crypto trading learning system. Fix all issues, optimize indicators, and create a production-ready system.

## 📊 Current State (Critical Issues)

### Learning Weights Analysis
```
Overall Accuracy: 6.67% (3/45 correct) — CRITICAL
Calibration Multiplier: 0.5 (UNRELIABLE tier)
Calibration Tier: UNRELIABLE
```

### Indicator Performance
| Indicator | Weight | Accuracy | Status |
|-----------|--------|----------|--------|
| RSI | 30 | 75% | ✅ Best performer |
| EMA 9/21 | 20 | 70% | ⚠️ Good but no signals tracked |
| Volume | 10 | 68% | ⚠️ No signals tracked |
| OI | 10 | 65% | ⚠️ No signals tracked |
| Funding Rate | 10 | 62% | ⚠️ No signals tracked |
| MACD | 5 | 30.5% | ❌ Poor |
| BB | 5 | 22.2% | ❌ Worst performer |

### Pattern Reliability
| Pattern | Weight | Reliability | Detections |
|---------|--------|-------------|------------|
| BB Squeeze | 15 | 0% | 3 (all failed) |
| EMA Cross | 12 | 68% | 0 |
| RSI Divergence | 12 | 65% | 0 |
| SR Flip | 15 | 75% | 0 |
| Volume Expansion | 10 | 70% | 0 |
| OI Expansion | 10 | 67% | 0 |
| Whale Accumulation | 8 | 63% | 0 |
| Whale Distribution | 8 | 61% | 0 |
| Taker Buy Dominance | 8 | 66% | 0 |
| Taker Sell Dominance | 8 | 64% | 0 |

### Prediction Registry
- Total: 13 predictions
- Status: 12 VERIFIED, 1 SUCCESS
- Problem: Very low success rate

## 🔍 Key Problems Identified

### 1. Calibration Death Spiral
- Multiplier dropped to 0.5 → predictions blocked
- Dynamic threshold fix implemented but not working effectively
- Need better recovery mechanism

### 2. BB Squeeze Pattern Failure
- 0% reliability (3 detections, all failed)
- Pattern weight too high (15) for poor performance
- Need to re-evaluate squeeze detection logic

### 3. MACD Signal Misclassification
- 30.5% accuracy — too many false signals
- Problem: Labeling any positive histogram as BULLISH_CROSS
- Need proper classification: CROSS vs RECOVERY vs CONTINUATION

### 4. Indicator Weight Imbalance
- RSI dominates (weight 30) but others underweighted
- EMA/Volume/OI have decent accuracy but weight 10-20
- Need dynamic weight adjustment based on actual performance

### 5. Pattern Detection Gap
- Most patterns have 0 detections
- BB Squeeze is the only one with detections (and it failed)
- Pattern detection logic may be too strict or misconfigured

## 📋 Required Improvements

### A. Confidence Calculation
1. Fix modifier values based on actual performance
2. Add dynamic modifiers that adapt to market conditions
3. Implement better calibration recovery mechanism

### B. Pattern Detection
1. Fix BB Squeeze detection (currently 0% success)
2. Add proper volume profile analysis
3. Implement multi-timeframe pattern confirmation

### C. Signal Classification
1. Fix MACD signal classification (CROSS vs RECOVERY)
2. Add confirmation requirements for signals
3. Implement signal strength scoring

### D. Risk Management
1. Add position sizing based on confidence
2. Implement dynamic stop-loss based on volatility
3. Add correlation-based risk limits

### E. Learning System
1. Fix calibration death spiral recovery
2. Add pattern-specific learning rates
3. Implement adaptive indicator weights

## 📁 Files to Analyze

### Data Files
- `data/learning_weights.json` — Current weights and accuracy
- `data/prediction_registry.json` — All predictions and outcomes
- `data/market_memory.json` — Market snapshots and positions
- `data/latest_snapshot.json` — Latest market scan

### Reference Files
- `references/confidence_calculation.md` — Confidence scoring rules
- `references/learning_rules.md` — Learning system rules
- `references/pitfalls-discovered.md` — Known issues and fixes
- `references/adaptive_thresholds.json` — Per-asset thresholds

### Scripts
- `scripts/predict_only_cycle.py` — Prediction generation
- `scripts/scan_and_predict_combined.py` — Full analysis cycle
- `scripts/verify_and_learn.py` — Verification and learning
- `scripts/pattern_detect.py` — Pattern detection engine

## 🎯 Success Criteria

1. **Accuracy Improvement**: Target 50%+ (from current 6.67%)
2. **Calibration Recovery**: Multiplier back to 0.85+ (MEDIUM tier)
3. **Pattern Detection**: At least 3 patterns with 60%+ reliability
4. **Signal Quality**: MACD accuracy above 60%
5. **Production Ready**: Clean code, proper error handling, documentation

## 🔧 Constraints

- Must work with Bybit API (pybit library)
- Must be model-agnostic (any AI can use the rules)
- Must handle API rate limits gracefully
- Must persist learning data to Redis + Supabase
- Must output Telegram-formatted reports
