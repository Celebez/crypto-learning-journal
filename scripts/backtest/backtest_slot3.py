#!/usr/bin/env python3
"""Targeted backtest untuk cari 1 strategy ke-3 (slot max 3 entry).
Fokus di USDCAD, NZDUSD, USDCHF + trailing stop + parameter sweep."""
import pandas as pd
import numpy as np
import os
import json

DATA_DIR = 'backtest/data/yahoo_h1h4'
RESULTS_DIR = 'backtest/results_yahoo_h1h4'
os.makedirs(RESULTS_DIR, exist_ok=True)

SPREADS = {
    'USDCAD': 1.8, 'NZDUSD': 2.5, 'USDCHF': 2.0,
    'EURUSD': 1.5, 'GBPUSD': 3.0, 'USDJPY': 2.7, 'AUDUSD': 1.9,
    'XAUUSD': 0.28,
}

def load_data(symbol, tf):
    fname = f"{DATA_DIR}/{symbol}_{tf}.csv"
    if not os.path.exists(fname): return None
    df = pd.read_csv(fname, index_col=0, parse_dates=True)
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
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
    return dx.rolling(n).mean(), plus_di, minus_di

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

def macd(s, fast=12, slow=26, signal=9):
    m = ema(s, fast) - ema(s, slow)
    sig = ema(m, signal)
    return m, sig, m - sig

def keltner(df, ema_n=20, mult=2.0, atr_n=14):
    mid = ema(df['Close'], ema_n)
    a = atr(df, atr_n)
    return mid + mult*a, mid, mid - mult*a

def bb_squeeze(df, n=20, std_n=2.0):
    mid = sma(df['Close'], n)
    sd = df['Close'].rolling(n).std()
    return mid + std_n*sd, mid, mid - std_n*sd

# ============ STRATEGIES ============
def strat_supertrend(df, period, mult, sl, tp, adx_filter=False, adx_th=15):
    st, dir = supertrend(df, period, mult)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    diff = dir.diff()
    signals[diff != 0] = dir
    if adx_filter:
        adx_v, _, _ = adx(df, 14)
        mask = (signals != 0) & (adx_v >= adx_th)
        signals[~mask] = 0
    return signals, a, sl, tp

def strat_supertrend_trailing(df, period, mult, sl, tp, trail_atr=1.0):
    """Supertrend with trailing stop instead of fixed TP/SL"""
    st, dir = supertrend(df, period, mult)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    diff = dir.diff()
    signals[diff != 0] = dir
    # Use ATR-based stop only, trail with supertrend line
    return signals, a, sl, tp, st  # return st for trailing

def strat_ema_macd(df, fast, slow, sig, ema_t, sl, tp):
    ema_t_v = ema(df['Close'], ema_t)
    m, s, h = macd(df['Close'], fast, slow, sig)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(h > 0) & (h.shift(1) <= 0) & (df['Close'] > ema_t_v)] = 1
    signals[(h < 0) & (h.shift(1) >= 0) & (df['Close'] < ema_t_v)] = -1
    return signals, a, sl, tp

def strat_ema_cross(df, fast, slow, sl, tp):
    ef = ema(df['Close'], fast)
    es = ema(df['Close'], slow)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(ef > es) & (ef.shift(1) <= es.shift(1))] = 1
    signals[(ef < es) & (ef.shift(1) >= es.shift(1))] = -1
    return signals, a, sl, tp

def strat_keltner_break(df, ema_n, mult, sl, tp):
    upper, mid, lower = keltner(df, ema_n, mult)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(df['Close'] > upper) & (df['Close'].shift(1) <= upper.shift(1))] = 1
    signals[(df['Close'] < lower) & (df['Close'].shift(1) >= lower.shift(1))] = -1
    return signals, a, sl, tp

def strat_bb_squeeze(df, n, std_n, sl, tp):
    upper, mid, lower = bb_squeeze(df, n, std_n)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(df['Close'] > upper) & (df['Close'].shift(1) <= upper.shift(1))] = 1
    signals[(df['Close'] < lower) & (df['Close'].shift(1) >= lower.shift(1))] = -1
    return signals, a, sl, tp

