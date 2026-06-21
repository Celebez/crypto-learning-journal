"""Backtest v6 — REAL MT5 DATA + MQL5 indicators
- 6 pairs × 3 TFs (D1, M30, M15) — 27 CSV files
- Real data from JustMarkets MT5 (D1 = 14 years history!)
- Real spread from CSV (last spread per symbol applied)
- MQL5-inspired strategies: supertrend, ema_macd, keltner_macd, donchian_stoch, heiken_ema, smc_fvg
"""
import pandas as pd
import numpy as np
import os
import glob
import sys
from datetime import datetime

PAIRS = ['EURUSD.m', 'GBPUSD.m', 'USDJPY.m', 'USDCHF.m', 'AUDUSD.m', 'XAUUSD.m']
TFS = ['D1', 'M30', 'M15']
DATA_DIR = '/codex-trading/backtest/data'

# Pip values for forex, dollar for XAU
PIP_SIZE = {p: 0.01 if p == 'XAUUSD.m' else (0.01 if 'JPY' in p else 0.0001) for p in PAIRS}


def load_mt5(pair, tf):
    """Load MT5 CSV with our format"""
    p = f'{DATA_DIR}/{pair}_{tf}_mt5.csv'
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    # Date is in column 1 as "YYYY.MM.DD HH:MM:SS"
    date_col = df.columns[1]
    df[date_col] = pd.to_datetime(df[date_col], format='%Y.%m.%d %H:%M:%S', errors='coerce')
    df = df.dropna(subset=[date_col]).set_index(date_col)
    df.columns = [str(c).lower() for c in df.columns]
    # Standard OHLCV
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df[['open', 'high', 'low', 'close']].dropna()


def get_real_spread(pair, tf):
    """Get the typical/median spread from the CSV's spread column"""
    p = f'{DATA_DIR}/{pair}_{tf}_mt5.csv'
    if not os.path.exists(p):
        return 30  # default
    df = pd.read_csv(p, usecols=['spread'])
    return int(df['spread'].median())


# === INDICATORS (MQL5-inspired) ===

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = (-d.where(d < 0, 0)).rolling(n).mean()
    rs = g / l
    return 100 - 100 / (1 + rs)

def macd(s, fast=12, slow=26, sig=9):
    m = ema(s, fast) - ema(s, slow)
    return m, ema(m, sig), m - ema(m, sig)

def stoch(h, l, c, k=14, d=3, smooth=3):
    hh = h.rolling(k).max()
    ll = l.rolling(k).min()
    k_line = 100 * (c - ll) / (hh - ll)
    return k_line.rolling(smooth).mean(), k_line.rolling(d).mean()

def atr(h, l, c, n=14):
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n).mean()

def bb(s, n=20, k=2.0):
    m = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return m, m + k*sd, m - k*sd


# === MQL5-INSPIRED STRATEGIES ===

def strat_supertrend(df, period=10, mult=2.0):
    """MQL5 #72345: ATR-based trailing stop"""
    a = atr(df['high'], df['low'], df['close'], period)
    hl2 = (df['high'] + df['low']) / 2
    upper = hl2 + mult * a
    lower = hl2 - mult * a

    direction = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df['close'].iloc[i] > upper.iloc[i-1]:
            direction.iloc[i] = 1
        elif df['close'].iloc[i] < lower.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]

    buy = (direction == 1) & (direction.shift(1) == -1)
    sell = (direction == -1) & (direction.shift(1) == 1)
    return buy, sell


def strat_ema_macd_atr(df, ema_f=5, ema_s=13, ema_t=50, atr_n=14):
    """EMA cross + MACD confirm + 50EMA trend + ATR stops"""
    e_f = ema(df['close'], ema_f)
    e_s = ema(df['close'], ema_s)
    e_t = ema(df['close'], ema_t)
    m, sig, hist = macd(df['close'], 12, 26, 9)
    r = rsi(df['close'], 7)

    buy = ((e_f > e_s) & (e_f.shift() <= e_s.shift()) & (m > sig) & (df['close'] > e_t)
           & (r > 40) & (r < 65) & (hist > 0))
    sell = ((e_f < e_s) & (e_f.shift() >= e_s.shift()) & (m < sig) & (df['close'] < e_t)
            & (r < 60) & (r > 35) & (hist < 0))
    return buy, sell, atr(df['high'], df['low'], df['close'], atr_n)


