"""Backtest v11 — proven strategies on YAHOO D1 data with MT5 broker spread
Tests: does the strategy generalize beyond MT5 data?
Yahoo: 22-30 years D1 history
MT5 spread: JustMarkets real
"""
import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '/home/ubuntu/codex-trading')
from backtest_v6_mt5 import (
    ema, rsi, macd, atr, bb, backtest_spread
)

PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'XAUUSD']

# JustMarkets MT5 spread (in points, 1 point = 0.0001 for forex, 0.01 for XAU)
# Median from MT5 prices.json
SPREAD_PIPS = {
    'EURUSD': 1.5,   # 0.00015
    'GBPUSD': 3.0,   # 0.00030
    'USDJPY': 2.7,   # 0.027 (USDJPY uses 0.01 pip)
    'USDCHF': 2.0,   # 0.00020
    'AUDUSD': 1.9,   # 0.00019
    'XAUUSD': 28.0,  # 0.28 (XAU uses 0.01 pip)
}


def load_yahoo(pair, tf='D1'):
    p = f'/home/ubuntu/codex-trading/backtest/data/{pair}_{tf}_yahoo.csv'
    df = pd.read_csv(p)
    # Yahoo CSV: Date, Open, High, Low, Close, Adj Close, Volume
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col], utc=True, errors='coerce')
    df = df.dropna(subset=[date_col]).set_index(date_col)
    df.columns = [str(c).lower() for c in df.columns]
    keep = [c for c in ['open', 'high', 'low', 'close', 'volume'] if c in df.columns]
    df = df[keep]
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.dropna()


# ===== PROVEN STRATEGIES =====

def strat_supertrend(df, period=10, mult=2.0):
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


def strat_supertrend_adx(df, st_period=10, st_mult=2.0, adx_thresh=15, sl_m=1.5, tp_m=2.5):
    a = atr(df['high'], df['low'], df['close'], st_period)
    hl2 = (df['high'] + df['low']) / 2
    upper = hl2 + st_mult * a
    lower = hl2 - st_mult * a

    direction = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df['close'].iloc[i] > upper.iloc[i-1]:
            direction.iloc[i] = 1
        elif df['close'].iloc[i] < lower.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]

    # ADX
    up = df['high'].diff()
    dn = -df['low'].diff()
    plus = 100 * (up.where((up > dn) & (up > 0), 0).ewm(alpha=1/14).mean())
    minus = 100 * (dn.where((dn > up) & (dn > 0), 0).ewm(alpha=1/14).mean())
    dx = 100 * (plus - minus).abs() / (plus + minus)
    adx_v = dx.ewm(alpha=1/14).mean()

    buy = (direction == 1) & (direction.shift(1) == -1) & (adx_v > adx_thresh)
    sell = (direction == -1) & (direction.shift(1) == 1) & (adx_v > adx_thresh)
    return buy, sell, atr(df['high'], df['low'], df['close'], 14)


def strat_ema_macd(df, ema_f=5, ema_s=13, ema_t=50, sl_m=1.5, tp_m=2.5):
    e_f = ema(df['close'], ema_f)
    e_s = ema(df['close'], ema_s)
    e_t = ema(df['close'], ema_t)
    m, sig, hist = macd(df['close'], 12, 26, 9)
    r = rsi(df['close'], 7)

    buy = ((e_f > e_s) & (e_f.shift() <= e_s.shift()) & (m > sig) & (df['close'] > e_t)
           & (r > 40) & (r < 65) & (hist > 0))
    sell = ((e_f < e_s) & (e_f.shift() >= e_s.shift()) & (m < sig) & (df['close'] < e_t)
            & (r < 60) & (r > 35) & (hist < 0))
    return buy, sell, atr(df['high'], df['low'], df['close'], 14)


def strat_ichimoku(df, sl_m=2.0, tp_m=3.0):
    h, l, c = df['high'], df['low'], df['close']
    conv_line = (h.rolling(9).max() + l.rolling(9).min()) / 2
    base_line = (h.rolling(26).max() + l.rolling(26).min()) / 2
    span_a = ((conv_line + base_line) / 2).shift(26)
    span_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)

    above_cloud = (c > span_a) & (c > span_b)
    below_cloud = (c < span_a) & (c < span_b)
    tk_cross_up = (conv_line > base_line) & (conv_line.shift() <= base_line.shift())
    tk_cross_dn = (conv_line < base_line) & (conv_line.shift() >= base_line.shift())

    buy = above_cloud & tk_cross_up
    sell = below_cloud & tk_cross_dn
    return buy, sell, atr(h, l, c, 14)


