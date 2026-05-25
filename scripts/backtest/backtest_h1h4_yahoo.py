#!/usr/bin/env python3
"""Backtest H1/H4 forex + M15/M30 XAUUSD dengan Yahoo data + MT5 spread real.
Modal terbatas, butuh duit harian — focus pada strategies yang proven + realistic."""
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime

DATA_DIR = 'backtest/data/yahoo_h1h4'
RESULTS_DIR = 'backtest/results_yahoo_h1h4'
os.makedirs(RESULTS_DIR, exist_ok=True)

# MT5 JustMarkets spread real (from earlier verification)
SPREADS = {
    'EURUSD': 1.5,   # pips
    'GBPUSD': 3.0,
    'USDJPY': 2.7,
    'USDCHF': 2.0,
    'AUDUSD': 1.9,
    'USDCAD': 1.8,
    'NZDUSD': 2.5,
    'XAUUSD': 0.28,  # 28 cents = 2.8 pips (1 pip gold = $0.01)
}

def load_data(symbol, tf):
    fname = f"{DATA_DIR}/{symbol}_{tf}.csv"
    if not os.path.exists(fname):
        return None
    df = pd.read_csv(fname, index_col=0, parse_dates=True)
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df

# ============ INDICATORS ============
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
    # Vectorized: use numpy
    close_arr = c.values
    upper_arr = upper.values
    lower_arr = lower.values
    st_arr = np.full(len(df), np.nan)
    dir_arr = np.zeros(len(df), dtype=int)
    dir_arr[0] = 1
    st_arr[0] = lower_arr[0] if close_arr[0] > upper_arr[0] else upper_arr[0]
    for i in range(1, len(df)):
        if close_arr[i] > upper_arr[i-1]:
            dir_arr[i] = 1
        elif close_arr[i] < lower_arr[i-1]:
            dir_arr[i] = -1
        else:
            dir_arr[i] = dir_arr[i-1]
        st_arr[i] = lower_arr[i] if dir_arr[i] == 1 else upper_arr[i]
    st = pd.Series(st_arr, index=df.index)
    direction = pd.Series(dir_arr, index=df.index)
    return st, direction

def macd(s, fast=12, slow=26, signal=9):
    m = ema(s, fast) - ema(s, slow)
    sig = ema(m, signal)
    hist = m - sig
    return m, sig, hist

def keltner(df, ema_n=20, mult=2.0, atr_n=14):
    mid = ema(df['Close'], ema_n)
    a = atr(df, atr_n)
    return mid + mult*a, mid, mid - mult*a

def bb_squeeze(df, n=20, std_n=2.0):
    mid = sma(df['Close'], n)
    sd = df['Close'].rolling(n).std()
    return mid + std_n*sd, mid, mid - std_n*sd

# ============ STRATEGIES ============
def strat_supertrend(df, period=10, mult=2.0, sl_mult=1.5, tp_mult=2.5, adx_filter=False):
    """SuperTrend basic + optional ADX filter"""
    st, dir = supertrend(df, period, mult)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[dir.diff() != 0] = dir  # 1=buy, -1=sell at flip
    adx_v, _, _ = adx(df, 14)
    if adx_filter:
        signals[signals != 0] = signals[signals != 0] * (adx_v[signals != 0] > 15).astype(int).replace(0, 1)
    return signals, a

def strat_ema_macd(df, fast=5, slow=13, sig=9, ema_trend=50, sl_mult=1.5, tp_mult=2.5):
    """EMA trend filter + MACD signal"""
    ema_t = ema(df['Close'], ema_trend)
    m, s, h = macd(df['Close'], fast, slow, sig)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    buy = (h > 0) & (h.shift(1) <= 0) & (df['Close'] > ema_t)
    sell = (h < 0) & (h.shift(1) >= 0) & (df['Close'] < ema_t)
    signals[buy] = 1
    signals[sell] = -1
    return signals, a

def strat_ichimoku(df, tenkan=9, kijun=26, senkou=52):
    """Ichimoku Cloud break"""
    h = df['High']; l = df['Low']
    ten = (h.rolling(tenkan).max() + l.rolling(tenkan).min()) / 2
    kij = (h.rolling(kijun).max() + l.rolling(kijun).min()) / 2
    senA = (ten + kij) / 2
    senB = (h.rolling(senkou).max() + l.rolling(senkou).min()) / 2
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    cloud_top = pd.concat([senA, senB], axis=1).max(axis=1)
    cloud_bot = pd.concat([senA, senB], axis=1).min(axis=1)
    above = df['Close'] > cloud_top
    below = df['Close'] < cloud_bot
    signals[(above) & (~above.shift(1).fillna(False))] = 1
    signals[(below) & (~below.shift(1).fillna(False))] = -1
    return signals, a