def strat_keltner_macd(df, n=20, mult=1.5, atr_n=14):
    """Keltner channel breakout + MACD trend"""
    m_ema = ema(df['close'], n)
    a = atr(df['high'], df['low'], df['close'], n)
    upper = m_ema + mult * a
    lower = m_ema - mult * a
    m, sig, _ = macd(df['close'], 12, 26, 9)
    r = rsi(df['close'], 14)

    buy = (df['close'] > upper) & (df['close'].shift() <= upper.shift()) & (m > sig) & (m > 0) & (r < 75)
    sell = (df['close'] < lower) & (df['close'].shift() >= lower.shift()) & (m < sig) & (m < 0) & (r > 25)
    return buy, sell, atr(df['high'], df['low'], df['close'], atr_n)


def strat_donchian_stoch(df, n=20, atr_n=14):
    """Donchian breakout + Stochastic confirm"""
    upper = df['high'].rolling(n).max()
    lower = df['low'].rolling(n).min()
    k_line, d_line = stoch(df['high'], df['low'], df['close'], 14, 3, 3)
    e100 = ema(df['close'], 100)

    buy = (df['close'] > upper.shift(1)) & (k_line > d_line) & (k_line < 80) & (df['close'] > e100)
    sell = (df['close'] < lower.shift(1)) & (k_line < d_line) & (k_line > 20) & (df['close'] < e100)
    return buy, sell, atr(df['high'], df['low'], df['close'], atr_n)


def strat_heiken_ema(df, min_streak=3):
    """Heiken Ashi with streak"""
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open = pd.Series(index=df.index, dtype=float)
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2

    ha_bull = ha_close > ha_open
    e5 = ema(df['close'], 5)
    e13 = ema(df['close'], 13)
    e50 = ema(df['close'], 50)

    streak = pd.Series(0, index=df.index)
    s = 0
    for i in range(len(df)):
        if i == 0:
            s = 1 if ha_bull.iloc[i] else -1
        elif ha_bull.iloc[i] == ha_bull.iloc[i-1]:
            s = s + (1 if ha_bull.iloc[i] else -1)
        else:
            s = 1 if ha_bull.iloc[i] else -1
        streak.iloc[i] = s

    buy = (streak >= min_streak) & (e5 > e13) & (df['close'] > e50) & (e5.shift() <= e13.shift())
    sell = (streak <= -min_streak) & (e5 < e13) & (df['close'] < e50) & (e5.shift() >= e13.shift())
    return buy, sell, atr(df['high'], df['low'], df['close'], 14)


def strat_smc_fvg(df, lookback=5, atr_n=14):
    """Fair Value Gap (MQL5 #73418)"""
    buy = pd.Series(False, index=df.index)
    sell = pd.Series(False, index=df.index)

    for i in range(lookback, len(df)):
        if df['low'].iloc[i-2] > df['high'].iloc[i-4]:
            if df['low'].iloc[i] <= df['high'].iloc[i-4]:
                r = rsi(df['close'].iloc[:i+1], 7).iloc[i]
                if r < 65:
                    buy.iloc[i] = True
        if df['high'].iloc[i-2] < df['low'].iloc[i-4]:
            if df['high'].iloc[i] >= df['low'].iloc[i-4]:
                r = rsi(df['close'].iloc[:i+1], 7).iloc[i]
                if r > 35:
                    sell.iloc[i] = True
    return buy, sell, atr(df['high'], df['low'], df['close'], atr_n)


# === BACKTESTER with real spread ===

