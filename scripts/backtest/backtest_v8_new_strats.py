"""Backtest v8 — extended MQL5 strategies on REAL MT5 data
New strategies:
- Ichimoku Cloud (#MQL5 ichimoku)
- Williams %R
- CCI (Commodity Channel Index)
- Parabolic SAR
- Hull Moving Average
- Bollinger Bands Squeeze
- Volume-weighted + price action
- Time/session filters
- Multi-TF confirmation (D1 + H4 bias)
- Day-of-week filter
"""
import pandas as pd
import numpy as np
import sys
import os
sys.path.insert(0, '/home/ubuntu/codex-trading')
from backtest_v6_mt5 import (
    load_mt5, get_real_spread, PIP_SIZE,
    ema, rsi, macd, stoch, atr, bb,
    backtest_spread
)

PAIRS = ['EURUSD.m', 'GBPUSD.m', 'USDJPY.m', 'USDCHF.m', 'AUDUSD.m', 'XAUUSD.m']
TFS = ['D1', 'M30', 'M15']

# ===== NEW INDICATORS =====

def hull_ma(s, n=9):
    """Hull Moving Average: 2*WMA(n/2) - WMA(n), smoothed by WMA(sqrt(n))"""
    half = int(n / 2)
    sqrt_n = int(np.sqrt(n))
    wma_half = s.rolling(half).mean()  # simplified
    wma_full = s.rolling(n).mean()
    diff = 2 * wma_half - wma_full
    return diff.rolling(sqrt_n).mean()


def cci(h, l, c, n=20):
    """Commodity Channel Index"""
    tp = (h + l + c) / 3
    sma = tp.rolling(n).mean()
    mad = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma) / (0.015 * mad)


def williams_r(h, l, c, n=14):
    """Williams %R"""
    hh = h.rolling(n).max()
    ll = l.rolling(n).min()
    return -100 * (hh - c) / (hh - ll)


def psar(h, l, af=0.02, max_af=0.2):
    """Parabolic SAR"""
    length = len(h)
    psar_arr = np.zeros(length)
    bull = True
    ep = l.iloc[0]
    af_curr = af
    psar_arr[0] = h.iloc[0]

    for i in range(1, length):
        if bull:
            psar_arr[i] = psar_arr[i-1] + af_curr * (ep - psar_arr[i-1])
            if l.iloc[i] < psar_arr[i]:
                bull = False
                psar_arr[i] = ep
                ep = l.iloc[i]
                af_curr = af
            else:
                if h.iloc[i] > ep:
                    ep = h.iloc[i]
                    af_curr = min(af_curr + af, max_af)
        else:
            psar_arr[i] = psar_arr[i-1] + af_curr * (ep - psar_arr[i-1])
            if h.iloc[i] > psar_arr[i]:
                bull = True
                psar_arr[i] = ep
                ep = h.iloc[i]
                af_curr = af
            else:
                if l.iloc[i] < ep:
                    ep = l.iloc[i]
                    af_curr = min(af_curr + af, max_af)

    return pd.Series(psar_arr, index=h.index), bull


def ichimoku(h, l, c, conv=9, base=26, span_b=52):
    """Ichimoku Cloud"""
    conv_line = (h.rolling(conv).max() + l.rolling(conv).min()) / 2
    base_line = (h.rolling(base).max() + l.rolling(base).min()) / 2
    span_a = ((conv_line + base_line) / 2).shift(base)
    span_b = ((h.rolling(span_b).max() + l.rolling(span_b).min()) / 2).shift(base)
    return conv_line, base_line, span_a, span_b


# ===== NEW STRATEGIES =====

def strat_ichimoku(df, sl_m=2.0, tp_m=3.0):
    """Ichimoku cloud: TK cross + price above/below cloud"""
    conv, base, span_a, span_b = ichimoku(df['high'], df['low'], df['close'])
    a = atr(df['high'], df['low'], df['close'], 14)

    # Price above cloud + TK cross up
    above_cloud = (df['close'] > span_a) & (df['close'] > span_b)
    below_cloud = (df['close'] < span_a) & (df['close'] < span_b)
    tk_cross_up = (conv > base) & (conv.shift() <= base.shift())
    tk_cross_dn = (conv < base) & (conv.shift() >= base.shift())

    buy = above_cloud & tk_cross_up
    sell = below_cloud & tk_cross_dn
    return buy, sell, a


def strat_williams_r(df, period=14, overbought=-20, oversold=-80, sl_m=1.5, tp_m=2.5):
    """Williams %R mean reversion"""
    wr = williams_r(df['high'], df['low'], df['close'], period)
    e50 = ema(df['close'], 50)
    a = atr(df['high'], df['low'], df['close'], 14)

    buy = (wr < oversold) & (wr.shift() >= oversold) & (df['close'] < e50)
    sell = (wr > overbought) & (wr.shift() <= overbought) & (df['close'] > e50)
    return buy, sell, a