def strat_keltner_break(df, ema_n=20, mult=2.0, sl_mult=2.0, tp_mult=3.0):
    """Keltner channel breakout"""
    upper, mid, lower = keltner(df, ema_n, mult)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(df['Close'] > upper) & (df['Close'].shift(1) <= upper.shift(1))] = 1
    signals[(df['Close'] < lower) & (df['Close'].shift(1) >= lower.shift(1))] = -1
    return signals, a

def strat_bb_squeeze(df, n=20, std_n=2.0, sl_mult=2.0, tp_mult=3.0):
    """Bollinger band break (similar to Keltner but std)"""
    upper, mid, lower = bb_squeeze(df, n, std_n)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(df['Close'] > upper) & (df['Close'].shift(1) <= upper.shift(1))] = 1
    signals[(df['Close'] < lower) & (df['Close'].shift(1) >= lower.shift(1))] = -1
    return signals, a

def strat_rsi_div(df, n=14, ob=70, os_=30, sl_mult=1.5, tp_mult=2.5):
    """RSI basic OB/OS reversal"""
    r = rsi(df['Close'], n)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(r < os_) & (r.shift(1) >= os_)] = 1
    signals[(r > ob) & (r.shift(1) <= ob)] = -1
    return signals, a

def strat_ema_cross(df, fast=9, slow=21, sl_mult=1.5, tp_mult=2.5):
    """EMA crossover"""
    ef = ema(df['Close'], fast)
    es = ema(df['Close'], slow)
    a = atr(df, 14)
    signals = pd.Series(0, index=df.index)
    signals[(ef > es) & (ef.shift(1) <= es.shift(1))] = 1
    signals[(ef < es) & (ef.shift(1) >= es.shift(1))] = -1
    return signals, a

# ============ BACKTEST ENGINE ============
def backtest(df, signals, atr_v, sl_mult, tp_mult, spread, is_gold=False):
    """Run backtest with spread. Returns trade list (vectorized)."""
    pip_mult = 0.01 if is_gold else 0.0001
    sig_arr = signals.values
    atr_arr = atr_v.values
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values
    idx = df.index
    trades = []
    pos = None
    for i in range(1, len(df)):
        if pos is None:
            if sig_arr[i] != 0:
                entry = close[i]
                if sig_arr[i] == 1:
                    sl = entry - atr_arr[i] * sl_mult
                    tp = entry + atr_arr[i] * tp_mult
                    pos = ('BUY', entry, sl, tp, i)
                else:
                    sl = entry + atr_arr[i] * sl_mult
                    tp = entry - atr_arr[i] * tp_mult
                    pos = ('SELL', entry, sl, tp, i)
        else:
            t, entry, sl, tp, bi = pos
            exit_p = None
            if t == 'BUY':
                if low[i] <= sl: exit_p = sl
                elif high[i] >= tp: exit_p = tp
            else:
                if high[i] >= sl: exit_p = sl
                elif low[i] <= tp: exit_p = tp
            if exit_p is not None:
                if t == 'BUY':
                    pips = (exit_p - entry) / pip_mult - spread
                else:
                    pips = (entry - exit_p) / pip_mult - spread
                trades.append({
                    'entry_time': idx[bi], 'exit_time': idx[i],
                    'type': t, 'entry': entry, 'exit': exit_p,
                    'pips': round(pips, 1), 'bars': i - bi, 'win': pips > 0
                })
                pos = None
    return trades

def stats(trades, name):
    if not trades:
        return {'name': name, 'trades': 0, 'wr': 0, 'pnl': 0, 'pf': 0}
    n = len(trades)
    wins = sum(1 for t in trades if t['win'])
    wr = wins / n * 100
    pnl = sum(t['pips'] for t in trades)
    gross_w = sum(t['pips'] for t in trades if t['win'])
    gross_l = abs(sum(t['pips'] for t in trades if not t['win']))
    pf = gross_w / gross_l if gross_l > 0 else 99
    avg_win = gross_w / wins if wins > 0 else 0
    avg_loss = gross_l / (n-wins) if n-wins > 0 else 0
    return {
        'name': name, 'trades': n, 'wr': round(wr, 1), 'pnl': round(pnl, 1),
        'pf': round(pf, 2), 'avg_win': round(avg_win, 1), 'avg_loss': round(avg_loss, 1),
        'expectancy': round(pnl/n, 1)
    }