def backtest_spread(df, buy_sig, sell_sig, pair, atr_vals, sl_m, tp_m, max_hold=50, spread_points=0):
    """Apply real spread: enter at ASK (buy) or BID (sell), exit at opposite"""
    pip = PIP_SIZE[pair]
    spread_price = spread_points * (0.0001 if 'JPY' not in pair and pair != 'XAUUSD.m' else 0.01)
    if pair == 'XAUUSD.m':
        spread_price = spread_points * 0.01  # points in MT5 = 0.01 for XAU

    trades = []
    in_trade = False
    side = 0
    entry = 0
    sl = 0
    tp = 0
    entry_i = 0

    for i in range(1, len(df)):
        if not in_trade:
            if buy_sig.iloc[i]:
                side = 1
                # BUY at ask = close + spread/2
                entry = df['close'].iloc[i] + spread_price / 2
                a = atr_vals.iloc[i] if hasattr(atr_vals, 'iloc') else 0
                if pd.isna(a) or a <= 0:
                    continue
                sl = entry - sl_m * a
                tp = entry + tp_m * a
                in_trade = True
                entry_i = i
            elif sell_sig.iloc[i]:
                side = -1
                # SELL at bid = close - spread/2
                entry = df['close'].iloc[i] - spread_price / 2
                a = atr_vals.iloc[i] if hasattr(atr_vals, 'iloc') else 0
                if pd.isna(a) or a <= 0:
                    continue
                sl = entry + sl_m * a
                tp = entry - tp_m * a
                in_trade = True
                entry_i = i
        else:
            h = df['high'].iloc[i]
            l = df['low'].iloc[i]
            exit_price = None
            if side == 1:
                # Exit long at bid (close - spread/2)
                bid_low = l - spread_price / 2
                bid_high = h - spread_price / 2
                if bid_low <= sl: exit_price = sl
                elif bid_high >= tp: exit_price = tp
            else:
                # Exit short at ask (close + spread/2)
                ask_low = l + spread_price / 2
                ask_high = h + spread_price / 2
                if ask_high >= sl: exit_price = sl
                elif ask_low <= tp: exit_price = tp

            if exit_price is not None:
                pips = (exit_price - entry) * side / pip
                trades.append({'pips': pips, 'side': side})
                in_trade = False
            elif i - entry_i >= max_hold:
                if side == 1:
                    exit_price = df['close'].iloc[i] - spread_price / 2
                else:
                    exit_price = df['close'].iloc[i] + spread_price / 2
                pips = (exit_price - entry) * side / pip
                trades.append({'pips': pips, 'side': side})
                in_trade = False

    if not trades:
        return None
    wins = [t for t in trades if t['pips'] > 0]
    losses = [t for t in trades if t['pips'] <= 0]
    wr = len(wins) / len(trades) * 100
    total = sum(t['pips'] for t in trades)
    gross_w = sum(t['pips'] for t in wins) if wins else 0
    gross_l = abs(sum(t['pips'] for t in losses)) if losses else 1
    pf = gross_w / gross_l if gross_l else 99
    return {'n': len(trades), 'wr': wr, 'total_pips': total, 'pf': pf, 'avg': total/len(trades)}


# === MAIN LOOP ===

STRATEGIES = {
    'supertrend':  (strat_supertrend,     {'sl': 2.0, 'tp': 3.0, 'needs_atr': False}),
    'ema_macd':    (strat_ema_macd_atr,   {'sl': 1.5, 'tp': 2.5, 'needs_atr': True}),
    'keltner_macd':(strat_keltner_macd,   {'sl': 1.5, 'tp': 2.5, 'needs_atr': True}),
    'donchian':    (strat_donchian_stoch, {'sl': 1.5, 'tp': 2.5, 'needs_atr': True}),
    'heiken_ema':  (strat_heiken_ema,     {'sl': 1.5, 'tp': 2.5, 'needs_atr': True}),
    'smc_fvg':     (strat_smc_fvg,        {'sl': 1.5, 'tp': 2.5, 'needs_atr': True}),
}


