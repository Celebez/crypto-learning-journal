#!/usr/bin/env python3
"""Forward test SEMUA 19 slot 3 candidates — 30 hari out-of-sample.
Pilih yang terbaik by realized PnL (bukan backtest historical)."""
import pandas as pd
import numpy as np
import os
import json

DATA_DIR = 'backtest/data/yahoo_h1h4'
RESULTS_DIR = 'backtest/results_yahoo_h1h4'
os.makedirs(RESULTS_DIR, exist_ok=True)

SPREADS = {'XAUUSD': 0.28, 'USDJPY': 2.7, 'USDCAD': 1.8, 'USDCHF': 2.0, 'NZDUSD': 2.5,
           'EURUSD': 1.5, 'GBPUSD': 3.0, 'AUDUSD': 1.9}
PIP_VALUES = {'XAUUSD': 0.01, 'USDJPY': 0.01, 'USDCAD': 0.0001, 'USDCHF': 0.0001,
              'NZDUSD': 0.0001, 'EURUSD': 0.0001, 'GBPUSD': 0.0001, 'AUDUSD': 0.0001}

def load_data(symbol, tf):
    fname = f"{DATA_DIR}/{symbol}_{tf}.csv"
    if not os.path.exists(fname): return None
    df = pd.read_csv(fname, index_col=0)
    try:
        df.index = pd.to_datetime(df.index, utc=True)
        df.index = df.index.tz_convert(None)
    except Exception:
        df.index = pd.to_datetime(df.index)
    return df

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()
def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)
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
def supertrend(df, period, mult):
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

def macd(s, fast, slow, signal):
    m = ema(s, fast) - ema(s, slow)
    sig = ema(m, signal)
    return m, sig, m - sig

def keltner(df, ema_n, mult, atr_n=14):
    mid = ema(df['Close'], ema_n)
    a = atr(df, atr_n)
    return mid + mult*a, mid, mid - mult*a

def bb_squeeze(df, n, std_n):
    mid = sma(df['Close'], n)
    sd = df['Close'].rolling(n).std()
    return mid + std_n*sd, mid, mid - std_n*sd

# Build signals for all major pairs
def gen_signals_st(df, period, mult, sl, tp, adx_th=0):
    st, dir = supertrend(df, period, mult)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    diff = dir.diff()
    signals[diff != 0] = dir
    if adx_th > 0:
        adx_v = adx(df, 14)
        signals[(signals != 0) & (adx_v < adx_th)] = 0
    return signals, a, sl, tp

def gen_signals_ema_macd(df, fast, slow, sig, ema_t, sl, tp):
    ema_t_v = ema(df['Close'], ema_t)
    m, s, h = macd(df['Close'], fast, slow, sig)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(h > 0) & (h.shift(1) <= 0) & (df['Close'] > ema_t_v)] = 1
    signals[(h < 0) & (h.shift(1) >= 0) & (df['Close'] < ema_t_v)] = -1
    return signals, a, sl, tp

def gen_signals_keltner(df, ema_n, mult, sl, tp):
    upper, mid, lower = keltner(df, ema_n, mult)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(df['Close'] > upper) & (df['Close'].shift(1) <= upper.shift(1))] = 1
    signals[(df['Close'] < lower) & (df['Close'].shift(1) >= lower.shift(1))] = -1
    return signals, a, sl, tp

def gen_signals_bbsq(df, n, std_n, sl, tp):
    upper, mid, lower = bb_squeeze(df, n, std_n)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(df['Close'] > upper) & (df['Close'].shift(1) <= upper.shift(1))] = 1
    signals[(df['Close'] < lower) & (df['Close'].shift(1) >= lower.shift(1))] = -1
    return signals, a, sl, tp

# ALL 7 MAJORS + XAU tested, H1+H4 for forex, M15+M30 for XAU
all_strategies = []
tfs_forex = ['H1', 'H4']
tfs_xau = ['M15', 'M30']
forex_pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'NZDUSD', 'USDCAD']
xau_pair = 'XAUUSD'

# SuperTrend variants (comprehensive)
st_params = [
    (5, 1.5, 1.0, 2.0), (5, 2.0, 1.0, 2.0), (5, 2.5, 1.5, 2.5), (5, 3.0, 1.5, 3.0),
    (7, 1.5, 1.0, 2.0), (7, 2.0, 1.5, 2.5), (7, 2.5, 1.5, 3.0), (7, 3.0, 2.0, 3.5),
    (10, 1.5, 1.5, 2.5), (10, 2.0, 1.5, 2.5), (10, 2.5, 2.0, 3.0), (10, 3.0, 2.0, 3.5),
    (14, 2.0, 2.0, 3.0), (14, 2.5, 2.0, 3.5), (14, 3.0, 2.5, 4.0),
    (20, 2.5, 2.5, 4.0), (20, 3.0, 3.0, 4.5),
]

