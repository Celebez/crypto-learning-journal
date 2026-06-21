"""Backtest v7 — iterate over more parameter combinations on REAL MT5 data
Focus on D1 (more data) + M30 (XAU works) — find optimal per-strategy params
"""
import pandas as pd
import numpy as np
import os
import sys
import itertools
sys.path.insert(0, '~/codex-trading')
from backtest_v6_mt5 import (
    load_mt5, get_real_spread, PIP_SIZE,
    ema, rsi, macd, stoch, atr, bb,
    strat_supertrend, strat_keltner_macd, strat_heiken_ema,
    backtest_spread
)

PAIRS = ['EURUSD.m', 'GBPUSD.m', 'USDJPY.m', 'USDCHF.m', 'AUDUSD.m', 'XAUUSD.m']
TFS = ['D1', 'M30', 'M15']


def v7_ema_macd_v2(df, ema_f, ema_s, ema_t, atr_n, sl_m, tp_m):
    """Parameterized EMA + MACD + trend"""
    e_f = ema(df['close'], ema_f)
    e_s = ema(df['close'], ema_s)
    e_t = ema(df['close'], ema_t)
    m, sig, hist = macd(df['close'], 12, 26, 9)
    r = rsi(df['close'], 7)

    buy = ((e_f > e_s) & (e_f.shift() <= e_s.shift()) & (m > sig) & (df['close'] > e_t)
           & (r > 40) & (r < 65) & (hist > 0))
    sell = ((e_f < e_s) & (e_f.shift() >= e_s.shift()) & (m < sig) & (df['close'] < e_t)
            & (r < 60) & (r > 35) & (hist < 0))
    a = atr(df['high'], df['low'], df['close'], atr_n)
    return buy, sell, a


def v7_supertrend_v2(df, period, mult, atr_n, sl_m, tp_m):
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
    a_stop = atr(df['high'], df['low'], df['close'], atr_n)
    return buy, sell, a_stop


def v7_keltner_v2(df, n, mult, atr_n, sl_m, tp_m):
    m_ema = ema(df['close'], n)
    a = atr(df['high'], df['low'], df['close'], n)
    upper = m_ema + mult * a
    lower = m_ema - mult * a
    m, sig, _ = macd(df['close'], 12, 26, 9)
    r = rsi(df['close'], 14)

    buy = (df['close'] > upper) & (df['close'].shift() <= upper.shift()) & (m > sig) & (m > 0) & (r < 75)
    sell = (df['close'] < lower) & (df['close'].shift() >= lower.shift()) & (m < sig) & (m < 0) & (r > 25)
    a_stop = atr(df['high'], df['low'], df['close'], atr_n)
    return buy, sell, a_stop


def v7_rsi_meanrev(df, period, overbought, oversold, atr_n, sl_m, tp_m):
    r = rsi(df['close'], period)
    e50 = ema(df['close'], 50)
    a = atr(df['high'], df['low'], df['close'], atr_n)

    buy = (r < oversold) & (df['close'] < e50) & (r.shift() >= oversold)
    sell = (r > overbought) & (df['close'] > e50) & (r.shift() <= overbought)
    return buy, sell, a


def v7_donchian_v2(df, n, atr_n, sl_m, tp_m):
    upper = df['high'].rolling(n).max()
    lower = df['low'].rolling(n).min()
    a = atr(df['high'], df['low'], df['close'], atr_n)

    buy = (df['close'] > upper.shift(1)) & (df['close'].shift() <= upper.shift(2).shift())
    sell = (df['close'] < lower.shift(1)) & (df['close'].shift() >= lower.shift(2).shift())
    return buy, sell, a