if __name__ == '__main__':
    results = []
    print('Loading real MT5 data and running backtest loop...\n')

    for tf in TFS:
        for pair in PAIRS:
            df = load_mt5(pair, tf)
            if df is None:
                print(f'  SKIP {pair} {tf} — no data')
                continue

            spread = get_real_spread(pair, tf)
            print(f'  {pair} {tf}: {len(df)} bars, median spread {spread} points')

            for sname, (sfunc, params) in STRATEGIES.items():
                try:
                    out = sfunc(df)
                    if len(out) == 3:
                        b, s, a = out
                    elif len(out) == 2:
                        b, s = out
                        a = atr(df['high'], df['low'], df['close'], 14)
                    else:
                        continue

                    st = backtest_spread(df, b, s, pair, a, params['sl'], params['tp'],
                                          max_hold=50, spread_points=spread)
                    if st and st['n'] >= 5:
                        st['tf'] = tf
                        st['pair'] = pair.replace('.m', '')
                        st['strat'] = sname
                        st['spread_pts'] = spread
                        st['bars'] = len(df)
                        st['date_range'] = f"{df.index[0].date()} → {df.index[-1].date()}"
                        results.append(st)
                except Exception as e:
                    pass

    results.sort(key=lambda x: x.get('total_pips', 0), reverse=True)

    print(f'\n=== TOP 30 RESULTS (REAL MT5 DATA + REAL SPREAD) ===')
    print(f"{'TF':<5} {'PAIR':<8} {'STRAT':<14} {'SPREAD':>6} {'N':>4} {'WR%':>6} {'PIPS':>8} {'PF':>5} {'BARS':>6}")
    for r in results[:30]:
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<14} {r['spread_pts']:>6} {r['n']:>4} {r['wr']:>6.1f} {r['total_pips']:>8.1f} {r['pf']:>5.2f} {r['bars']:>6}")

    # Best per (TF, pair)
    print(f'\n=== BEST PER PAIR/TF ===')
    best = {}
    for r in results:
        k = (r['pair'], r['tf'])
        if k not in best or r['total_pips'] > best[k]['total_pips']:
            best[k] = r
    for (pair, tf), r in sorted(best.items()):
        print(f"{tf:<5} {pair:<8} {r['strat']:<14} N={r['n']:>3} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>7.1f} PF={r['pf']:>4.2f} Range={r['date_range']}")

    # WR >= 60%
    winners = [r for r in results if r['wr'] >= 60 and r['n'] >= 10]
    print(f'\n=== WR >= 60% PRODUCTION CANDIDATES ({len(winners)} found) ===')
    for r in sorted(winners, key=lambda x: -x['total_pips']):
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<14} N={r['n']:>3} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>7.1f} PF={r['pf']:>4.2f}")

    # WR >= 55%
    winners55 = [r for r in results if 55 <= r['wr'] < 60 and r['n'] >= 10]
    print(f'\n=== WR 55-60% ({len(winners55)} found) ===')
    for r in sorted(winners55, key=lambda x: -x['total_pips']):
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<14} N={r['n']:>3} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>7.1f} PF={r['pf']:>4.2f}")

    # Aggregate per TF
    for tf in TFS:
        tf_results = [r for r in results if r['tf'] == tf]
        if tf_results:
            agg_n = sum(r['n'] for r in tf_results)
            agg_pips = sum(r['total_pips'] for r in tf_results)
            wins_total = sum(r['n'] * r['wr']/100 for r in tf_results)
            agg_wr = wins_total / agg_n * 100 if agg_n else 0
            print(f'\n=== AGGREGATE {tf}: {agg_n} trades, {agg_wr:.1f}% WR, {agg_pips:.1f} pips ===')

    pd.DataFrame(results).to_csv('/codex-trading/backtest_v6_mt5_results.csv', index=False)
    print(f'\nFull: /codex-trading/backtest_v6_mt5_results.csv ({len(results)} entries)')