# EMA_MACD variants
em_params = [
    (3, 10, 16, 50, 1.5, 2.5), (3, 10, 16, 100, 2.0, 3.0),
    (5, 13, 9, 50, 1.5, 2.5), (5, 13, 9, 100, 2.0, 3.0),
    (5, 20, 9, 50, 1.5, 2.5), (5, 20, 9, 100, 2.0, 3.0),
    (8, 21, 5, 50, 1.5, 2.5), (8, 21, 5, 100, 2.0, 3.0),
    (12, 26, 9, 100, 2.0, 3.0), (12, 26, 9, 200, 2.5, 3.5),
]

# Keltner/Bollinger variants
kb_params = [
    (10, 1.5, 1.5, 2.5), (10, 2.0, 1.5, 2.5), (10, 2.0, 2.0, 3.0),
    (14, 2.0, 2.0, 3.0), (14, 2.5, 2.0, 3.0),
    (20, 1.5, 1.5, 2.5), (20, 2.0, 2.0, 3.0), (20, 2.5, 2.5, 3.5),
    (30, 2.0, 2.0, 3.0), (30, 2.5, 2.5, 3.5),
    (50, 2.0, 2.0, 3.0), (50, 2.5, 2.5, 3.5),
]

# Build for forex
data_cache = {}
for sym in forex_pairs:
    for tf in tfs_forex:
        df = load_data(sym, tf)
        if df is None: continue
        data_cache[(sym, tf)] = df
        # ST
        for p, m, sl, tp in st_params:
            for adx_th in [0, 15, 20, 25]:
                all_strategies.append((sym, tf, 'st', (p, m, sl, tp, adx_th)))
        # EMA_MACD
        for f, slw, sg, ema_t, sl, tp in em_params:
            all_strategies.append((sym, tf, 'emamacd', (f, slw, sg, ema_t, sl, tp)))
        # Keltner
        for n, mult, sl, tp in kb_params:
            all_strategies.append((sym, tf, 'keltner', (n, mult, sl, tp)))
        # BB Squeeze
        for n, mult, sl, tp in kb_params:
            all_strategies.append((sym, tf, 'bbsq', (n, mult, sl, tp)))

# XAU
for tf in tfs_xau:
    df = load_data(xau_pair, tf)
    if df is None: continue
    data_cache[(xau_pair, tf)] = df
    for p, m, sl, tp in st_params:
        for adx_th in [0, 15, 20]:
            all_strategies.append((xau_pair, tf, 'st', (p, m, sl, tp, adx_th)))
    for n, mult, sl, tp in kb_params:
        all_strategies.append((xau_pair, tf, 'keltner', (n, mult, sl, tp)))
        all_strategies.append((xau_pair, tf, 'bbsq', (n, mult, sl, tp)))

print(f'Total strategies: {len(all_strategies)}')

# Pre-compute signals
slot_signals = {}
for sym, tf, strat_type, params in all_strategies:
    df = data_cache.get((sym, tf))
    if df is None: continue
    if strat_type == 'st':
        p, m, sl, tp, adx_th = params
        sig, a, sl_v, tp_v = gen_signals_st(df, p, m, sl, tp, adx_th)
    elif strat_type == 'emamacd':
        f, slw, sg, ema_t, sl, tp = params
        sig, a, sl_v, tp_v = gen_signals_ema_macd(df, f, slw, sg, ema_t, sl, tp)
    elif strat_type == 'keltner':
        n, mult, sl, tp = params
        sig, a, sl_v, tp_v = gen_signals_keltner(df, n, mult, sl, tp)
    elif strat_type == 'bbsq':
        n, mult, sl, tp = params
        sig, a, sl_v, tp_v = gen_signals_bbsq(df, n, mult, sl, tp)
    slot_signals[(sym, tf, strat_type, params)] = {'df': df, 'signals': sig, 'atr': a, 'sl': sl_v, 'tp': tp}

# Test period (30 days)
test_end = min([data_cache[k].index[-1] for k in data_cache])
test_start = test_end - pd.Timedelta(days=30)
print(f'Test period: {test_start.date()} to {test_end.date()}')

