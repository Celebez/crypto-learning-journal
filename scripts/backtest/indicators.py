"""CSV-only crypto indicators for the momentum and mean-reversion segment."""

from typing import Dict, List

from shared.utils import Candle, calculate_atr, calculate_bb, calculate_macd, calculate_rsi


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _return(closes: List[float], periods: int) -> float:
    if len(closes) <= periods or closes[-periods - 1] == 0:
        return 0.0
    return closes[-1] / closes[-periods - 1] - 1.0


def calculate_funding_signal(funding_rate: float) -> float:
    """Contrarian signal from a funding-rate value expressed as a decimal."""
    return -_clamp(funding_rate / 0.0015)


def calculate_oi_signal(oi_change_pct: float, price_change_pct: float) -> float:
    """Directional conviction proxy from OI and price percentage changes."""
    oi_strength = _clamp(abs(oi_change_pct) / 10.0, 0.0, 1.0)
    price_direction = _clamp(price_change_pct / 4.0)
    return price_direction * (0.4 + 0.6 * oi_strength)


def calculate_volume_signal(volumes: List[float], lookback: int = 20) -> float:
    """Volume activity score. Direction is applied by the strategy."""
    if len(volumes) < lookback:
        return 0.0
    average = sum(volumes[-lookback:]) / lookback
    if average <= 0:
        return 0.0
    return _clamp(volumes[-1] / average - 1.0)


def calculate_volume_profile_signal(candles: List[Candle], lookback: int = 30) -> float:
    """Estimate price acceptance using a volume-weighted typical price."""
    if len(candles) < lookback:
        return 0.0
    window = candles[-lookback:]
    total_volume = sum(c.volume for c in window)
    if total_volume <= 0:
        return 0.0
    value_area = sum(((c.high + c.low + c.close) / 3.0) * c.volume for c in window) / total_volume
    atr = calculate_atr(
        [c.high for c in candles],
        [c.low for c in candles],
        [c.close for c in candles],
    )
    return _clamp((candles[-1].close - value_area) / (2.0 * atr)) if atr > 0 else 0.0


def calculate_bb_squeeze_signal(closes: List[float], lookback: int = 20) -> float:
    """Return squeeze intensity from Bollinger Band width compression."""
    if len(closes) < lookback * 2:
        return 0.0
    widths = []
    for end in range(len(closes) - lookback + 1, len(closes) + 1):
        widths.append(calculate_bb(closes[:end], period=lookback)[3])
    average = sum(widths) / len(widths)
    return _clamp((average - widths[-1]) / average, 0.0, 1.0) if average > 0 else 0.0


def calculate_indicators(candles: List[Candle]) -> Dict[str, float]:
    """Calculate crypto indicators and candle-derived market-data proxies."""
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    volumes = [c.volume for c in candles]
    atr = calculate_atr(highs, lows, closes)
    macd_line, macd_signal, macd_histogram = calculate_macd(closes)
    bb_upper, bb_lower, bb_middle, bb_width = calculate_bb(closes)

    momentum_6 = _return(closes, 6)
    momentum_30 = _return(closes, 30)
    volume_average = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0.0
    volume_ratio = volumes[-1] / volume_average if volume_average > 0 else 1.0

    # With CSV-only candles, momentum estimates crowded perpetual positioning and
    # turnover/volume estimates OI participation. These are proxies, not live feeds.
    funding_rate_proxy = momentum_6 * 0.025
    oi_trend_proxy = (volume_ratio - 1.0) * 100.0
    trend_alignment = _clamp(momentum_30 / 0.10)

    return {
        "atr": atr,
        "rsi": calculate_rsi(closes),
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "macd_histogram": macd_histogram,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_middle": bb_middle,
        "bb_width": bb_width,
        "bb_squeeze": calculate_bb_squeeze_signal(closes),
        "funding_rate_proxy": funding_rate_proxy,
        "funding_signal": calculate_funding_signal(funding_rate_proxy),
        "oi_trend_proxy": oi_trend_proxy,
        "oi_signal": calculate_oi_signal(oi_trend_proxy, momentum_6 * 100.0),
        "volume_profile": calculate_volume_profile_signal(candles),
        "volume_activity": calculate_volume_signal(volumes),
        "momentum": _clamp(momentum_6 / 0.04),
        "trend_alignment": trend_alignment,
    }
