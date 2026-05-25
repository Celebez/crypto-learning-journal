#!/usr/bin/env python3
"""Paper trade forward test — 30 hari out-of-sample dengan Yahoo H1/H4 + M15/M30.
Simulasi forex-sistem cron: cek signal 5-menit, virtual fill, track PnL semua 3 slot."""
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta

DATA_DIR = 'backtest/data/yahoo_h1h4'
RESULTS_DIR = 'backtest/results_yahoo_h1h4'
os.makedirs(RESULTS_DIR, exist_ok=True)

SPREADS = {
    'XAUUSD': 0.28, 'USDJPY': 2.7, 'USDCAD': 1.8, 'USDCHF': 2.0, 'NZDUSD': 2.5,
}

# 3-SLOT CONFIG (FINAL v4 — slot 2 = USDJPY H4 BB Squeeze)
SLOTS = {
    1: {'symbol': 'XAUUSD', 'tf': 'M15', 'strategy': 'supertrend',
        'params': {'period': 10, 'mult': 2.0, 'sl': 1.5, 'tp': 2.5}, 'weight': 0.4},
    2: {'symbol': 'USDJPY', 'tf': 'H4', 'strategy': 'bbsq',
        'params': {'n': 20, 'std_n': 2.0, 'sl': 2.0, 'tp': 3.0}, 'weight': 0.4},
    3: {'symbol': 'FLEX', 'tf': 'FLEX', 'strategy': 'ai_choice',
        'params': {}, 'weight': 0.2},  # AI will pick from validated pool
}

# Risk management
RISK_PCT = 0.02  # 2% per trade
MAX_POSITIONS = 3
PIP_VALUES = {'XAUUSD': 0.01, 'USDJPY': 0.01, 'USDCAD': 0.0001, 'USDCHF': 0.0001}

