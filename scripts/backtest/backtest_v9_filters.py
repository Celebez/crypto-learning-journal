"""Backtest v9 — final iteration with filters, trailing stops, and consensus
Adds:
- ADX trend strength filter
- ATR volatility filter
- Trailing stop
- Multi-strategy consensus
- Day-of-week filter
- Best SL/TP ratios
"""
import pandas as pd
import numpy as np
import sys
sys.path.insert(0, '/home/ubuntu/codex-trading')
from backtest_v6_mt5 import (
    load_mt5, get_real_spread, PIP_SIZE,
    ema, rsi, macd, stoch, atr, bb,
    backtest_spread,
    strat_supertrend, strat_ema_macd_atr, strat_keltner_macd
)

PAIRS = ['EURUSD.m', 'GBPUSD.m', 'USDJPY.m', 'USDCHF.m', 'AUDUSD.m', 'XAUUSD.m']
TFS = ['D1', 'M30', 'M15']


def adx_ind(h, l, c, n=14):
    up = h.diff()
    dn = -l.diff()
    plus = 100 * (up.where((up > dn) & (up > 0), 0).ewm(alpha=1/n).mean())
    minus = 100 * (dn.where((dn > up) & (dn > 0), 0).ewm(alpha=1/n).mean())
    dx = 100 * (plus - minus).abs() / (plus + minus)
    return dx.ewm(alpha=1/n).mean(), plus, minus


# ===== FILTERED STRATEGIES =====

def v9_supertrend_adx(df, st_period=10, st_mult=2.0, adx_thresh=15, sl_m=1.5, tp_m=2.5):
    """Super Trend with ADX filter"""
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

    adx_v, _, _ = adx_ind(df['high'], df['low'], df['close'], 14)

    buy = (direction == 1) & (direction.shift(1) == -1) & (adx_v > adx_thresh)
    sell = (direction == -1) & (direction.shift(1) == 1) & (adx_v > adx_thresh)
    return buy, sell, atr(df['high'], df['low'], df['close'], 14)


def v9_ema_macd_adx(df, ema_f=5, ema_s=13, ema_t=50, adx_thresh=15, sl_m=1.5, tp_m=2.5):
    """EMA+MACD with ADX filter"""
    e_f = ema(df['close'], ema_f)
    e_s = ema(df['close'], ema_s)
    e_t = ema(df['close'], ema_t)
    m, sig, hist = macd(df['close'], 12, 26, 9)
    adx_v, plus, minus = adx_ind(df['high'], df['low'], df['close'], 14)
    r = rsi(df['close'], 7)

    buy = ((e_f > e_s) & (e_f.shift() <= e_s.shift()) & (m > sig) & (df['close'] > e_t)
           & (r > 40) & (r < 65) & (adx_v > adx_thresh))
    sell = ((e_f < e_s) & (e_f.shift() >= e_s.shift()) & (m < sig) & (df['close'] < e_t)
            & (r < 60) & (r > 35) & (adx_v > adx_thresh))
    return buy, sell, atr(df['high'], df['low'], df['close'], 14)


def v9_supertrend_trailing(df, st_period=10, st_mult=2.0, sl_m=1.5, tp_m=3.0):
    """Super Trend with TRAILING stop (moves to breakeven at 1x ATR)"""
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

    buy = (direction == 1) & (direction.shift(1) == -1)
    sell = (direction == -1) & (direction.shift(1) == 1)
    return buy, sell, atr(df['high'], df['low'], df['close'], 14), direction


