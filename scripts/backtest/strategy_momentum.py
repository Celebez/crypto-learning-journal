"""Simple momentum strategy: RSI + Bollinger Bands.

Entry conditions are intentionally loose compared to strategy_v2 — the goal
is more frequent trades so the bot is not stuck in HOLD forever.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from shared.utils import Candle


@dataclass
class _Indicators:
    closes: List[float]
    rsi: List[float]
    bb_upper: List[float]
    bb_middle: List[float]
    bb_lower: List[float]
    bb_width: List[float]


def _calc_rsi(closes: List[float], period: int = 14) -> List[float]:
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    result = [50.0] * len(closes)
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))
    return result


def _calc_bollinger(closes: List[float], period: int = 20, num_std: float = 2.0):
    n = len(closes)
    upper = [0.0] * n
    middle = [0.0] * n
    lower = [0.0] * n
    width = [0.0] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = variance ** 0.5
        middle[i] = sma
        upper[i] = sma + num_std * std
        lower[i] = sma - num_std * std
        width[i] = (upper[i] - lower[i]) / sma if sma > 0 else 0
    return upper, middle, lower, width


class MomentumStrategy:
    """RSI + Bollinger Bands momentum — more aggressive than V2."""

    RSI_PERIOD = 14
    BB_PERIOD = 20
    BB_STD = 2.0

    # Entry thresholds — intentionally loose
    RSI_OVERSOLD = 45.0      # buy when RSI < 45 (aggressive)
    RSI_OVERBOUGHT = 55.0    # sell when RSI > 55 (aggressive)
    BB_SQUEEZE_THRESHOLD = 0.04  # width < 4% = squeeze → breakout potential

    TP_PCT = 0.004   # 0.4% take profit
    SL_PCT = 0.012   # 1.2% stop loss
    MIN_HISTORY = 30  # less history needed

    def __init__(self):
        self._cache: Optional[_Indicators] = None

    def _compute(self, closes: List[float]) -> _Indicators:
        if (self._cache is not None
                and len(self._cache.closes) == len(closes)
                and self._cache.closes[0] == closes[0]
                and self._cache.closes[-1] == closes[-1]):
            return self._cache
        rsi = _calc_rsi(closes, self.RSI_PERIOD)
        bb_upper, bb_middle, bb_lower, bb_width = _calc_bollinger(
            closes, self.BB_PERIOD, self.BB_STD
        )
        self._cache = _Indicators(
            closes=closes, rsi=rsi,
            bb_upper=bb_upper, bb_middle=bb_middle,
            bb_lower=bb_lower, bb_width=bb_width,
        )
        return self._cache

    def generate_signal(self, candles: List[Candle], index: int) -> Dict[str, Optional[float]]:
        if index < self.MIN_HISTORY or index >= len(candles):
            return {"direction": None, "confidence": 0}

        closes = [c.close for c in candles]
        ind = self._compute(closes)

        price = candles[index].close
        rsi = ind.rsi[index]
        prev_rsi = ind.rsi[index - 1]
        bb_upper = ind.bb_upper[index]
        bb_lower = ind.bb_lower[index]
        bb_middle = ind.bb_middle[index]
        bb_width = ind.bb_width[index]
        prev_close = candles[index - 1].close

        # --- BUY: RSI recovering from oversold + price near lower BB ---
        rsi_rising = rsi > prev_rsi
        near_lower_bb = price <= bb_middle * 1.002  # within 0.2% of middle or below
        rsi_not_extreme = rsi < 55  # RSI < 55

        if rsi < self.RSI_OVERSOLD and rsi_rising and near_lower_bb:
            return self._trade("BUY", price)
        # Alternative buy: RSI oversold + price below middle BB (no need for rising RSI)
        if rsi < self.RSI_OVERSOLD and price < bb_middle:
            return self._trade("BUY", price)
        # Alternative buy: BB squeeze breakout (price breaks above middle BB with momentum)
        if (bb_width < self.BB_SQUEEZE_THRESHOLD
                and price > bb_middle and prev_close <= bb_middle
                and rsi < 55):
            return self._trade("BUY", price)

        # --- SELL: RSI falling from overbought + price near upper BB ---
        rsi_falling = rsi < prev_rsi
        near_upper_bb = price >= bb_middle * 0.998  # within 0.2% of middle or above

        if rsi > self.RSI_OVERBOUGHT and rsi_falling and near_upper_bb:
            return self._trade("SELL", price)
        # Alternative sell: RSI overbought + price above middle BB
        if rsi > self.RSI_OVERBOUGHT and price > bb_middle:
            return self._trade("SELL", price)
        # Alternative sell: BB squeeze breakdown
        if (bb_width < self.BB_SQUEEZE_THRESHOLD
                and price < bb_middle and prev_close >= bb_middle
                and rsi > 45):
            return self._trade("SELL", price)

        return {"direction": None, "confidence": 0}

    def _trade(self, direction: str, price: float):
        sign = 1.0 if direction == "BUY" else -1.0
        return {
            "direction": direction,
            "stop_loss": price - sign * price * self.SL_PCT,
            "take_profit": price + sign * price * self.TP_PCT,
            "confidence": 70.0,
            "strategy": "momentum",
        }