# ============ BACKTEST ENGINE WITH TRAILING STOP ============
def backtest_trailing(df, signals, atr_v, sl_mult, tp_mult, spread, trail_line=None, is_gold=False):
    """Backtest with optional trailing stop (using supertrend line as trail)."""
    pip_mult = 0.01 if is_gold else 0.0001
    sig_arr = signals.values
    atr_arr = atr_v.values
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values
    idx = df.index
    trail = trail_line.values if trail_line is not None else None
    trades = []
    pos = None
    for i in range(1, len(df)):
        if pos is None:
            if sig_arr[i] != 0:
                entry = close[i]
                if sig_arr[i] == 1:
                    sl = entry - atr_arr[i] * sl_mult
                    tp = entry + atr_arr[i] * tp_mult
                    pos = ('BUY', entry, sl, tp, i, sl)  # last = current trail
                else:
                    sl = entry + atr_arr[i] * sl_mult
                    tp = entry - atr_arr[i] * tp_mult
                    pos = ('SELL', entry, sl, tp, i, sl)
        else:
            t, entry, sl, tp, bi, cur_trail = pos
            exit_p = None
            # Update trailing stop with supertrend line
            if trail is not None and not np.isnan(trail[i]):
                if t == 'BUY' and trail[i] > cur_trail:
                    new_sl = max(sl, trail[i])
                    pos = (t, entry, new_sl, tp, bi, trail[i])
                    sl, cur_trail = new_sl, trail[i]
                elif t == 'SELL' and trail[i] < cur_trail:
                    new_sl = min(sl, trail[i])
                    pos = (t, entry, new_sl, tp, bi, trail[i])
                    sl, cur_trail = new_sl, trail[i]
            # Check exit
            if t == 'BUY':
                if low[i] <= sl: exit_p = sl
                elif high[i] >= tp: exit_p = tp
            else:
                if high[i] >= sl: exit_p = sl
                elif low[i] <= tp: exit_p = tp
            if exit_p is not None:
                if t == 'BUY': pips = (exit_p - entry) / pip_mult - spread
                else: pips = (entry - exit_p) / pip_mult - spread
                trades.append({
                    'entry_time': idx[bi], 'exit_time': idx[i],
                    'type': t, 'pips': round(pips, 1),
                    'bars': i - bi, 'win': pips > 0
                })
                pos = None
    return trades

def stats(trades, name):
    if not trades: return {'name': name, 'trades': 0, 'wr': 0, 'pnl': 0, 'pf': 0, 'expectancy': 0}
    n = len(trades)
    wins = sum(1 for t in trades if t['win'])
    wr = wins / n * 100
    pnl = sum(t['pips'] for t in trades)
    gw = sum(t['pips'] for t in trades if t['win'])
    gl = abs(sum(t['pips'] for t in trades if not t['win']))
    pf = gw / gl if gl > 0 else 99
    return {'name': name, 'trades': n, 'wr': round(wr, 1), 'pnl': round(pnl, 1),
            'pf': round(pf, 2), 'expectancy': round(pnl/n, 1)}

# ============ MAIN SWEEP ============
all_results = []

# Focus on USDCAD, NZDUSD, USDCHF (weak pairs to find at least 1 more)
target_symbols = ['USDCAD', 'NZDUSD', 'USDCHF']
tfs = ['H1', 'H4']

# SuperTrend param sweep with ADX
st_params = [
    (5, 1.5, 1.0, 2.0), (5, 2.0, 1.0, 2.0), (5, 2.5, 1.5, 2.5),
    (7, 1.5, 1.0, 2.0), (7, 2.0, 1.5, 2.5), (7, 2.5, 1.5, 3.0), (7, 3.0, 2.0, 3.0),
    (10, 1.5, 1.5, 2.5), (10, 2.0, 1.5, 2.5), (10, 2.5, 2.0, 3.0), (10, 3.0, 2.0, 3.5),
    (14, 2.0, 2.0, 3.0), (14, 2.5, 2.0, 3.5), (14, 3.0, 2.5, 4.0),
    (20, 2.5, 2.5, 4.0), (20, 3.0, 3.0, 4.5),
]

# EMA_MACD param sweep
em_params = [
    (3, 10, 16, 50, 1.5, 2.5), (3, 10, 16, 100, 2.0, 3.0),
    (5, 13, 9, 50, 1.5, 2.5), (5, 13, 9, 100, 2.0, 3.0),
    (5, 20, 9, 50, 1.5, 2.5), (5, 20, 9, 100, 2.0, 3.0),
    (8, 21, 5, 50, 1.5, 2.5), (8, 21, 5, 100, 2.0, 3.0),
    (12, 26, 9, 100, 2.0, 3.0), (12, 26, 9, 200, 2.5, 3.5),
]