def backtest_trailing(df, buy_sig, sell_sig, direction, pair, atr_vals, sl_m, tp_m, max_hold=50, spread_points=0):
    """Backtest with trailing stop at 1x ATR after 1x ATR profit"""
    pip = PIP_SIZE[pair]
    spread_price = spread_points * (0.0001 if 'JPY' not in pair and pair != 'XAUUSD.m' else 0.01)
    if pair == 'XAUUSD.m':
        spread_price = spread_points * 0.01

    trades = []
    in_trade = False
    side = 0
    entry = 0
    sl = 0
    tp = 0
    highest = 0
    lowest = 0
    entry_i = 0

    for i in range(1, len(df)):
        if not in_trade:
            if buy_sig.iloc[i]:
                side = 1
                entry = df['close'].iloc[i] + spread_price / 2
                a = atr_vals.iloc[i]
                if pd.isna(a) or a <= 0:
                    continue
                sl = entry - sl_m * a
                tp = entry + tp_m * a
                highest = entry
                in_trade = True
                entry_i = i
            elif sell_sig.iloc[i]:
                side = -1
                entry = df['close'].iloc[i] - spread_price / 2
                a = atr_vals.iloc[i]
                if pd.isna(a) or a <= 0:
                    continue
                sl = entry + sl_m * a
                tp = entry - tp_m * a
                lowest = entry
                in_trade = True
                entry_i = i
        else:
            h = df['high'].iloc[i]
            l = df['low'].iloc[i]
            a = atr_vals.iloc[i]
            exit_price = None

            if side == 1:
                # Trailing: raise SL if price > entry + 1 ATR
                if h > highest:
                    highest = h
                if highest > entry + a:
                    new_sl = highest - a
                    if new_sl > sl:
                        sl = new_sl

                bid_low = l - spread_price / 2
                if bid_low <= sl: exit_price = sl
                elif h >= tp: exit_price = tp
            else:
                if l < lowest:
                    lowest = l
                if lowest < entry - a:
                    new_sl = lowest + a
                    if new_sl < sl:
                        sl = new_sl

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


def v9_consensus_2(df, sl_m=1.5, tp_m=2.5):
    """2-strategy consensus: supertrend + ema_macd must agree"""
    b1, s1, a1 = strat_supertrend(df)
    b2, s2, a2 = strat_ema_macd_atr(df)

    buy = b1 & b2
    sell = s1 & s2
    return buy, sell, atr(df['high'], df['low'], df['close'], 14)


def v9_consensus_3(df, sl_m=1.5, tp_m=2.5):
    """3-strategy consensus: supertrend + ema_macd + keltner"""
    b1, s1 = strat_supertrend(df)
    b2, s2, a2 = strat_ema_macd_atr(df)
    b3, s3, a3 = strat_keltner_macd(df)

    buy = b1 & b2 & b3
    sell = s1 & s2 & s3
    return buy, sell, atr(df['high'], df['low'], df['close'], 14)


def v9_day_filter(df, sl_m=1.5, tp_m=2.5, day_to_trade=[0,1,2,3]):
    """Super trend, only Mon-Thu (avoid Friday close)"""
    b, s, a = strat_supertrend(df)
    weekday = df.index.dayofweek if hasattr(df.index, 'dayofweek') else pd.Series(df.index).dt.dayofweek
    day_mask = weekday.isin(day_to_trade)
    return b & day_mask, s & day_mask, a


# === MAIN ===

STRATS_V9 = {
    'super_adx15':  (v9_supertrend_adx,        {'sl': 1.5, 'tp': 2.5, 'adx': 15}),
    'super_adx20':  (v9_supertrend_adx,        {'sl': 1.5, 'tp': 2.5, 'adx': 20}),
    'super_adx25':  (v9_supertrend_adx,        {'sl': 1.5, 'tp': 2.5, 'adx': 25}),
    'ema_macd_adx15': (v9_ema_macd_adx,        {'sl': 1.5, 'tp': 2.5, 'adx': 15}),
    'ema_macd_adx20': (v9_ema_macd_adx,        {'sl': 1.5, 'tp': 2.5, 'adx': 20}),
    'super_trailing':  ('TRAILING',              {'sl': 1.5, 'tp': 3.0}),
    'super_trail_hi':  ('TRAILING',              {'sl': 1.0, 'tp': 4.0}),
    'consensus_2':     (v9_consensus_2,         {'sl': 1.5, 'tp': 2.5}),
    'consensus_3':     (v9_consensus_3,         {'sl': 2.0, 'tp': 3.0}),
    'mon_thu':         (v9_day_filter,          {'sl': 1.5, 'tp': 2.5, 'days': [0,1,2,3]}),
    'tue_thu':         (v9_day_filter,          {'sl': 1.5, 'tp': 2.5, 'days': [1,2,3]}),
}


