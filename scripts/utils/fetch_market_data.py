#!/usr/bin/env python3
"""
Fetch portfolio state and market data for all tracked assets.
Direct import from hermes_bybit_bridge — bypasses file bridge for reliability.

Usage:
  cd /home/ubuntu && /home/ubuntu/.hermes-venv/bin/python3 \
    ~/.hermes/skills/trading/crypto_portfolio_monitor_learning/scripts/fetch_market_data.py

Output: JSON to stdout with sections: PORTFOLIO, TICKERS, KLINES (4H), KLINES_1H, FUNDING, ORDERBOOK
"""
import sys, json
sys.path.insert(0, "/home/ubuntu")

from hermes_bybit_bridge import session, get_balance, get_positions

TRACKED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]

# 1. Portfolio
balance = get_balance()
positions = get_positions()
print("=== PORTFOLIO ===")
print(json.dumps({"balance": balance, "positions": positions}))

# 2. Tickers for all assets
print("\n=== TICKERS ===")
for sym in TRACKED:
    try:
        t = session.get_tickers(category="linear", symbol=sym)
        info = t["result"]["list"][0]
        print(json.dumps({
            "symbol": sym,
            "lastPrice": info.get("lastPrice"),
            "bid1Price": info.get("bid1Price"),
            "ask1Price": info.get("ask1Price"),
            "price24hPcnt": info.get("price24hPcnt"),
            "turnover24h": info.get("turnover24h"),
            "volume24h": info.get("volume24h"),
            "highPrice24h": info.get("highPrice24h"),
            "lowPrice24h": info.get("lowPrice24h"),
            "indexPrice": info.get("indexPrice"),
            "fundingRate": info.get("fundingRate"),
            "nextFundingTime": info.get("nextFundingTime"),
            "openInterest": info.get("openInterest"),
            "openInterestValue": info.get("openInterestValue"),
        }))
    except Exception as e:
        print(json.dumps({"symbol": sym, "error": str(e)}))

# 3. Kline data for indicator calc (4H, recent candles)
print("\n=== KLINES ===")
for sym in TRACKED:
    try:
        kl = session.get_kline(category="linear", symbol=sym, interval="240", limit=50)
        candles = []
        for c in kl["result"]["list"]:
            candles.append({
                "time": c[0], "open": c[1], "high": c[2],
                "low": c[3], "close": c[4], "volume": c[5], "turnover": c[6]
            })
        print(json.dumps({"symbol": sym, "candles": candles}))
    except Exception as e:
        print(json.dumps({"symbol": sym, "error": str(e)}))

# 4. 1H klines for short-term pattern detection
print("\n=== KLINES_1H ===")
for sym in TRACKED[:4]:  # BTC, ETH, SOL, XRP only
    try:
        kl = session.get_kline(category="linear", symbol=sym, interval="60", limit=50)
        candles = []
        for c in kl["result"]["list"]:
            candles.append({
                "time": c[0], "open": c[1], "high": c[2],
                "low": c[3], "close": c[4], "volume": c[5], "turnover": c[6]
            })
        print(json.dumps({"symbol": sym, "candles": candles}))
    except Exception as e:
        print(json.dumps({"symbol": sym, "error": str(e)}))

# 5. Funding rate history
print("\n=== FUNDING ===")
for sym in TRACKED:
    try:
        fr = session.get_funding_rate_history(category="linear", symbol=sym, limit=3)
        rates = [{"time": r.get("fundingRateTimestamp"), "rate": r.get("fundingRate")} for r in fr["result"]["list"]]
        print(json.dumps({"symbol": sym, "funding_history": rates}))
    except Exception as e:
        print(json.dumps({"symbol": sym, "error": str(e)}))

# 6. Orderbook depth for microstructure
print("\n=== ORDERBOOK ===")
for sym in ["BTCUSDT", "ETHUSDT"]:
    try:
        ob = session.get_orderbook(category="linear", symbol=sym, limit=20)
        bids = ob["result"]["b"][:10]
        asks = ob["result"]["a"][:10]
        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        spread = float(asks[0][0]) - float(bids[0][0])
        mid = (float(asks[0][0]) + float(bids[0][0])) / 2
        print(json.dumps({
            "symbol": sym,
            "bid_volume_total": bid_vol,
            "ask_volume_total": ask_vol,
            "spread": spread,
            "spread_pct": (spread / mid) * 100,
            "bid_ask_ratio": round(bid_vol / ask_vol, 2) if ask_vol > 0 else 0
        }))
    except Exception as e:
        print(json.dumps({"symbol": sym, "error": str(e)}))
