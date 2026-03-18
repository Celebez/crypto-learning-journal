#!/usr/bin/env python3
"""
Hermes Bybit Bridge - Trading via Bybit Demo API
Menggantikan MT5 + EA + Wine sepenuhnya
"""
from pybit.unified_trading import HTTP
import json, os, time

CONFIG = {
    "api_key": os.environ.get("BYBIT_API_KEY", "REPLACE_WITH_YOUR_DEMO_KEY"),
    "api_secret": os.environ.get("BYBIT_API_SECRET", "REPLACE_WITH_YOUR_DEMO_SECRET"),
    "command_file": os.path.expanduser("~/hermes_trade_command.txt"),
    "result_file": os.path.expanduser("~/hermes_trade_result.txt"),
    "category": "linear",  # linear = USDT perpetuals
    "default_symbol": "BTCUSDT",
}

# Demo/testnet only. For live trading, set BYBIT_API_KEY and BYBIT_API_SECRET
# env vars and remove the demo=True flag below.
DEMO_MODE = os.environ.get("BYBIT_DEMO", "true").lower() == "true"
session = HTTP(api_key=CONFIG["api_key"], api_secret=CONFIG["api_secret"], demo=DEMO_MODE)

def get_balance():
    bal = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
    data = bal["result"]["list"][0]
    coins = {c["coin"]: c for c in data["coin"]}
    usdt = coins.get("USDT", {})
    return {
        "balance": float(data["totalWalletBalance"]),
        "equity": float(data["totalEquity"]),
        "available": float(data["totalAvailableBalance"]),
        "usdt_balance": float(usdt.get("walletBalance", 0)),
        "usdt_equity": float(usdt.get("equity", 0)),
    }

def get_positions():
    pos = session.get_positions(category=CONFIG["category"], settleCoin="USDT")
    result = []
    for p in pos["result"]["list"]:
        if float(p["size"]) > 0:
            result.append({
                "symbol": p["symbol"],
                "side": p["side"],
                "size": float(p["size"]),
                "entry": float(p["avgPrice"]),
                "mark": float(p["markPrice"]),
                "pnl": float(p["unrealisedPnl"]),
                "leverage": float(p["leverage"]),
            })
    return result

def get_price(symbol):
    ticker = session.get_tickers(category=CONFIG["category"], symbol=symbol)
    t = ticker["result"]["list"][0]
    return {
        "symbol": t["symbol"],
        "bid": float(t["bid1Price"]),
        "ask": float(t["ask1Price"]),
        "last": float(t["lastPrice"]),
        "change_24h": f"{float(t['price24hPcnt'])*100:.2f}%",
    }

def place_order(symbol, side, qty, tp=None, sl=None):
    order = session.place_order(
        category=CONFIG["category"],
        symbol=symbol,
        side=side.capitalize(),  # Buy or Sell
        orderType="Market",
        qty=str(qty),
        timeInForce="IOC",
    )
    return order

def close_position(symbol):
    pos = session.get_positions(category=CONFIG["category"], symbol=symbol)
    for p in pos["result"]["list"]:
        if float(p["size"]) > 0:
            side = "Sell" if p["side"] == "Buy" else "Buy"
            order = session.place_order(
                category=CONFIG["category"],
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=p["size"],
                timeInForce="IOC",
            )
            return order
    return {"error": "No position found"}

def close_all():
    positions = get_positions()
    results = []
    for p in positions:
        r = close_position(p["symbol"])
        results.append({"symbol": p["symbol"], "result": r})
    return results

def process_command(cmd):
    cmd = cmd.strip().upper()
    parts = cmd.split("|")
    action = parts[0]
    
    if action == "BALANCE":
        b = get_balance()
        return f"OK|BALANCE|{b['balance']:.2f}|{b['equity']:.2f}|{b['available']:.2f}"
    
    elif action == "POSITIONS":
        positions = get_positions()
        if not positions:
            return "OK|POSITIONS|NO_POSITIONS"
        result = "OK|POSITIONS"
        for p in positions:
            result += f"|{p['symbol']},{p['side']},{p['size']},{p['entry']},{p['pnl']:.2f}"
        return result
    
    elif action == "PRICE" and len(parts) >= 2:
        p = get_price(parts[1])
        return f"OK|PRICE|{p['symbol']}|Bid:{p['bid']}|Ask:{p['ask']}|Last:{p['last']}|{p['change_24h']}"
    
    elif action == "BUY" and len(parts) >= 4:
        sym = parts[1]
        qty = float(parts[2])
        result = place_order(sym, "Buy", qty)
        if result["retCode"] == 0:
            return f"OK|BUY|{sym}|{qty}"
        return f"ERROR|{result['retMsg']}"
    
    elif action == "SELL" and len(parts) >= 4:
        sym = parts[1]
        qty = float(parts[2])
        result = place_order(sym, "Sell", qty)
        if result["retCode"] == 0:
            return f"OK|SELL|{sym}|{qty}"
        return f"ERROR|{result['retMsg']}"
    
    elif action == "CLOSE" and len(parts) >= 2:
        result = close_position(parts[1])
        return f"OK|CLOSED|{parts[1]}"
    
    elif action == "CLOSE_ALL":
        results = close_all()
        return f"OK|CLOSE_ALL|{len(results)} positions closed"
    
    elif action == "HELP":
        return ("OK|COMMANDS: BALANCE, POSITIONS, PRICE|SYMBOL, "
                "BUY|SYMBOL|QTY|SL, SELL|SYMBOL|QTY|SL, "
                "CLOSE|SYMBOL, CLOSE_ALL, HELP")
    
    return f"ERROR|Unknown command: {action}"

def watch_loop():
    print("🚀 Hermes Bybit Bridge started")
    print(f"📁 Watching: {CONFIG['command_file']}")
    
    while True:
        try:
            if os.path.exists(CONFIG["command_file"]):
                with open(CONFIG["command_file"], "r") as f:
                    cmd = f.read().strip()
                
                if cmd:
                    print(f"📩 Command: {cmd}")
                    result = process_command(cmd)
                    print(f"📨 Result: {result}")
                    
                    with open(CONFIG["result_file"], "w") as f:
                        f.write(result)
                    
                    os.remove(CONFIG["command_file"])
        except Exception as e:
            print(f"❌ Error: {e}")
        
        time.sleep(1)

if __name__ == "__main__":
    # Test connection first
    try:
        b = get_balance()
        print(f"✅ Connected! Balance: ${b['balance']:.2f}")
        watch_loop()
    except Exception as e:
        print(f"❌ Connection failed: {e}")