def load_data(symbol, tf):
    fname = f"{DATA_DIR}/{symbol}_{tf}.csv"
    if not os.path.exists(fname): return None
    df = pd.read_csv(fname, index_col=0)
    # Try parse dates, handle mixed timezones
    try:
        df.index = pd.to_datetime(df.index, utc=True)
        df.index = df.index.tz_convert(None)
    except Exception:
        df.index = pd.to_datetime(df.index)
    return df

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()
def atr(df, n=14):
    h = df['High']; l = df['Low']; c = df['Close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()
def adx(df, n=14):
    h = df['High']; l = df['Low']; c = df['Close']
    up = h.diff(); dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr_n = tr.rolling(n).mean()
    plus_di = 100 * plus_dm.rolling(n).mean() / atr_n.replace(0, 1e-10)
    minus_di = 100 * minus_dm.rolling(n).mean() / atr_n.replace(0, 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
    return dx.rolling(n).mean()

def supertrend(df, period=10, mult=2.0):
    h = df['High']; l = df['Low']; c = df['Close']
    atr_n = atr(df, period)
    hl2 = (h + l) / 2
    upper = hl2 + mult * atr_n
    lower = hl2 - mult * atr_n
    close_arr = c.values; upper_arr = upper.values; lower_arr = lower.values
    st_arr = np.full(len(df), np.nan)
    dir_arr = np.zeros(len(df), dtype=int)
    dir_arr[0] = 1
    st_arr[0] = lower_arr[0] if close_arr[0] > upper_arr[0] else upper_arr[0]
    for i in range(1, len(df)):
        if close_arr[i] > upper_arr[i-1]: dir_arr[i] = 1
        elif close_arr[i] < lower_arr[i-1]: dir_arr[i] = -1
        else: dir_arr[i] = dir_arr[i-1]
        st_arr[i] = lower_arr[i] if dir_arr[i] == 1 else upper_arr[i]
    return pd.Series(st_arr, index=df.index), pd.Series(dir_arr, index=df.index)

# Pre-compute signals for each slot
print('=== Pre-computing signals for each slot ===')
slot_signals = {}
for slot_id, cfg in SLOTS.items():
    df = load_data(cfg['symbol'], cfg['tf'])
    if df is None: continue
    a = atr(df, 14)
    if cfg['strategy'] == 'supertrend':
        st, dir = supertrend(df, cfg['params']['period'], cfg['params']['mult'])
        signals = pd.Series(0, index=df.index)
        diff = dir.diff()
        signals[diff != 0] = dir
    elif cfg['strategy'] == 'supertrend_adx':
        st, dir = supertrend(df, cfg['params']['period'], cfg['params']['mult'])
        signals = pd.Series(0, index=df.index)
        diff = dir.diff()
        signals[diff != 0] = dir
        adx_v = adx(df, 14)
        signals[(signals != 0) & (adx_v < cfg['params']['adx_th'])] = 0
    elif cfg['strategy'] == 'bbsq':
        n, std_n = cfg['params']['n'], cfg['params']['std_n']
        mid = sma(df['Close'], n)
        sd = df['Close'].rolling(n).std()
        upper = mid + std_n * sd
        lower = mid - std_n * sd
        signals = pd.Series(0, index=df.index)
        signals[(df['Close'] > upper) & (df['Close'].shift(1) <= upper.shift(1))] = 1
        signals[(df['Close'] < lower) & (df['Close'].shift(1) >= lower.shift(1))] = -1
    slot_signals[slot_id] = {'df': df, 'signals': signals, 'atr': a}
    print(f'  Slot {slot_id} {cfg["symbol"]} {cfg["tf"]} {cfg["strategy"]}: {len(signals[signals!=0])} signals over {len(df)} bars')

# Forward test: 30 hari terakhir
TEST_DAYS = 30
# Find common test period
test_start = max([slot_signals[s]['df'].index[-1] - timedelta(days=TEST_DAYS) for s in slot_signals])
test_end = min([slot_signals[s]['df'].index[-1] for s in slot_signals])
print(f'\n=== TEST PERIOD: {test_start.date()} to {test_end.date()} ({TEST_DAYS} days) ===')

# Simulate virtual positions
positions = {}  # slot_id -> {entry, sl, tp, type, entry_time, peak, trough}
trades = []
equity_curve = []
initial_equity = 10000  # virtual
equity = initial_equity
peak_equity = equity
max_dd = 0

# Iterate bar-by-bar across all slots in time order
# Build unified timeline from all slots
all_bars = []
for s_id, sdata in slot_signals.items():
    df = sdata['df']
    test_mask = (df.index >= test_start) & (df.index <= test_end)
    test_df = df[test_mask]
    for t in test_df.index:
        all_bars.append((t, s_id))
all_bars.sort()

print(f'Total bars to process: {len(all_bars)}')
print(f'Simulating {MAX_POSITIONS} concurrent positions, {RISK_PCT*100}% risk/trade')

# Walk through each bar
for i, (t, s_id) in enumerate(all_bars):
    sdata = slot_signals[s_id]
    df = sdata['df']
    sig = sdata['signals']
    atr_v = sdata['atr']
    if t not in df.index: continue
    idx = df.index.get_loc(t)
    if idx == 0: continue
    high = df['High'].iloc[idx]
    low = df['Low'].iloc[idx]
    close = df['Close'].iloc[idx]
    sig_val = sig.iloc[idx]
    a = atr_v.iloc[idx]
    cfg = SLOTS[s_id]
    spread = SPREADS[cfg['symbol']]
    pip_mult = PIP_VALUES[cfg['symbol']]

    # Check exits for existing position
    if s_id in positions:
        pos = positions[s_id]
        exit_p = None
        if pos['type'] == 'BUY':
            if low <= pos['sl']: exit_p = pos['sl']
            elif high >= pos['tp']: exit_p = pos['tp']
        else:
            if high >= pos['sl']: exit_p = sl if False else pos['sl']
            elif low <= pos['tp']: exit_p = pos['tp']
        if exit_p is not None:
            if pos['type'] == 'BUY':
                pips = (exit_p - pos['entry']) / pip_mult - spread
            else:
                pips = (pos['entry'] - exit_p) / pip_mult - spread
            pnl = pips * pos['lot'] * 10  # $10 per pip per standard lot
            equity += pnl
            trades.append({
                'slot': s_id, 'symbol': cfg['symbol'], 'tf': cfg['tf'],
                'type': pos['type'], 'entry_time': pos['entry_time'],
                'exit_time': t, 'entry': pos['entry'], 'exit': exit_p,
                'pips': round(pips, 1), 'pnl': round(pnl, 2), 'bars': idx - pos['bar'],
                'win': pips > 0
            })
            del positions[s_id]

    # New entry signal
    if s_id not in positions and sig_val != 0 and len(positions) < MAX_POSITIONS:
        if sig_val == 1:
            entry = close
            sl = entry - a * cfg['params']['sl']
            tp = entry + a * cfg['params']['tp']
            pos_type = 'BUY'
        else:
            entry = close
            sl = entry + a * cfg['params']['sl']
            tp = entry - a * cfg['params']['tp']
            pos_type = 'SELL'
        # Lot size: risk% of equity, SL distance in price
        sl_dist = abs(entry - sl)
        if sl_dist > 0:
            # $ risked = equity * risk%
            # pip value: lot * 10 (standard) for forex majors
            # lot = (equity * risk%) / (sl_dist / pip_mult * 10)
            pip_dist = sl_dist / pip_mult
            lot = (equity * RISK_PCT) / (pip_dist * 10) if pip_dist > 0 else 0.01
            lot = max(0.01, min(lot, 1.0))  # cap
            positions[s_id] = {
                'type': pos_type, 'entry': entry, 'sl': sl, 'tp': tp,
                'entry_time': t, 'bar': idx, 'lot': lot
            }

    # Track equity curve
    peak_equity = max(peak_equity, equity)
    dd = (peak_equity - equity) / peak_equity * 100
    max_dd = max(max_dd, dd)
    if i % 100 == 0:
        equity_curve.append({'time': t, 'equity': round(equity, 2), 'positions': len(positions)})

# Close remaining positions at last bar
for s_id in list(positions.keys()):
    pos = positions[s_id]
    df = slot_signals[s_id]['df']
    cfg = SLOTS[s_id]
    spread = SPREADS[cfg['symbol']]
    pip_mult = PIP_VALUES[cfg['symbol']]
    last_close = df['Close'].iloc[-1]
    if pos['type'] == 'BUY':
        pips = (last_close - pos['entry']) / pip_mult - spread
    else:
        pips = (pos['entry'] - last_close) / pip_mult - spread
    pnl = pips * pos['lot'] * 10
    equity += pnl
    trades.append({
        'slot': s_id, 'symbol': cfg['symbol'], 'tf': cfg['tf'],
        'type': pos['type'], 'entry_time': pos['entry_time'],
        'exit_time': df.index[-1], 'entry': pos['entry'], 'exit': last_close,
        'pips': round(pips, 1), 'pnl': round(pnl, 2), 'bars': 'open',
        'win': pips > 0
    })

# Stats
print(f'\n=== RESULTS ===')
print(f'Initial equity: ${initial_equity:.2f}')
print(f'Final equity:   ${equity:.2f}')
print(f'Net PnL:        ${equity - initial_equity:.2f} ({(equity/initial_equity - 1)*100:+.2f}%)')
print(f'Max drawdown:   {max_dd:.2f}%')
print(f'Total trades:   {len(trades)}')
if trades:
    wins = sum(1 for t in trades if t['win'])
    print(f'Win rate:       {wins/len(trades)*100:.1f}% ({wins}/{len(trades)})')
    print()
    print('=== PER SLOT ===')
    df_t = pd.DataFrame(trades)
    for s_id in SLOTS:
        sub = df_t[df_t['slot'] == s_id]
        if len(sub) == 0:
            print(f'  Slot {s_id} {SLOTS[s_id]["symbol"]} {SLOTS[s_id]["tf"]}: NO TRADES')
            continue
        w = sub['win'].sum()
        pnl = sub['pnl'].sum()
        print(f'  Slot {s_id} {SLOTS[s_id]["symbol"]} {SLOTS[s_id]["tf"]}: '
              f'{len(sub)} trades, {w/len(sub)*100:.1f}% WR, ${pnl:+.2f} PnL')
    print()
    print('=== TRADES LOG ===')
    for t in trades:
        emoji = '✅' if t['win'] else '❌'
        print(f'  {emoji} Slot{t["slot"]} {t["symbol"]} {t["tf"]} {t["type"]:4s} '
              f'{t["entry_time"]} → {t["exit_time"]} ({t["bars"]} bars) '
              f'{t["pips"]:+6.1f} pips ${t["pnl"]:+7.2f}')

df_t = pd.DataFrame(trades)
df_t.to_csv(f'{RESULTS_DIR}/paper_trade_30d.csv', index=False)
pd.DataFrame(equity_curve).to_csv(f'{RESULTS_DIR}/paper_equity_curve.csv', index=False)
print(f'\nSaved to {RESULTS_DIR}/paper_trade_30d.csv')
