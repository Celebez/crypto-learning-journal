"""Trend-aligned pullback crypto strategy.

The strategy trades a recovery from a short-term pullback while the broader
4H trend is still intact.  All indicator values are calculated from candles at
or before ``index`` so signals can be evaluated without lookahead bias.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from shared.utils import Candle, calculate_ema


@dataclass
class _IndicatorCache:
    candles: List[Candle]
    candle_count: int
    closes: List[float]
    ema_fast: List[float]
    ema_trend: List[float]
    ema_regime: List[float]
    stochastic: List[float]
    vwap: List[float]
    average_volume: List[float]


def _calculate_stochastic_values(candles: List[Candle], period: int) -> List[float]:
    result = [50.0] * len(candles)
    for index in range(period - 1, len(candles)):
        window = candles[index - period + 1 : index + 1]
        low = min(candle.low for candle in window)
        high = max(candle.high for candle in window)
        result[index] = 100.0 * (candles[index].close - low) / (high - low) if high > low else 50.0
    return result


def _calculate_rolling_values(candles: List[Candle], period: int) -> tuple[List[float], List[float]]:
    vwap = [0.0] * len(candles)
    average_volume = [0.0] * len(candles)
    weighted_sum = 0.0
    volume_sum = 0.0
    for index, candle in enumerate(candles):
        typical_price = (candle.high + candle.low + candle.close) / 3.0
        weighted_sum += typical_price * candle.volume
        volume_sum += candle.volume
        if index >= period:
            old = candles[index - period]
            weighted_sum -= ((old.high + old.low + old.close) / 3.0) * old.volume
            volume_sum -= old.volume
        if index >= period - 1 and volume_sum > 0:
            vwap[index] = weighted_sum / volume_sum
            average_volume[index] = volume_sum / period
    return vwap, average_volume


class CryptoStrategy:
    """Enter trend-aligned pullbacks as short-term momentum resumes."""

    RISK_PER_TRADE = 0.005
    DAILY_STOP = 0.02
    MIN_HISTORY = 104
    FAST_EMA_PERIOD = 12
    TREND_EMA_PERIOD = 36
    REGIME_EMA_PERIOD = 100
    STOCHASTIC_PERIOD = 10
    VWAP_PERIOD = 24
    MIN_VOLUME_RATIO = 0.65
    TP_PCT = 0.003
    SL_PCT = 0.018

    def __init__(self) -> None:
        self._indicator_cache: Optional[_IndicatorCache] = None

    def generate_signal(
        self,
        candles: List[Candle],
        index: int,
        candles_1h: Optional[List[Candle]] = None,
    ) -> Dict[str, Optional[float]]:
        """Return a signal using only the completed 4H candles through ``index``."""
        if index < self.MIN_HISTORY or index >= len(candles):
            return self._hold()

        indicators = self._get_indicator_cache(candles)
        candle = candles[index]
        previous = candles[index - 1]
        price = candle.close
        vwap = indicators.vwap[index]
        average_volume = indicators.average_volume[index]
        if price <= 0 or vwap <= 0 or average_volume <= 0:
            return self._hold()

        ema_fast = indicators.ema_fast[index]
        ema_trend = indicators.ema_trend[index]
        ema_regime = indicators.ema_regime[index]
        stochastic = indicators.stochastic[index]
        previous_stochastic = indicators.stochastic[index - 1]
        candle_range = candle.high - candle.low
        if candle_range <= 0:
            return self._hold()
        if candle.volume <= average_volume * self.MIN_VOLUME_RATIO:
            return self._hold()

        lower_wick = min(candle.open, candle.close) - candle.low
        upper_wick = candle.high - max(candle.open, candle.close)
        bullish_recovery = candle.close > candle.open or candle.close > previous.close or lower_wick > candle_range * 0.35
        bearish_recovery = candle.close < candle.open or candle.close < previous.close or upper_wick > candle_range * 0.35
        long_pullback = price <= max(ema_fast, vwap) * 1.012
        short_pullback = price >= min(ema_fast, vwap) * 0.988

        if (
            ema_trend > ema_regime * 0.995
            and ema_fast >= ema_trend * 0.985
            and long_pullback
            and stochastic < 62.0
            and stochastic > previous_stochastic
            and bullish_recovery
        ):
            return self._trade("BUY", price)

        if (
            ema_trend < ema_regime * 1.005
            and ema_fast <= ema_trend * 1.015
            and short_pullback
            and stochastic > 38.0
            and stochastic < previous_stochastic
            and bearish_recovery
        ):
            return self._trade("SELL", price)

        return self._hold()

    def _get_indicator_cache(self, candles: List[Candle]) -> _IndicatorCache:
        cache = self._indicator_cache
        if cache is not None and cache.candles is candles and cache.candle_count == len(candles):
            return cache

        closes = [candle.close for candle in candles]
        vwap, average_volume = _calculate_rolling_values(candles, self.VWAP_PERIOD)
        cache = _IndicatorCache(
            candles=candles,
            candle_count=len(candles),
            closes=closes,
            ema_fast=calculate_ema(closes, self.FAST_EMA_PERIOD),
            ema_trend=calculate_ema(closes, self.TREND_EMA_PERIOD),
            ema_regime=calculate_ema(closes, self.REGIME_EMA_PERIOD),
            stochastic=_calculate_stochastic_values(candles, self.STOCHASTIC_PERIOD),
            vwap=vwap,
            average_volume=average_volume,
        )
        self._indicator_cache = cache
        return cache

    def _trade(self, direction: str, price: float) -> Dict[str, Optional[float]]:
        sign = 1.0 if direction == "BUY" else -1.0
        return {
            "direction": direction,
            "stop_loss": price - sign * price * self.SL_PCT,
            "take_profit": price + sign * price * self.TP_PCT,
            "confidence": 85.0,
        }

    @staticmethod
    def _hold() -> Dict[str, Optional[float]]:
        return {"direction": "HOLD", "stop_loss": None, "take_profit": None, "confidence": 0.0}
