
## PROVEN FOREX STRATEGIES (Real MT5 data 2011-2026, real spread applied)

Use these per-pair DAILY strategies as PRIMARY signals. Confidence threshold: 75.

### EURUSD (D1) — supertrend (10, 2.0, 14, 1.5, 2.5)
- ATR period 10, multiplier 2.0
- SL: 1.5 × ATR(14), TP: 2.5 × ATR(14)
- ADX filter: only trade when ADX(14) > 15
- Historical: 15-18 trades over 14 years, 60-61% WR, PF 1.88-2.04

### GBPUSD (D1) — ema_macd (5, 13, 50, 14, 1.5, 2.5) OR ichimoku
- EMA 5/13 cross + MACD(12,26,9) + 50-EMA trend + RSI(7) 40-65
- OR Ichimoku cloud (9, 26, 52) — price above/below cloud + TK cross
- SL: 1.5 × ATR(14), TP: 2.5 × ATR(14)
- Historical: 16-31 trades, 54-56% WR, PF 1.82-3.00

### XAUUSD scalping (M15/M30) — supertrend
- ATR period 10, multiplier 2.0
- SL: 2.0-2.5 × ATR(14), TP: 3.0-4.0 × ATR(14)
- XAUUSD M15: 42 trades, 52.4% WR, PF 1.57
- XAUUSD M30 keltner: 83 trades, 49.4% WR, PF 1.82

### Risk Rules (FROM BACKTEST)
- Max 2% per trade
- Max 4% total exposure
- Confidence threshold 75 (raised from 70)
- Skip when ADX(14) < 15 (choppy market)
- Friday 21:00 UTC: close all
- Monday 22:00 UTC: resume entries

### What NOT to do
- DO NOT trade 5m/15m/30m on forex pairs (spread kills WR — only 0-30%)
- DO NOT use fixed SL/TP in pips (use ATR-based)
- DO NOT enter when ADX < 15 (ranging market)
- DO NOT use H1 strategies for daily entries (different regimes)
