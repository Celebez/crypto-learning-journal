# TRADING SYSTEM SEGMENTATION — CODEX INSTRUCTIONS

## MISSION
Refactor the monolithic trading system into 3 independent market segments:
1. **Crypto** — USDT perpetual contracts (Bybit)
2. **XAU** — Gold (XAU/USD)
3. **Forex** — Major currency pairs (EUR/USD, GBP/USD, etc.)

Each segment MUST have different:
- Indicators and parameters
- Risk management rules
- Analysis methods
- Confidence calculation weights

## EXISTING CODE TO REFACTOR

### Files in /home/ubuntu/codex-trading/:
- `improved_confidence.py` — Generic confidence calculator
- `improved_macd.py` — MACD classifier
- `improved_bb_squeeze.py` — BB Squeeze detector
- `improved_calibration.py` — Calibration manager
- `improved_risk.py` — Risk manager

### Backtest Data Available:
- `backtest/data/BTCUSDT_4h.csv` — 1000 bars
- `backtest/data/ETHUSDT_4h.csv` — 1000 bars
- `backtest/data/SOLUSDT_4h.csv` — 1000 bars
- `backtest/data/XAUUSDT_4h.csv` — 511 bars
- `backtest/data/BTCUSDT_1h.csv` — 1000 bars

## TARGET STRUCTURE

```
codex-trading/
├── shared/
│   ├── __init__.py
│   ├── confidence.py      # Base confidence (refactored from improved_confidence.py)
│   ├── macd.py            # Base MACD (refactored from improved_macd.py)
│   ├── bb_squeeze.py      # Base BB Squeeze (refactored from improved_bb_squeeze.py)
│   ├── calibration.py     # Base calibration (refactored from improved_calibration.py)
│   └── risk.py            # Base risk (refactored from improved_risk.py)
├── crypto/
│   ├── __init__.py
│   ├── confidence.py      # Crypto-specific confidence
│   ├── indicators.py      # Funding rate, sentiment, on-chain
│   ├── risk.py            # Crypto risk (2% per trade, 6% daily)
│   └── backtest.py        # Crypto backtester
├── xau/
│   ├── __init__.py
│   ├── confidence.py      # XAU-specific confidence
│   ├── indicators.py      # USD strength, safe haven, inflation
│   ├── risk.py            # XAU risk (1.5% per trade, 4% daily)
│   └── backtest.py        # XAU backtester
├── forex/
│   ├── __init__.py
│   ├── confidence.py      # Forex-specific confidence
│   ├── indicators.py      # Session, interest rate, correlation
│   ├── risk.py            # Forex risk (1% per trade, 3% daily)
│   └── backtest.py        # Forex backtester
└── backtest/
    └── run_all.py         # Run all backtests
```

## CRYPTO SEGMENT REQUIREMENTS

### Indicators:
1. **Funding Rate** — Positive = overleveraged longs, negative = overleveraged shorts
2. **Open Interest** — Rising OI + rising price = strong trend
3. **Taker Buy/Sell Ratio** — Taker buy > 60% = bullish pressure
4. **Liquidation Levels** — Price near liquidation = potential cascade
5. **Fear & Greed Index** — Extreme fear = buy signal, extreme greed = sell signal

### Risk Parameters:
- Max risk per trade: 2%
- Max daily loss: 6%
- Stop loss: 1-3% (ATR-based)
- Take profit: 1:2 risk-reward
- Position sizing: Based on notional value

### Confidence Weights:
- Funding rate: 1.2
- Open interest: 1.1
- Volume profile: 1.0
- MACD: 0.8
- RSI: 0.8
- BB Squeeze: 0.7
- Sentiment: 0.5

### Analysis Method:
- Multi-timeframe: Daily → 4H → 1H
- Focus on momentum and sentiment
- Funding rate contrarian signals
- Whale activity tracking

## XAU SEGMENT REQUIREMENTS

### Indicators:
1. **USD Strength (DXY)** — Inverse correlation with gold
2. **Real Yields** — Negative yields = bullish gold
3. **VIX** — High VIX = safe haven demand = bullish gold
4. **Inflation Expectations** — Rising inflation = bullish gold
5. **Central Bank Buying** — Net buyer = bullish gold

### Risk Parameters:
- Max risk per trade: 1.5%
- Max daily loss: 4%
- Stop loss: $5-15 (ATR-based)
- Take profit: 1:2.5 risk-reward
- Position sizing: Based on dollar value

### Confidence Weights:
- USD strength: 1.3
- Real yields: 1.2
- VIX correlation: 1.0
- MACD: 0.9
- RSI: 0.8
- BB Squeeze: 0.6
- Inflation: 0.5

### Analysis Method:
- Multi-timeframe: Daily → 4H → 1H
- Focus on USD correlation
- News event sensitivity (NFP, CPI, FOMC)
- Safe haven flow analysis

## FOREX SEGMENT REQUIREMENTS

### Indicators:
1. **Session Awareness** — Asian/London/NY sessions have different behaviors
2. **Interest Rate Differential** — Carry trade potential
3. **Economic Calendar** — High-impact news events
4. **Correlation** — EUR/USD vs GBP/USD correlation
5. **Spread Quality** — Wide spread = avoid trading

### Risk Parameters:
- Max risk per trade: 1%
- Max daily loss: 3%
- Stop loss: 20-50 pips (pair-dependent)
- Take profit: 1:2 risk-reward
- Position sizing: Based on pip value

### Confidence Weights:
- Session timing: 1.3
- Support/Resistance: 1.2
- Interest rate: 1.0
- MACD: 0.8
- RSI: 0.8
- BB Squeeze: 0.5
- Spread quality: gate (not score)

### Analysis Method:
- Multi-timeframe: Daily → 4H → 1H → 15M
- Focus on support/resistance levels
- Session-based entry timing
- News event avoidance (30 min before/after)

## BACKTEST REQUIREMENTS

Each segment MUST have its own backtester that:
1. Loads segment-specific data
2. Uses segment-specific indicators
3. Applies segment-specific risk rules
4. Generates segment-specific report

### Backtest Data:
- Crypto: Use `backtest/data/*_4h.csv` files
- XAU: Use `backtest/data/XAUUSDT_4h.csv`
- Forex: Create synthetic data or use OANDA API (if available)

### Output:
- Each segment produces independent results
- Combined summary in `backtest/reports/segment_summary.md`

## IMPLEMENTATION PRIORITY

1. **Crypto** — Data available, Bybit API connected
2. **XAU** — Data available from Bybit
3. **Forex** — Needs OANDA API or synthetic data

## SUCCESS CRITERIA

1. Each segment has independent code
2. Each segment uses market-appropriate indicators
3. Each segment has different risk parameters
4. Backtests run independently for each segment
5. Results are comparable and documented

## DO NOT

1. Do NOT modify the existing `improved_*.py` files
2. Do NOT mix learning system data with backtest data
3. Do NOT use generic parameters for all markets
4. Do NOT skip market-specific indicators

## CREATE

1. Create all new files in the structure above
2. Create backtest scripts for each segment
3. Create combined backtest runner
4. Generate documentation for each segment