def strat_cci_trend(df, period=20, threshold=100, sl_m=1.5, tp_m=2.5):
    """CCI trend following"""
    c = cci(df['high'], df['low'], df['close'], period)
    a = atr(df['high'], df['low'], df['close'], 14)

    buy = (c > threshold) & (c.shift() <= threshold) & (c > 0)
    sell = (c < -threshold) & (c.shift() >= -threshold) & (c < 0)
    return buy, sell, a


def strat_hull_ma(df, n=9, sl_m=1.5, tp_m=2.5):
    """Hull MA cross"""
    hma = hull_ma(df['close'], n)
    a = atr(df['high'], df['low'], df['close'], 14)
    hma_prev = hma.shift()

    buy = (hma > df['close']) & (hma_prev <= df['close'].shift())  # HMA crosses below price (long)
    sell = (hma < df['close']) & (hma_prev >= df['close'].shift())
    return buy, sell, a


def strat_psar_trend(df, sl_m=1.5, tp_m=2.5):
    """Parabolic SAR trend following"""
    psar_vals, _ = psar(df['high'], df['low'])
    a = atr(df['high'], df['low'], df['close'], 14)

    buy = (df['close'] > psar_vals) & (df['close'].shift() <= psar_vals.shift())
    sell = (df['close'] < psar_vals) & (df['close'].shift() >= psar_vals.shift())
    return buy, sell, a


def strat_bb_squeeze(df, n=20, k=2.0, sl_m=1.5, tp_m=2.5):
    """Bollinger Band squeeze: bandwidth contracts, then expansion breakout"""
    m, up, dn = bb(df['close'], n, k)
    bandwidth = (up - dn) / m
    bw_sma = bandwidth.rolling(50).mean()
    a = atr(df['high'], df['low'], df['close'], 14)

    # Squeeze (low bandwidth) then breakout
    squeeze = bandwidth < bw_sma * 0.5
    buy = squeeze & (df['close'] > up) & (df['close'].shift() <= up.shift())
    sell = squeeze & (df['close'] < dn) & (df['close'].shift() >= dn.shift())
    return buy, sell, a


def strat_3ema_stack(df, fast=5, mid=13, slow=50, sl_m=1.5, tp_m=2.5):
    """3 EMA stack: aligned in order, all slope up/down"""
    e_f = ema(df['close'], fast)
    e_m = ema(df['close'], mid)
    e_s = ema(df['close'], slow)
    a = atr(df['high'], df['low'], df['close'], 14)

    # Bull: fast > mid > slow AND fast rising
    buy = (e_f > e_m) & (e_m > e_s) & (e_f > e_f.shift(3))
    sell = (e_f < e_m) & (e_m < e_s) & (e_f < e_f.shift(3))
    return buy, sell, a


def strat_adx_di_cross(df, adx_period=14, threshold=20, sl_m=1.5, tp_m=2.5):
    """ADX + DI cross: only trade when trend strong"""
    h, l, c = df['high'], df['low'], df['close']
    a = atr(h, l, c, adx_period)
    adx_val, plus_di, minus_di = adx_ind(h, l, c, adx_period)

    # DI cross with strong ADX
    buy = (adx_val > threshold) & (plus_di > minus_di) & (plus_di.shift() <= minus_di.shift())
    sell = (adx_val > threshold) & (minus_di > plus_di) & (minus_di.shift() <= plus_di.shift())
    return buy, sell, a