# ============ MAIN ============
all_results = []
symbols = ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD', 'XAUUSD']
tfs_forex = ['H1', 'H4']
tfs_xau = ['M15', 'M30']

for sym in symbols:
    spread = SPREADS[sym]
    is_gold = (sym == 'XAUUSD')
    tfs = tfs_xau if is_gold else tfs_forex
    for tf in tfs:
        df = load_data(sym, tf)
        if df is None: continue
        # SuperTrend variants
        for p, m, sl, tp in [(10, 2.0, 1.5, 2.5), (10, 3.0, 2.0, 3.0), (7, 2.0, 1.5, 2.5), (14, 2.5, 2.0, 3.5)]:
            for adx_f in [False, True]:
                sig, a = strat_supertrend(df, p, m, sl, tp, adx_f)
                t = backtest(df, sig, a, sl, tp, spread, is_gold)
                s = stats(t, f'{sym}_{tf}_supertrend_{p}_{m}_{"adx" if adx_f else "noadx"}')
                all_results.append(s)
        # EMA_MACD variants
        for f, slw, sg, ema_t, sl, tp in [
            (5, 13, 9, 50, 1.5, 2.5), (3, 10, 16, 50, 1.5, 2.5),
            (12, 26, 9, 100, 2.0, 3.0), (8, 21, 5, 50, 1.5, 2.5),
        ]:
            sig, a = strat_ema_macd(df, f, slw, sg, ema_t, sl, tp)
            t = backtest(df, sig, a, sl, tp, spread, is_gold)
            s = stats(t, f'{sym}_{tf}_emamacd_{f}_{slw}_{sg}_ema{ema_t}')
            all_results.append(s)
        # Ichimoku
        sig, a = strat_ichimoku(df, 9, 26, 52)
        t = backtest(df, sig, a, 2.0, 3.0, spread, is_gold)
        s = stats(t, f'{sym}_{tf}_ichimoku')
        all_results.append(s)
        # Keltner
        sig, a = strat_keltner_break(df, 20, 2.0, 2.0, 3.0)
        t = backtest(df, sig, a, 2.0, 3.0, spread, is_gold)
        s = stats(t, f'{sym}_{tf}_keltner')
        all_results.append(s)
        # BB squeeze
        sig, a = strat_bb_squeeze(df, 20, 2.0, 2.0, 3.0)
        t = backtest(df, sig, a, 2.0, 3.0, spread, is_gold)
        s = stats(t, f'{sym}_{tf}_bbsqueeze')
        all_results.append(s)
        # EMA cross
        for fast, slow, sl, tp in [(9, 21, 1.5, 2.5), (5, 20, 1.5, 2.5), (12, 26, 2.0, 3.0)]:
            sig, a = strat_ema_cross(df, fast, slow, sl, tp)
            t = backtest(df, sig, a, sl, tp, spread, is_gold)
            s = stats(t, f'{sym}_{tf}_emacross_{fast}_{slow}')
            all_results.append(s)
        # RSI basic
        sig, a = strat_rsi_div(df, 14, 70, 30, 1.5, 2.5)
        t = backtest(df, sig, a, 1.5, 2.5, spread, is_gold)
        s = stats(t, f'{sym}_{tf}_rsi')
        all_results.append(s)

# Save
df_res = pd.DataFrame(all_results)
df_res.to_csv(f'{RESULTS_DIR}/all_results.csv', index=False)
# Filter: N>=10, WR>=50, PnL>0, PF>=1.3
df_prof = df_res[(df_res['trades'] >= 10) & (df_res['wr'] >= 50) & (df_res['pnl'] > 0) & (df_res['pf'] >= 1.3)]
df_prof = df_prof.sort_values('pnl', ascending=False)
df_prof.to_csv(f'{RESULTS_DIR}/profitable.csv', index=False)
print(f'\n=== TOTAL: {len(df_res)} strategies tested ===')
print(f'=== PROFITABLE (N>=10, WR>=50%, PF>=1.3, PnL>0): {len(df_prof)} ===\n')
print(df_prof.head(50).to_string(index=False))