if __name__ == '__main__':
    results = []

    # === Parameter sweeps ===
    # ema_macd: ema_f, ema_s, ema_t, atr_n, sl_m, tp_m
    ema_macd_grid = [
        (5, 13, 50, 14, 1.5, 2.5),
        (5, 13, 50, 14, 2.0, 3.0),
        (3, 10, 50, 14, 1.5, 2.5),
        (8, 21, 100, 14, 1.5, 2.5),
        (5, 13, 100, 21, 2.0, 3.5),
        (5, 13, 50, 14, 1.0, 2.0),
        (3, 8, 50, 14, 1.0, 1.8),
        (5, 13, 30, 14, 1.5, 2.0),
        (5, 13, 50, 10, 1.5, 2.5),
        (5, 13, 50, 14, 2.0, 4.0),  # higher RR
    ]

    # supertrend: period, mult, atr_n, sl_m, tp_m
    supertrend_grid = [
        (10, 2.0, 14, 2.0, 3.0),
        (10, 2.5, 14, 2.0, 3.0),
        (10, 3.0, 14, 2.0, 3.0),
        (14, 2.5, 14, 2.0, 3.0),
        (7, 2.0, 14, 1.5, 2.5),
        (10, 2.0, 14, 1.5, 2.5),
        (20, 3.0, 21, 2.0, 3.5),
        (10, 2.0, 14, 2.5, 4.0),
        (5, 1.5, 14, 1.5, 2.5),
        (14, 3.0, 14, 2.5, 4.0),
    ]

    # keltner: n, mult, atr_n, sl_m, tp_m
    keltner_grid = [
        (20, 1.5, 14, 1.5, 2.5),
        (20, 2.0, 14, 2.0, 3.0),
        (14, 1.5, 14, 1.5, 2.5),
        (30, 2.0, 21, 2.0, 3.0),
        (20, 1.0, 14, 1.0, 2.0),
        (50, 2.0, 21, 2.0, 3.0),
    ]

    # rsi: period, overbought, oversold, atr_n, sl_m, tp_m
    rsi_grid = [
        (14, 70, 30, 14, 1.5, 2.5),
        (7, 75, 25, 14, 1.5, 2.5),
        (21, 65, 35, 14, 1.5, 2.5),
        (14, 75, 25, 14, 2.0, 3.0),
        (14, 80, 20, 14, 1.5, 2.5),
    ]

    # donchian: n, atr_n, sl_m, tp_m
    donchian_grid = [
        (20, 14, 1.5, 2.5),
        (50, 21, 2.0, 3.0),
        (10, 14, 1.0, 2.0),
        (100, 21, 2.0, 3.0),
    ]

    print('Running parameter sweep on REAL MT5 data...\n')
    total_combos = 0
    for tf in TFS:
        for pair in PAIRS:
            df = load_mt5(pair, tf)
            if df is None:
                continue
            spread = get_real_spread(pair, tf)

            # EMA+MACD
            for params in ema_macd_grid:
                try:
                    b, s, a = v7_ema_macd_v2(df, *params)
                    st = backtest_spread(df, b, s, pair, a, params[4], params[5], max_hold=50, spread_points=spread)
                    if st and st['n'] >= 5:
                        st.update({'tf': tf, 'pair': pair.replace('.m',''), 'strat': 'ema_macd',
                                   'params': params, 'spread': spread, 'bars': len(df)})
                        results.append(st)
                except: pass

            # Supertrend
            for params in supertrend_grid:
                try:
                    b, s, a = v7_supertrend_v2(df, *params)
                    st = backtest_spread(df, b, s, pair, a, params[3], params[4], max_hold=50, spread_points=spread)
                    if st and st['n'] >= 5:
                        st.update({'tf': tf, 'pair': pair.replace('.m',''), 'strat': 'supertrend',
                                   'params': params, 'spread': spread, 'bars': len(df)})
                        results.append(st)
                except: pass

            # Keltner
            for params in keltner_grid:
                try:
                    b, s, a = v7_keltner_v2(df, *params)
                    st = backtest_spread(df, b, s, pair, a, params[3], params[4], max_hold=50, spread_points=spread)
                    if st and st['n'] >= 5:
                        st.update({'tf': tf, 'pair': pair.replace('.m',''), 'strat': 'keltner',
                                   'params': params, 'spread': spread, 'bars': len(df)})
                        results.append(st)
                except: pass

            # RSI
            for params in rsi_grid:
                try:
                    b, s, a = v7_rsi_meanrev(df, *params)
                    st = backtest_spread(df, b, s, pair, a, params[4], params[5], max_hold=50, spread_points=spread)
                    if st and st['n'] >= 5:
                        st.update({'tf': tf, 'pair': pair.replace('.m',''), 'strat': 'rsi',
                                   'params': params, 'spread': spread, 'bars': len(df)})
                        results.append(st)
                except: pass

            # Donchian
            for params in donchian_grid:
                try:
                    b, s, a = v7_donchian_v2(df, *params)
                    st = backtest_spread(df, b, s, pair, a, params[2], params[3], max_hold=50, spread_points=spread)
                    if st and st['n'] >= 5:
                        st.update({'tf': tf, 'pair': pair.replace('.m',''), 'strat': 'donchian',
                                   'params': params, 'spread': spread, 'bars': len(df)})
                        results.append(st)
                except: pass
            total_combos += len(ema_macd_grid) + len(supertrend_grid) + len(keltner_grid) + len(rsi_grid) + len(donchian_grid)

    print(f'Tested {total_combos} parameter combinations × 18 (pair,TF) = {total_combos * 18} backtests')
    print(f'Got {len(results)} valid results\n')

    # Sort by WR
    results.sort(key=lambda x: (x.get('wr', 0), x.get('total_pips', 0)), reverse=True)

    # WR >= 60%
    winners = [r for r in results if r.get('wr', 0) >= 60 and r.get('n', 0) >= 10]
    print(f'=== WR >= 60% (N>=10) — {len(winners)} candidates ===')
    print(f"{'TF':<5} {'PAIR':<8} {'STRAT':<12} {'N':>4} {'WR%':>6} {'PIPS':>8} {'PF':>5} {'PARAMS'}")
    for r in winners[:30]:
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<12} {r['n']:>4} {r['wr']:>6.1f} {r['total_pips']:>8.1f} {r['pf']:>5.2f} {r['params']}")

    # WR 50-60%
    winners50 = [r for r in results if 50 <= r.get('wr', 0) < 60 and r.get('n', 0) >= 10]
    print(f'\n=== WR 50-60% (N>=10) — {len(winners50)} candidates ===')
    for r in winners50[:30]:
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<12} {r['n']:>4} {r['wr']:>6.1f} {r['total_pips']:>8.1f} {r['pf']:>5.2f} {r['params']}")

    # Best per (TF, pair)
    print(f'\n=== BEST PER (TF, PAIR) by total_pips (N>=5) ===')
    best = {}
    for r in results:
        k = (r['pair'], r['tf'])
        if k not in best or r['total_pips'] > best[k]['total_pips']:
            best[k] = r
    for (pair, tf), r in sorted(best.items()):
        print(f"{tf:<5} {pair:<8} {r['strat']:<12} N={r['n']:>3} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>9.1f} PF={r['pf']:>4.2f} {r['params']}")

    # Best per (TF, pair) by WR (min N=10)
    print(f'\n=== BEST PER (TF, PAIR) by WR (N>=10) ===')
    best_wr = {}
    for r in results:
        if r.get('n', 0) < 10:
            continue
        k = (r['pair'], r['tf'])
        if k not in best_wr or r['wr'] > best_wr[k]['wr']:
            best_wr[k] = r
    for (pair, tf), r in sorted(best_wr.items()):
        print(f"{tf:<5} {pair:<8} {r['strat']:<12} N={r['n']:>3} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>9.1f} PF={r['pf']:>4.2f} {r['params']}")

    pd.DataFrame(results).to_csv('/codex-trading/backtest_v7_mt5_param_sweep.csv', index=False)
    print(f'\nFull: /codex-trading/backtest_v7_mt5_param_sweep.csv ({len(results)} entries)')