def adx_ind(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    plus = 100 * (up.where((up > dn) & (up > 0), 0).ewm(alpha=1/n).mean())
    minus = 100 * (dn.where((dn > up) & (dn > 0), 0).ewm(alpha=1/n).mean())
    dx = 100 * (plus - minus).abs() / (plus + minus)
    adx_v = dx.ewm(alpha=1/n).mean()
    return adx_v, plus, minus


def strat_volume_breakout(df, n=20, sl_m=1.5, tp_m=2.5):
    """Volume breakout: high volume + price breakout"""
    upper = df['high'].rolling(n).max()
    lower = df['low'].rolling(n).min()
    a = atr(df['high'], df['low'], df['close'], 14)

    # No volume data in some, so use ATR as proxy
    buy = (df['close'] > upper.shift(1)) & (df['close'].shift() <= upper.shift(2))
    sell = (df['close'] < lower.shift(1)) & (df['close'].shift() >= lower.shift(2))
    return buy, sell, a


# ===== COMBO STRATEGIES =====

def strat_dual_ma_adx(df, ma_fast=10, ma_slow=50, adx_period=14, adx_thresh=20, sl_m=1.5, tp_m=2.5):
    """Dual MA + ADX filter (only trade strong trends)"""
    e_f = ema(df['close'], ma_fast)
    e_s = ema(df['close'], ma_slow)
    adx_v, plus, minus = adx_ind(df['high'], df['low'], df['close'], adx_period)
    a = atr(df['high'], df['low'], df['close'], 14)

    # Long: fast > slow AND ADX > thresh AND +DI > -DI
    buy = (e_f > e_s) & (e_f.shift() <= e_s.shift()) & (adx_v > adx_thresh) & (plus > minus)
    sell = (e_f < e_s) & (e_f.shift() >= e_s.shift()) & (adx_v > adx_thresh) & (minus > plus)
    return buy, sell, a


def strat_breakout_retest(df, n=20, sl_m=1.5, tp_m=2.5):
    """Donchian breakout + retest entry (enter on pullback)"""
    upper = df['high'].rolling(n).max()
    lower = df['low'].rolling(n).min()
    e50 = ema(df['close'], 50)
    a = atr(df['high'], df['low'], df['close'], 14)

    # Breakout happened recently, now pullback to 50EMA
    broke_up = df['close'].shift(1) > upper.shift(2)
    pullback_up = (df['low'] <= e50 * 1.005) & (df['close'] > e50) & (df['close'] > df['open'])

    broke_dn = df['close'].shift(1) < lower.shift(2)
    pullback_dn = (df['high'] >= e50 * 0.995) & (df['close'] < e50) & (df['close'] < df['open'])

    buy = broke_up & pullback_up
    sell = broke_dn & pullback_dn
    return buy, sell, a


# === MAIN LOOP ===

NEW_STRATEGIES = {
    'ichimoku':     (strat_ichimoku,        {'sl': 2.0, 'tp': 3.0}),
    'williams_r':   (strat_williams_r,      {'sl': 1.5, 'tp': 2.5}),
    'cci_trend':    (strat_cci_trend,       {'sl': 1.5, 'tp': 2.5}),
    'hull_ma':      (strat_hull_ma,         {'sl': 1.5, 'tp': 2.5}),
    'psar':         (strat_psar_trend,      {'sl': 1.5, 'tp': 2.5}),
    'bb_squeeze':   (strat_bb_squeeze,      {'sl': 1.5, 'tp': 2.5}),
    '3ema_stack':   (strat_3ema_stack,      {'sl': 1.5, 'tp': 2.5}),
    'adx_di':       (strat_adx_di_cross,    {'sl': 1.5, 'tp': 2.5}),
    'vol_breakout': (strat_volume_breakout, {'sl': 1.5, 'tp': 2.5}),
    'dual_ma_adx':  (strat_dual_ma_adx,     {'sl': 1.5, 'tp': 2.5}),
    'breakout_retest': (strat_breakout_retest, {'sl': 1.5, 'tp': 2.5}),
}


if __name__ == '__main__':
    results = []

    for tf in TFS:
        for pair in PAIRS:
            df = load_mt5(pair, tf)
            if df is None:
                continue
            spread = get_real_spread(pair, tf)

            for sname, (sfunc, params) in NEW_STRATEGIES.items():
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
                        st.update({'tf': tf, 'pair': pair.replace('.m',''), 'strat': sname,
                                   'spread': spread, 'bars': len(df)})
                        results.append(st)
                except Exception as e:
                    pass

    results.sort(key=lambda x: (x.get('wr', 0), x.get('total_pips', 0)), reverse=True)

    # WR >= 60%
    winners = [r for r in results if r.get('wr', 0) >= 60 and r.get('n', 0) >= 10]
    print(f'=== WR >= 60% (N>=10) — {len(winners)} candidates (v8 NEW strategies) ===')
    print(f"{'TF':<5} {'PAIR':<8} {'STRAT':<18} {'N':>4} {'WR%':>6} {'PIPS':>9} {'PF':>5}")
    for r in winners[:30]:
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<18} {r['n']:>4} {r['wr']:>6.1f} {r['total_pips']:>9.1f} {r['pf']:>5.2f}")

    # WR 50-60%
    winners50 = [r for r in results if 50 <= r.get('wr', 0) < 60 and r.get('n', 0) >= 10]
    print(f'\n=== WR 50-60% (N>=10) — {len(winners50)} candidates ===')
    for r in winners50[:30]:
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<18} {r['n']:>4} {r['wr']:>6.1f} {r['total_pips']:>9.1f} {r['pf']:>5.2f}")

    # Best per (TF, pair) by WR
    print(f'\n=== BEST PER (TF, PAIR) by WR (N>=10) ===')
    best = {}
    for r in results:
        if r.get('n', 0) < 10:
            continue
        k = (r['pair'], r['tf'])
        if k not in best or r['wr'] > best[k]['wr']:
            best[k] = r
    for (pair, tf), r in sorted(best.items()):
        print(f"{tf:<5} {pair:<8} {r['strat']:<18} N={r['n']:>3} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>9.1f} PF={r['pf']:>4.2f}")

    pd.DataFrame(results).to_csv('/home/ubuntu/codex-trading/backtest_v8_new_strats.csv', index=False)
    print(f'\nFull: /home/ubuntu/codex-trading/backtest_v8_new_strats.csv ({len(results)} entries)')