# ===== BACKTEST with broker spread =====

def backtest_spread_yahoo(df, buy_sig, sell_sig, pair, atr_vals, sl_m, tp_m, max_hold=50, spread_points=0):
    """Yahoo price is just close (no bid/ask), so apply spread as entry/exit slippage"""
    pip = 0.01 if 'JPY' in pair else (0.01 if pair == 'XAUUSD' else 0.0001)
    spread_price = spread_points * pip
    # For XAUUSD, spread_points in cents (1 point = 0.01 USD)
    # For others, spread_points in pips (1 pip = 0.0001 or 0.01 for JPY)

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
                bid_low = l - spread_price / 2
                if bid_low <= sl: exit_price = sl
                elif h >= tp: exit_price = tp
            else:
                ask_high = h + spread_price / 2
                if ask_high >= sl: exit_price = sl
                elif l <= tp: exit_price = tp

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


# ===== MAIN LOOP =====

if __name__ == '__main__':
    results = []

    # Configurations to test (proven winners from MT5 backtest)
    configs = [
        ('supertrend (10,2.0,14,1.5,2.5)', 'supertrend', {'period': 10, 'mult': 2.0}, {'sl': 1.5, 'tp': 2.5}),
        ('supertrend (7,2.0,14,1.5,2.5)', 'supertrend', {'period': 7, 'mult': 2.0}, {'sl': 1.5, 'tp': 2.5}),
        ('supertrend (10,2.0,14,2.5,4.0)', 'supertrend', {'period': 10, 'mult': 2.0}, {'sl': 2.5, 'tp': 4.0}),
        ('supertrend (14,3.0,14,2.5,4.0)', 'supertrend', {'period': 14, 'mult': 3.0}, {'sl': 2.5, 'tp': 4.0}),
        ('super_adx15', 'supertrend_adx', {'st_period': 10, 'st_mult': 2.0, 'adx_thresh': 15}, {'sl': 1.5, 'tp': 2.5}),
        ('super_adx20', 'supertrend_adx', {'st_period': 10, 'st_mult': 2.0, 'adx_thresh': 20}, {'sl': 1.5, 'tp': 2.5}),
        ('ema_macd (5,13,50,1.5,2.5)', 'ema_macd', {'ema_f': 5, 'ema_s': 13, 'ema_t': 50}, {'sl': 1.5, 'tp': 2.5}),
        ('ema_macd (3,10,50,1.5,2.5)', 'ema_macd', {'ema_f': 3, 'ema_s': 10, 'ema_t': 50}, {'sl': 1.5, 'tp': 2.5}),
        ('ema_macd (5,13,50,2.0,3.0)', 'ema_macd', {'ema_f': 5, 'ema_s': 13, 'ema_t': 50}, {'sl': 2.0, 'tp': 3.0}),
        ('ema_macd (5,13,50,1.0,2.0)', 'ema_macd', {'ema_f': 5, 'ema_s': 13, 'ema_t': 50}, {'sl': 1.0, 'tp': 2.0}),
        ('ichimoku (9,26,52)', 'ichimoku', {}, {'sl': 1.5, 'tp': 2.5}),
    ]

    for cfg_name, strat_name, strat_params, sltp in configs:
        for pair in PAIRS:
            df = load_yahoo(pair, 'D1')
            if df is None:
                continue
            spread = SPREAD_PIPS[pair]

            try:
                if strat_name == 'supertrend':
                    b, s = strat_supertrend(df, **strat_params)
                    a = atr(df['high'], df['low'], df['close'], 14)
                elif strat_name == 'supertrend_adx':
                    b, s, a = strat_supertrend_adx(df, **strat_params)
                elif strat_name == 'ema_macd':
                    b, s, a = strat_ema_macd(df, **strat_params)
                elif strat_name == 'ichimoku':
                    b, s, a = strat_ichimoku(df)

                st = backtest_spread_yahoo(df, b, s, pair, a, sltp['sl'], sltp['tp'],
                                            max_hold=50, spread_points=spread)
                if st and st['n'] >= 10:
                    st['cfg'] = cfg_name
                    st['pair'] = pair
                    st['spread'] = spread
                    st['bars'] = len(df)
                    st['date_range'] = f"{df.index[0].date()} → {df.index[-1].date()}"
                    results.append(st)
            except Exception as e:
                pass

    # Sort by WR then total pips
    results.sort(key=lambda x: (x.get('wr', 0), x.get('total_pips', 0)), reverse=True)

    print('='*80)
    print('YAHOO D1 + MT5 SPREAD — PROVEN STRATEGIES (real broker spread applied)')
    print('='*80)

    print(f'\n{"PAIR":<8} {"STRATEGY":<35} {"N":>4} {"WR%":>6} {"PIPS":>9} {"PF":>5} {"BARS":>6} {"RANGE"}')
    print('-'*120)
    for r in results:
        print(f"{r['pair']:<8} {r['cfg']:<35} {r['n']:>4} {r['wr']:>6.1f} {r['total_pips']:>9.1f} {r['pf']:>5.2f} {r['bars']:>6} {r['date_range']}")

    # WR >= 55% candidates
    winners = [r for r in results if r.get('wr', 0) >= 55 and r.get('n', 0) >= 15]
    print(f'\n=== WR >= 55% (N>=15) — {len(winners)} CANDIDATES (Yahoo validated) ===')
    for r in winners:
        print(f"{r['pair']:<8} {r['cfg']:<35} N={r['n']:>4} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>9.1f} PF={r['pf']:>4.2f}")

    # Per-pair best
    print(f'\n=== BEST PER PAIR (by WR) ===')
    best = {}
    for r in results:
        k = r['pair']
        if k not in best or r['wr'] > best[k]['wr']:
            best[k] = r
    for pair, r in sorted(best.items()):
        print(f"{pair:<8} {r['cfg']:<35} N={r['n']:>4} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>9.1f} PF={r['pf']:>4.2f}")

    # Aggregate
    print(f'\n=== AGGREGATE (all Yahoo results) ===')
    agg_n = sum(r['n'] for r in results)
    agg_pips = sum(r['total_pips'] for r in results)
    wins_total = sum(r['n'] * r['wr']/100 for r in results)
    agg_wr = wins_total / agg_n * 100 if agg_n else 0
    print(f'Total trades: {agg_n}, Aggregate WR: {agg_wr:.1f}%, Total pips: {agg_pips:.1f}')

    pd.DataFrame(results).to_csv('/home/ubuntu/codex-trading/backtest_v11_yahoo.csv', index=False)
    print(f'\nFull: /home/ubuntu/codex-trading/backtest_v11_yahoo.csv ({len(results)} entries)')

    # Compare to MT5 results
    print(f'\n=== COMPARISON: MT5 (D1) vs Yahoo (D1) — same strategies ===')
    mt5_results = {
        'EURUSD': {'cfg': 'supertrend (10,2.0,14,1.5,2.5)', 'n': 18, 'wr': 61.1, 'pips': 1067.7, 'pf': 2.04},
        'GBPUSD': {'cfg': 'ema_macd (3,10,50,1.5,2.5)', 'n': 16, 'wr': 56.2, 'pips': 1166.0, 'pf': 2.00},
        'AUDUSD': {'cfg': 'supertrend (10,2.0,14,1.5,2.5)', 'n': 8, 'wr': 62.5, 'pips': 586.7, 'pf': 2.95},
    }
    for pair, mt5 in mt5_results.items():
        yahoo = [r for r in results if r['pair'] == pair and r['cfg'] == mt5['cfg']]
        if yahoo:
            y = yahoo[0]
            wr_diff = y['wr'] - mt5['wr']
            pips_diff = y['total_pips'] - mt5['pips']
            n_diff = y['n'] - mt5['n']
            print(f"\n{pair} {mt5['cfg']}:")
            print(f"  MT5:   N={mt5['n']:>3} WR={mt5['wr']:>5.1f}% Pips={mt5['pips']:>7.1f} PF={mt5['pf']:.2f}")
            print(f"  Yahoo: N={y['n']:>3} WR={y['wr']:>5.1f}% Pips={y['total_pips']:>7.1f} PF={y['pf']:.2f}")
            print(f"  DIFF:  ΔN={n_diff:+} ΔWR={wr_diff:+.1f}% ΔPips={pips_diff:+.1f}")
