# Trading System Segmentation — Evaluation Request

## 🎯 Mission
Separate the monolithic trading system into 3 independent segments:
1. **Forex** — Major/minor currency pairs
2. **XAU** — Gold (XAU/USD)
3. **Crypto** — USDT perpetual contracts on Bybit

Each segment must have **different analysis methods, indicators, and risk parameters** because these markets behave fundamentally differently.

---

## 📊 Market Characteristics Comparison

### Forex (EUR/USD, GBP/USD, USD/JPY, etc.)
- **Trading hours:** 24/5 (Mon-Fri), most active during London & NY sessions
- **Volatility:** Low-Medium (1-2% daily range typical)
- **Spread:** Low (1-3 pips for majors)
- **Leverage:** Up to 1:500 (broker dependent)
- **Key drivers:** Interest rates, GDP, employment data, central bank policy
- **Correlation:** High within pairs (e.g., EUR/USD vs GBP/USD)
- **Session-based:** Asian, London, NY sessions have different behaviors
- **Spread cost:** Significant for scalping strategies

### XAU/USD (Gold)
- **Trading hours:** 24/5, but most active during London & NY overlap
- **Volatility:** Medium-High (1-3% daily range, can spike on news)
- **Spread:** Medium (2-5 cents)
- **Leverage:** Up to 1:500 (broker dependent)
- **Key drivers:** USD strength, inflation expectations, geopolitical risk, central bank buying
- **Safe haven:** Moves inversely to risk appetite
- **Correlation:** Negative with USD index, positive with inflation expectations
- **News sensitivity:** High impact on NFP, CPI, FOMC

### Crypto (BTC, ETH, SOL, etc.)
- **Trading hours:** 24/7/365
- **Volatility:** High (3-10% daily range common)
- **Spread:** Variable (0.01-0.1% for major pairs)
- **Leverage:** Up to 1:100 (exchange dependent)
- **Key drivers:** Adoption, regulation, on-chain metrics, whale activity, sentiment
- **Funding rate:** Unique to perpetual contracts
- **Correlation:** High within crypto market, low with traditional assets
- **Sentiment-driven:** Fear & Greed Index, social media, news

---

## 🔧 Current Code Analysis

### Files to Evaluate:
1. `improved_confidence.py` — Dynamic confidence calculation
2. `improved_macd.py` — MACD signal classification
3. `improved_bb_squeeze.py` — BB Squeeze detection
4. `improved_calibration.py` — Calibration recovery
5. `improved_risk.py` — Position sizing & risk management

### Current State:
- All modules are **generic** — no market-specific logic
- Indicators use **same parameters** for all markets
- Risk management uses **same thresholds** for all markets
- No **session awareness** for Forex
- No **funding rate** integration for Crypto
- No **safe haven** logic for XAU

---

## 📋 Segmentation Requirements

### A. Forex Segment

**Indicators to Add/Modify:**
1. **Session Awareness**
   - Asian session (00:00-08:00 UTC): Low volatility, range-bound
   - London session (08:00-16:00 UTC): Breakouts, trending
   - NY session (13:00-21:00 UTC): Continuation, news-driven
   - London-NY overlap (13:00-16:00 UTC): Highest volatility

2. **Interest Rate Differential**
   - Carry trade potential
   - Rate decision impact
   - Yield curve analysis

3. **Economic Calendar Integration**
   - High-impact news events (NFP, CPI, FOMC)
   - Pre/post news volatility adjustment
   - News-based position sizing

4. **Correlation Management**
   - EUR/USD vs GBP/USD correlation
   - USD/JPY vs USD/CHF correlation
   - Avoid over-exposure to USD

**Risk Parameters:**
- Max risk per trade: 1% (lower due to correlation)
- Max daily loss: 3%
- Stop loss: 20-50 pips (varies by pair)
- Take profit: 1:2 risk-reward minimum
- Position sizing: Based on pip value

**Analysis Method:**
- Multi-timeframe: Daily → 4H → 1H → 15M
- Focus on support/resistance levels
- Session-based entry timing
- News event avoidance (30 min before/after)

---

### B. XAU Segment

**Indicators to Add/Modify:**
1. **USD Strength Analysis**
   - DXY (Dollar Index) correlation
   - USD/JPY as USD proxy
   - Inverse relationship monitoring

2. **Safe Haven Demand**
   - VIX (Fear Index) correlation
   - Bond yield analysis (real yields)
   - Geopolitical risk events

3. **Inflation Expectations**
   - TIPS yield spread
   - CPI data impact
   - Central bank policy divergence

4. **Central Bank Activity**
   - Gold reserve changes
   - Physical demand (ETF flows)
   - Mining supply dynamics