# Keltner/Bollinger param sweep
kb_params = [
    (10, 1.5, 1.5, 2.5), (10, 2.0, 1.5, 2.5), (10, 2.0, 2.0, 3.0),
    (14, 2.0, 2.0, 3.0), (14, 2.5, 2.0, 3.0),
    (20, 1.5, 1.5, 2.5), (20, 2.0, 2.0, 3.0), (20, 2.5, 2.5, 3.5),
    (20, 2.0, 2.0, 3.0), (30, 2.0, 2.0, 3.0), (30, 2.5, 2.5, 3.5),
    (50, 2.0, 2.0, 3.0), (50, 2.5, 2.5, 3.5),
]

for sym in target_symbols:
    spread = SPREADS[sym]
    is_gold = (sym == 'XAUUSD')
    for tf in tfs:
        df = load_data(sym, tf)
        if df is None: continue
        # SuperTrend sweep (with/without ADX)
        for p, m, sl, tp in st_params:
            for adx_f, adx_t in [(False, 0), (True, 15), (True, 20), (True, 25)]:
                sig, a, sl_v, tp_v = strat_supertrend(df, p, m, sl, tp, adx_f, adx_t)
                t = backtest_trailing(df, sig, a, sl_v, tp_v, spread, None, is_gold)
                s = stats(t, f'{sym}_{tf}_st_{p}_{m}_adx{adx_t}')
                all_results.append(s)
        # SuperTrend with trailing stop
        for p, m, sl, tp in [(7, 2.0, 1.5, 2.5), (10, 2.0, 1.5, 2.5), (10, 3.0, 2.0, 3.5)]:
            sig, a, sl_v, tp_v, trail = strat_supertrend_trailing(df, p, m, sl, tp)
            t = backtest_trailing(df, sig, a, sl_v, tp_v, spread, trail, is_gold)
            s = stats(t, f'{sym}_{tf}_st_trail_{p}_{m}')
            all_results.append(s)
        # EMA_MACD sweep
        for f, slw, sg, ema_t, sl, tp in em_params:
            sig, a, sl_v, tp_v = strat_ema_macd(df, f, slw, sg, ema_t, sl, tp)
            t = backtest_trailing(df, sig, a, sl_v, tp_v, spread, None, is_gold)
            s = stats(t, f'{sym}_{tf}_emamacd_{f}_{slw}_{sg}_e{ema_t}')
            all_results.append(s)
        # EMA cross sweep
        for f, s_v, sl, tp in [(5, 13, 1.5, 2.5), (5, 20, 1.5, 2.5), (5, 34, 2.0, 3.0),
                                (8, 21, 1.5, 2.5), (9, 21, 1.5, 2.5), (10, 30, 2.0, 3.0),
                                (12, 26, 2.0, 3.0), (13, 34, 2.0, 3.0), (20, 50, 2.5, 3.5)]:
            sig, a, sl_v, tp_v = strat_ema_cross(df, f, s_v, sl, tp)
            t = backtest_trailing(df, sig, a, sl_v, tp_v, spread, None, is_gold)
            s = stats(t, f'{sym}_{tf}_emacross_{f}_{s_v}')
            all_results.append(s)
        # Keltner/Bollinger sweep
        for n, mult, sl, tp in kb_params:
            sig, a, sl_v, tp_v = strat_keltner_break(df, n, mult, sl, tp)
            t = backtest_trailing(df, sig, a, sl_v, tp_v, spread, None, is_gold)
            s = stats(t, f'{sym}_{tf}_keltner_{n}_{mult}')
            all_results.append(s)
            sig, a, sl_v, tp_v = strat_bb_squeeze(df, n, mult, sl, tp)
            t = backtest_trailing(df, sig, a, sl_v, tp_v, spread, None, is_gold)
            s = stats(t, f'{sym}_{tf}_bbsq_{n}_{mult}')
            all_results.append(s)

# Save
df_res = pd.DataFrame(all_results)
df_res.to_csv(f'{RESULTS_DIR}/slot3_search.csv', index=False)
# Filter profitable: N>=10, WR>=42%, PnL>0
df_prof = df_res[(df_res['trades'] >= 10) & (df_res['wr'] >= 42) & (df_res['pnl'] > 0)] if len(df_res) > 0 else df_res
df_prof = df_prof.sort_values('pnl', ascending=False)
print(f'\n=== TOTAL: {len(df_res)} strategies tested ===')
print(f'=== PROFITABLE (N>=10, WR>=42%, PnL>0): {len(df_prof)} ===\n')
print(df_prof.head(40).to_string(index=False))
