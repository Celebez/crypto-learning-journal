"""
improved_bb_squeeze.py — Fixed Bollinger Band Squeeze Detection

Addresses the 0% success rate (3/3 failures) by requiring BOTH compression
AND release with volume confirmation and multi-timeframe alignment.

The old system triggered on compression alone, but compression is just
potential energy — it needs release (expansion) to produce a tradeable move.

Usage:
    detector = BBSqueezeDetector()
    squeeze = detect_bb_squeeze(current_data, history)
    released = validate_squeeze_release(squeeze, current_data, history)
    strength = get_squeeze_strength(squeeze)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    # Minimal fallback — numpy not strictly required for basic detection
    np = None  # type: ignore


class SqueezePhase(Enum):
    """Phases of a BB Squeeze lifecycle."""
    NONE = "NONE"
    COMPRESSION = "COMPRESSION"        # BBs narrowing, Keltner inside
    RELEASE_BULLISH = "RELEASE_BULLISH"  # Expansion with bullish breakout
    RELEASE_BEARISH = "RELEASE_BEARISH"  # Expansion with bearish breakout
    POST_RELEASE = "POST_RELEASE"      # After initial release move


@dataclass
class BBSqueezeData:
    """
    Bollinger Band and Keltner Channel data point.

    Note: We store raw values, not the squeeze indicator itself.
    The squeeze fires when BB is INSIDE Keltner Channel.
    """
    bb_upper: float
    bb_lower: float
    bb_middle: float
    kc_upper: float        # Keltner Channel upper
    kc_lower: float        # Keltner Channel lower
    close: float
    volume: float
    atr: float = 0.0       # Average True Range (used for KC calculation)
    timestamp: float = 0.0

    @property
    def bb_width(self) -> float:
        """Bollinger Band width (spread)."""
        return self.bb_upper - self.bb_lower

    @property
    def kc_width(self) -> float:
        """Keltner Channel width."""
        return self.kc_upper - self.kc_lower

    @property
    def is_squeezed(self) -> bool:
        """True if BB is inside KC (squeeze active)."""
        return self.bb_upper < self.kc_upper and self.bb_lower > self.kc_lower

    @property
    def bb_position(self) -> float:
        """Close position relative to BB range (0=lower, 1=upper)."""
        if self.bb_width < 1e-10:
            return 0.5
        return (self.close - self.bb_lower) / self.bb_width


@dataclass
class SqueezeResult:
    """
    Result of BB Squeeze detection and validation.

    Attributes:
        phase: Current phase of the squeeze lifecycle.
        is_valid: Whether this is a valid tradeable squeeze (compression + release).
        compression_duration: How many candles the squeeze has been active.
        release_volume_ratio: Volume ratio during release vs compression average.
        multi_tf_aligned: Whether multi-timeframe analysis agrees.
        strength: Overall squeeze strength 0.0 to 1.0.
        direction: Squeeze direction ("bullish", "bearish", "neutral").
        details: Human-readable explanation.
    """
    phase: SqueezePhase
    is_valid: bool
    compression_duration: int = 0
    release_volume_ratio: float = 0.0
    multi_tf_aligned: bool = False
    strength: float = 0.0
    direction: str = "neutral"
    details: str = ""

    @property
    def is_release(self) -> bool:
        return self.phase in (SqueezePhase.RELEASE_BULLISH, SqueezePhase.RELEASE_BEARISH)

    @property
    def is_bullish(self) -> bool:
        return self.phase == SqueezePhase.RELEASE_BULLISH


class BBSqueezeDetector:
    """
    Improved Bollinger Band Squeeze detector.

    Key fixes:
    1. Requires BOTH compression AND release (not just compression)
    2. Volume confirmation on release (volume spike required)
    3. Multi-timeframe confirmation support
    4. Proper lifecycle tracking (compression -> release -> post-release)
    """

    # Volume spike threshold: release volume must be this × average compression volume
    VOLUME_SPIKE_THRESHOLD = 1.3  # 30% above average

    # Minimum compression duration (candles)
    MIN_COMPRESSION_CANDLES = 3

    # Maximum compression duration before it's stale
    MAX_COMPRESSION_CANDLES = 50

    # BB width percentile for "compressed" state (relative to recent history)
    COMPRESSION_PERCENTILE = 25  # width must be in bottom 25%

    # Release expansion factor: BB width must expand by this factor
    RELEASE_EXPANSION_FACTOR = 1.5  # 50% wider than compressed

    def __init__(
        self,
        volume_spike_threshold: float = VOLUME_SPIKE_THRESHOLD,
        min_compression_candles: int = MIN_COMPRESSION_CANDLES,
    ):
        self.volume_spike_threshold = volume_spike_threshold
        self.min_compression_candles = min_compression_candles
        self._compression_start: Optional[int] = None
        self._compression_active: bool = False
        self._phase: SqueezePhase = SqueezePhase.NONE

    def _calculate_bb_percentile(
        self,
        history: List[BBSqueezeData],
        current_width: float,
        lookback: int = 20,
    ) -> float:
        """
        Calculate where current BB width falls in recent history.

        Returns percentile (0-100). Lower = more compressed.
        """
        if len(history) < 5:
            return 50.0  # neutral if insufficient data

        widths = [d.bb_width for d in history[-lookback:]]
        widths.append(current_width)
        widths.sort()

        rank = widths.index(current_width)
        return (rank / len(widths)) * 100

    def _is_volume_spike(
        self,
        current_volume: float,
        history: List[BBSqueezeData],
        lookback: int = 10,
    ) -> Tuple[bool, float]:
        """
        Check if current volume is a spike relative to recent average.

        Returns:
            Tuple of (is_spike, volume_ratio).
        """
        if len(history) < 3:
            return False, 1.0

        recent_volumes = [d.volume for d in history[-lookback:] if d.volume > 0]
        if not recent_volumes:
            return False, 1.0

        avg_volume = sum(recent_volumes) / len(recent_volumes)
        if avg_volume <= 0:
            return False, 1.0

        ratio = current_volume / avg_volume
        return ratio >= self.volume_spike_threshold, ratio

    def _determine_direction(self, current: BBSqueezeData, history: List[BBSqueezeData]) -> str:
        """Determine squeeze breakout direction based on price action and volume."""
        if not history:
            return "neutral"

        recent_closes = [d.close for d in history[-5:]] + [current.close]
        if len(recent_closes) < 3:
            return "neutral"

        # Simple: direction based on close relative to BB middle and recent momentum
        above_middle = current.close > current.bb_middle

        # Check momentum (recent price direction)
        momentum = recent_closes[-1] - recent_closes[-3] if len(recent_closes) >= 3 else 0

        if above_middle and momentum > 0:
            return "bullish"
        elif not above_middle and momentum < 0:
            return "bearish"
        else:
            return "neutral"

    def detect_bb_squeeze(
        self,
        current: BBSqueezeData,
        history: Optional[List[BBSqueezeData]] = None,
        higher_tf_aligned: Optional[bool] = None,
    ) -> SqueezeResult:
        """
        Detect BB Squeeze state.

        This determines the CURRENT PHASE but does NOT validate for trading.
        Use validate_squeeze_release() to check if it's actionable.

        Args:
            current: Current candle's BB/KC data.
            history: Recent candle history (newest last).
            higher_tf_aligned: Whether higher timeframe (e.g., 4H) shows
                             alignment with the 1H direction.

        Returns:
            SqueezeResult with phase and metadata.
        """
        if history is None:
            history = []

        all_data = history + [current]

        # Calculate compression metrics
        bb_percentile = self._calculate_bb_percentile(history, current.bb_width)
        is_squeezed = current.is_squeezed

        # Count compression duration
        compression_candles = 0
        for d in reversed(all_data[:-1]):
            if d.is_squeezed:
                compression_candles += 1
            else:
                break

        if is_squeezed:
            compression_candles += 1

        # Determine phase
        phase = SqueezePhase.NONE
        strength = 0.0
        direction = "neutral"
        details = ""
        is_valid = False

        # Check for release (expansion from compression)
        was_compressed = compression_candles >= self.min_compression_candles
        bb_expanding = False
        if len(history) >= 2:
            prev = history[-1]
            bb_expanding = current.bb_width > prev.bb_width * self.RELEASE_EXPANSION_FACTOR

        # Check volume spike
        is_volume_spike, volume_ratio = self._is_volume_spike(current.volume, history)

        if was_compressed and bb_expanding and not is_squeezed:
            # Release detected
            direction = self._determine_direction(current, history)
            if direction == "bullish":
                phase = SqueezePhase.RELEASE_BULLISH
            else:
                phase = SqueezePhase.RELEASE_BEARISH

            # Calculate strength
            strength = min(1.0, compression_candles / 10.0)  # longer compression = stronger
            if is_volume_spike:
                strength = min(1.0, strength + 0.2)  # volume spike bonus
            strength = min(1.0, strength + (volume_ratio - 1.0) * 0.1)

            # Validity requires volume spike AND close outside BB (actual breakout)
            close_outside_bb = (current.close > current.bb_upper) or (current.close < current.bb_lower)
            is_valid = is_volume_spike and close_outside_bb
            details = (
                f"Release detected after {compression_candles} candles of compression. "
                f"Volume ratio: {volume_ratio:.1f}x "
                f"({'spike confirmed' if is_volume_spike else 'NO volume spike'})"
                f"{'' if close_outside_bb else ' — close inside BB (not a breakout)'}"
            )

            self._compression_active = False

        elif is_squeezed:
            # Still in compression
            phase = SqueezePhase.COMPRESSION
            strength = max(0, (compression_candles - self.min_compression_candles) / 5.0)
            details = (
                f"Compression active: {compression_candles} candles, "
                f"BB percentile: {bb_percentile:.0f}%"
            )
            self._compression_active = True

        elif compression_candles > 0:
            # Post-release or recently ended compression
            phase = SqueezePhase.POST_RELEASE
            details = f"Compression ended ({compression_candles} candles), no expansion detected"
            self._compression_active = False

        else:
            details = "No squeeze pattern detected"
            self._compression_active = False

        # Multi-timeframe alignment
        multi_tf_aligned = higher_tf_aligned if higher_tf_aligned is not None else False

        result = SqueezeResult(
            phase=phase,
            is_valid=is_valid and multi_tf_aligned,
            compression_duration=compression_candles,
            release_volume_ratio=volume_ratio,
            multi_tf_aligned=multi_tf_aligned,
            strength=round(strength, 3),
            direction=direction,
            details=details,
        )

        logger.debug(
            f"BB Squeeze: phase={phase.value}, valid={result.is_valid}, "
            f"strength={strength:.2f}, vol_ratio={volume_ratio:.1f}, "
            f"multi_tf={multi_tf_aligned}"
        )

        return result

    def validate_squeeze_release(
        self,
        squeeze_result: SqueezeResult,
        current: BBSqueezeData,
        history: Optional[List[BBSqueezeData]] = None,
    ) -> Tuple[bool, str]:
        """
        Validate whether a squeeze release is tradeable.

        All of these must be true:
        1. Phase is RELEASE_BULLISH or RELEASE_BEARISH
        2. Volume spike confirmed (release volume >> compression average)
        3. Multi-timeframe alignment
        4. Squeeze lasted minimum duration (not just noise)
        5. Close is outside BB (actual breakout, not just expansion)

        Args:
            squeeze_result: Result from detect_bb_squeeze().
            current: Current candle data.
            history: Recent history.

        Returns:
            Tuple of (is_valid, reason_string).
        """
        # Phase check
        if not squeeze_result.is_release:
            return False, f"Not a release phase (current: {squeeze_result.phase.value})"

        # Volume check
        if squeeze_result.release_volume_ratio < self.volume_spike_threshold:
            return False, (
                f"Volume not confirmed: ratio={squeeze_result.release_volume_ratio:.1f}x "
                f"(need {self.volume_spike_threshold:.1f}x)"
            )

        # Multi-timeframe check
        if not squeeze_result.multi_tf_aligned:
            return False, "Multi-timeframe alignment not confirmed"

        # Compression duration check
        if squeeze_result.compression_duration < self.min_compression_candles:
            return False, (
                f"Compression too short: {squeeze_result.compression_duration} candles "
                f"(need {self.min_compression_candles}+)"
            )

        # Breakout direction check: close must be outside BB
        if squeeze_result.direction == "bullish" and current.close <= current.bb_upper:
            return False, "Bullish squeeze but close is still inside BB"
        if squeeze_result.direction == "bearish" and current.close >= current.bb_lower:
            return False, "Bearish squeeze but close is still inside BB"

        return True, (
            f"Valid {squeeze_result.direction} squeeze release: "
            f"{squeeze_result.compression_duration} candle compression, "
            f"volume {squeeze_result.release_volume_ratio:.1f}x, "
            f"multi-TF aligned"
        )

    def get_squeeze_strength(self, result: SqueezeResult) -> float:
        """
        Get a normalized strength score for a squeeze result.

        Factors:
        - Compression duration (longer = stronger potential energy)
        - Volume ratio on release (higher = more conviction)
        - Multi-timeframe alignment (aligned = stronger)
        - Phase (release > compression > post-release)

        Args:
            result: SqueezeResult from detect_bb_squeeze().

        Returns:
            Strength score 0.0 to 1.0.
        """
        base = result.strength

        # Phase multiplier
        phase_mult = {
            SqueezePhase.RELEASE_BULLISH: 1.0,
            SqueezePhase.RELEASE_BEARISH: 1.0,
            SqueezePhase.COMPRESSION: 0.5,
            SqueezePhase.POST_RELEASE: 0.3,
            SqueezePhase.NONE: 0.0,
        }
        score = base * phase_mult.get(result.phase, 0.0)

        # Volume bonus
        if result.release_volume_ratio > self.volume_spike_threshold:
            vol_bonus = min(0.3, (result.release_volume_ratio - self.volume_spike_threshold) * 0.2)
            score += vol_bonus

        # Multi-TF bonus
        if result.multi_tf_aligned:
            score += 0.1

        # Validity bonus
        if result.is_valid:
            score = max(score, 0.6)  # minimum strength for valid signals

        return round(min(1.0, max(0.0, score)), 3)


# Module-level convenience functions

_default_detector = BBSqueezeDetector()


def detect_bb_squeeze(
    current: BBSqueezeData,
    history: Optional[List[BBSqueezeData]] = None,
    higher_tf_aligned: Optional[bool] = None,
) -> SqueezeResult:
    """Detect BB Squeeze state (convenience wrapper)."""
    return _default_detector.detect_bb_squeeze(current, history, higher_tf_aligned)


def validate_squeeze_release(
    squeeze_result: SqueezeResult,
    current: BBSqueezeData,
    history: Optional[List[BBSqueezeData]] = None,
) -> Tuple[bool, str]:
    """Validate whether a squeeze release is tradeable."""
    return _default_detector.validate_squeeze_release(squeeze_result, current, history)


def get_squeeze_strength(result: SqueezeResult) -> float:
    """Get normalized squeeze strength score."""
    return _default_detector.get_squeeze_strength(result)


if __name__ == "__main__":
    # Example usage
    print("=" * 60)
    print("BB Squeeze Detector Example")
    print("=" * 60)

    # Simulate a compression sequence followed by release
    history_data = [
        # Wide BBs (no squeeze)
        BBSqueezeData(bb_upper=105, bb_lower=95, bb_middle=100, kc_upper=106, kc_lower=94, close=100, volume=1000),
        BBSqueezeData(bb_upper=104, bb_lower=96, bb_middle=100, kc_upper=105, kc_lower=95, close=101, volume=900),
        # Compression starts (BB inside KC)
        BBSqueezeData(bb_upper=103, bb_lower=97, bb_middle=100, kc_upper=104, kc_lower=96, close=100, volume=800),
        BBSqueezeData(bb_upper=102.5, bb_lower=97.5, bb_middle=100, kc_upper=104, kc_lower=96, close=99.5, volume=700),
        BBSqueezeData(bb_upper=102, bb_lower=98, bb_middle=100, kc_upper=104, kc_lower=96, close=100, volume=600),
        BBSqueezeData(bb_upper=101.5, bb_lower=98.5, bb_middle=100, kc_upper=104, kc_lower=96, close=100.5, volume=550),
        BBSqueezeData(bb_upper=101, bb_lower=99, bb_middle=100, kc_upper=104, kc_lower=96, close=101, volume=500),
    ]

    # Current candle: release with volume spike
    # Close must be ABOVE BB upper for bullish breakout validation
    current = BBSqueezeData(
        bb_upper=106, bb_lower=94, bb_middle=100,  # BB expanded!
        kc_upper=104, kc_lower=96,  # KC unchanged
        close=107,  # broke above upper BB (106)
        volume=1500,  # volume spike!
    )

    # Detect squeeze
    squeeze = detect_bb_squeeze(current, history_data, higher_tf_aligned=True)
    print(f"Phase: {squeeze.phase.value}")
    print(f"Valid: {squeeze.is_valid}")
    print(f"Strength: {squeeze.strength}")
    print(f"Direction: {squeeze.direction}")
    print(f"Compression candles: {squeeze.compression_duration}")
    print(f"Volume ratio: {squeeze.release_volume_ratio:.1f}x")
    print(f"Details: {squeeze.details}")

    # Validate
    is_valid, reason = validate_squeeze_release(squeeze, current, history_data)
    print(f"\nValidation: {'PASS' if is_valid else 'FAIL'} — {reason}")

    # Get strength
    strength = get_squeeze_strength(squeeze)
    print(f"Normalized strength: {strength}")

    # Example: compression only (should NOT be valid for trading)
    print("\n--- Compression Only Example ---")
    current_comp = BBSqueezeData(
        bb_upper=101.5, bb_lower=98.5, bb_middle=100,
        kc_upper=104, kc_lower=96,
        close=100, volume=600,
    )
    squeeze2 = detect_bb_squeeze(current_comp, history_data)
    is_valid2, reason2 = validate_squeeze_release(squeeze2, current_comp, history_data)
    print(f"Phase: {squeeze2.phase.value}")
    print(f"Valid: {is_valid2} — {reason2}")