**Risk Parameters:**
- Max risk per trade: 1.5%
- Max daily loss: 4%
- Stop loss: $5-15 (ATR-based)
- Take profit: 1:2.5 risk-reward minimum
- Position sizing: Based on dollar value

**Analysis Method:**
- Multi-timeframe: Daily → 4H → 1H
- Focus on USD correlation
- News event sensitivity (NFP, CPI, FOMC)
- Safe haven flow analysis

---

### C. Crypto Segment

**Indicators to Add/Modify:**
1. **On-Chain Metrics** (if available)
   - Exchange inflow/outflow
   - Whale wallet activity
   - Active addresses

2. **Funding Rate Analysis**
   - Positive funding = longs paying shorts (overleveraged longs)
   - Negative funding = shorts paying longs (overleveraged shorts)
   - Extreme funding = reversal signal

3. **Sentiment Analysis**
   - Fear & Greed Index
   - Social media sentiment
   - Google Trends

4. **Market Structure**
   - Liquidation levels
   - Open interest changes
   - Taker buy/sell ratio

**Risk Parameters:**
- Max risk per trade: 2% (higher due to volatility)
- Max daily loss: 6%
- Stop loss: 1-3% (ATR-based)
- Take profit: 1:2 risk-reward minimum
- Position sizing: Based on notional value

**Analysis Method:**
- Multi-timeframe: Daily → 4H → 1H → 15M
- Focus on momentum and sentiment
- Funding rate contrarian signals
- Whale activity tracking

---

## 🏗️ Proposed Architecture

### Option 1: Separate Modules (Recommended)
```
codex-trading/
├── shared/
│   ├── confidence.py          # Base confidence calculator
│   ├── calibration.py         # Base calibration manager
│   └── utils.py               # Common utilities
├── forex/
│   ├── __init__.py
│   ├── confidence.py          # Forex-specific confidence
│   ├── indicators.py          # Session, interest rate, correlation
│   ├── risk.py                # Forex risk parameters
│   └── analyzer.py            # Forex analysis engine
├── xau/
│   ├── __init__.py
│   ├── confidence.py          # XAU-specific confidence
│   ├── indicators.py          # USD strength, safe haven, inflation
│   ├── risk.py                # XAU risk parameters
│   └── analyzer.py            # XAU analysis engine
├── crypto/
│   ├── __init__.py
│   ├── confidence.py          # Crypto-specific confidence
│   ├── indicators.py          # Funding rate, sentiment, on-chain
│   ├── risk.py                # Crypto risk parameters
│   └── analyzer.py            # Crypto analysis engine
└── tests/
    ├── test_forex.py
    ├── test_xau.py
    └── test_crypto.py
```

### Option 2: Single Module with Config
```
codex-trading/
├── trading_engine.py          # Main engine with market config
├── configs/
│   ├── forex.yaml
│   ├── xau.yaml
│   └── crypto.yaml
└── indicators/
    ├── sessions.py
    ├── funding_rate.py
    └── sentiment.py
```

---

## ❓ Evaluation Questions for Codex

1. **Architecture:** Which option (separate modules vs config) is better for maintainability and testing?

2. **Indicator Design:** Should each segment have its own indicator implementations, or share base indicators with market-specific parameters?

3. **Confidence Calculation:** How should the confidence formula differ between markets? What weights should change?

4. **Risk Management:** What are the critical differences in risk parameters? Should stop loss calculation be market-specific?

5. **Backtesting:** How should we structure backtests for each market? What data sources are recommended?

6. **Integration:** How should these segments integrate with the existing Bybit (crypto) and OANDA (forex) APIs?

7. **Priority:** Which segment should be implemented first? Which has the highest edge potential?

8. **Code Reuse:** What percentage of current code can be reused vs rewritten?

9. **Testing Strategy:** How should we test each segment independently before live trading?

10. **Deployment:** Should segments run as separate processes or one unified system?

---

## 🎯 Success Criteria

1. **Separation:** Each segment is independent and can be tested/developed separately
2. **Specialization:** Each segment uses market-appropriate indicators and parameters
3. **Maintainability:** Changes to one segment don't break others
4. **Performance:** Each segment achieves >50% accuracy in backtesting
5. **Risk Management:** Each segment respects market-specific risk limits

---

## 📁 Files for Review

Please review the existing code in `/home/ubuntu/codex-trading/`:
- `improved_confidence.py` (11KB)
- `improved_macd.py` (17KB)
- `improved_bb_squeeze.py` (19KB)
- `improved_calibration.py` (16KB)
- `improved_risk.py` (21KB)
- `CODEX_EVALUATION.md` (previous evaluation)

Provide:
1. Architecture recommendation
2. Specific code changes needed for each segment
3. New indicator implementations required
4. Risk parameter differences
5. Priority order for implementation