if __name__ == '__main__':
    results = []

    for tf in TFS:
        for pair in PAIRS:
            df = load_mt5(pair, tf)
            if df is None:
                continue
            spread = get_real_spread(pair, tf)

            for sname, conf in STRATS_V9.items():
                try:
                    if conf == 'TRAILING':
                        out = v9_supertrend_trailing(df, st_period=10, st_mult=2.0, sl_m=1.5, tp_m=3.0)
                        b, s, a, direction = out
                        st = backtest_trailing(df, b, s, direction, pair, a, 1.5, 3.0, max_hold=50, spread_points=spread)
                    else:
                        sfunc, params = conf
                        if sname.startswith('super_adx') or sname.startswith('ema_macd_adx'):
                            out = sfunc(df, **{'adx_thresh': params.get('adx', 15)})
                            b, s, a = out
                            st = backtest_spread(df, b, s, pair, a, params['sl'], params['tp'],
                                                  max_hold=50, spread_points=spread)
                        elif sname.startswith('mon_thu') or sname.startswith('tue_thu'):
                            out = sfunc(df, day_to_trade=params['days'])
                            b, s, a = out
                            st = backtest_spread(df, b, s, pair, a, params['sl'], params['tp'],
                                                  max_hold=50, spread_points=spread)
                        else:
                            out = sfunc(df)
                            b, s, a = out
                            st = backtest_spread(df, b, s, pair, a, params['sl'], params['tp'],
                                                  max_hold=50, spread_points=spread)

                    if st and st['n'] >= 10:
                        st.update({'tf': tf, 'pair': pair.replace('.m',''), 'strat': sname,
                                   'spread': spread, 'bars': len(df)})
                        results.append(st)
                except Exception as e:
                    pass

    results.sort(key=lambda x: (x.get('wr', 0), x.get('total_pips', 0)), reverse=True)

    # WR >= 60%
    winners = [r for r in results if r.get('wr', 0) >= 60 and r.get('n', 0) >= 10]
    print(f'=== WR >= 60% (N>=10) — {len(winners)} candidates (v9 filter+trailing) ===')
    print(f"{'TF':<5} {'PAIR':<8} {'STRAT':<20} {'N':>4} {'WR%':>6} {'PIPS':>9} {'PF':>5}")
    for r in winners[:30]:
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<20} {r['n']:>4} {r['wr']:>6.1f} {r['total_pips']:>9.1f} {r['pf']:>5.2f}")

    # WR 50-60%
    winners50 = [r for r in results if 50 <= r.get('wr', 0) < 60 and r.get('n', 0) >= 10]
    print(f'\n=== WR 50-60% (N>=10) — {len(winners50)} candidates ===')
    for r in winners50[:30]:
        print(f"{r['tf']:<5} {r['pair']:<8} {r['strat']:<20} {r['n']:>4} {r['wr']:>6.1f} {r['total_pips']:>9.1f} {r['pf']:>5.2f}")

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
        print(f"{tf:<5} {pair:<8} {r['strat']:<20} N={r['n']:>3} WR={r['wr']:>5.1f}% Pips={r['total_pips']:>9.1f} PF={r['pf']:>4.2f}")

    pd.DataFrame(results).to_csv('/home/ubuntu/codex-trading/backtest_v9_filters.csv', index=False)
    print(f'\nFull: /home/ubuntu/codex-trading/backtest_v9_filters.csv ({len(results)} entries)')