# Forward test each strategy independently (no concurrent positions)
results = []
for key, sdata in slot_signals.items():
    sym, tf, strat_type, params = key
    df = sdata['df']
    sig = sdata['signals']
    atr_v = sdata['atr']
    sl_mult = sdata['sl']
    tp_mult = sdata['tp']
    spread = SPREADS.get(sym, 1.5)
    pip_mult = PIP_VALUES.get(sym, 0.0001)
    is_gold = (sym == 'XAUUSD')

    # Test in 30-day window
    test_mask = (df.index >= test_start) & (df.index <= test_end)
    test_idx = df.index[test_mask]
    if len(test_idx) < 10: continue

    trades = []
    pos = None
    for t in test_idx:
        idx = df.index.get_loc(t)
        if idx == 0: continue
        high = df['High'].iloc[idx]
        low = df['Low'].iloc[idx]
        close = df['Close'].iloc[idx]
        sig_val = sig.iloc[idx]
        a = atr_v.iloc[idx]
        if np.isnan(a): continue

        # Exit check
        if pos is not None:
            exit_p = None
            if pos['type'] == 'BUY':
                if low <= pos['sl']: exit_p = pos['sl']
                elif high >= pos['tp']: exit_p = pos['tp']
            else:
                if high >= pos['sl']: exit_p = pos['sl']
                elif low <= pos['tp']: exit_p = pos['tp']
            if exit_p is not None:
                if pos['type'] == 'BUY':
                    pips = (exit_p - pos['entry']) / pip_mult - spread
                else:
                    pips = (pos['entry'] - exit_p) / pip_mult - spread
                trades.append({'pips': pips, 'win': pips > 0, 'entry': pos['entry_time'], 'exit': t, 'type': pos['type']})
                pos = None

        # Entry
        if pos is None and sig_val != 0:
            if sig_val == 1:
                entry = close
                sl = entry - a * sl_mult
                tp = entry + a * tp_mult
                pos = {'type': 'BUY', 'entry': entry, 'sl': sl, 'tp': tp, 'entry_time': t}
            else:
                entry = close
                sl = entry + a * sl_mult
                tp = entry - a * tp_mult
                pos = {'type': 'SELL', 'entry': entry, 'sl': sl, 'tp': tp, 'entry_time': t}

    # Stats
    if not trades: continue
    n = len(trades)
    wins = sum(1 for t in trades if t['win'])
    wr = wins / n * 100
    pnl = sum(t['pips'] for t in trades)
    gw = sum(t['pips'] for t in trades if t['win'])
    gl = abs(sum(t['pips'] for t in trades if not t['win']))
    pf = gw / gl if gl > 0 else 0
    if strat_type == 'st':
        name = f'{sym}_{tf}_st_{"_".join(str(x) for x in params)}'
    elif strat_type == 'emamacd':
        f, slw, sg, ema_t, sl, tp = params
        name = f'{sym}_{tf}_emamacd_{f}_{slw}_{sg}_e{ema_t}'
    elif strat_type == 'keltner':
        n, mult, sl, tp = params
        name = f'{sym}_{tf}_keltner_{n}_{mult}'
    elif strat_type == 'bbsq':
        n, mult, sl, tp = params
        name = f'{sym}_{tf}_bbsq_{n}_{mult}'
    results.append({
        'name': name, 'trades': n, 'wr': round(wr, 1), 'pnl': round(pnl, 1),
        'pf': round(pf, 2), 'avg_pips': round(pnl/n, 1), 'type': strat_type,
        'sym': sym, 'tf': tf
    })

# Sort by PnL
df_res = pd.DataFrame(results).sort_values('pnl', ascending=False)
df_res.to_csv(f'{RESULTS_DIR}/forward_test_30d.csv', index=False)

print(f'\n=== TOP 30 BY 30-DAY PNL ===')
print(df_res.head(30).to_string(index=False))
print(f'\n=== TOP 10 BY PF (with N>=5) ===')
df_pf = df_res[(df_res['trades'] >= 5) & (df_res['pnl'] > 0)].sort_values('pf', ascending=False)
print(df_pf.head(10)[['name','trades','wr','pnl','pf']].to_string(index=False))
print(f'\n=== ALL PROFITABLE (N>=5, PnL>0) ===')
df_prof = df_res[(df_res['trades'] >= 5) & (df_res['pnl'] > 0)]
print(f'Total: {len(df_prof)}')
