"""
improved_macd.py — Proper MACD Signal Classification

Distinguishes between true MACD crossover events and mere histogram states.
Requires confirmation candles to avoid false signals from noise.

Signal Types:
    BULLISH_CROSS     — MACD line just crossed above signal line (hist turned positive)
    BULLISH_RECOVERY  — Histogram positive but MACD line still below signal
    BULLISH           — MACD above signal, histogram positive and growing
    BEARISH_CROSS     — MACD line just crossed below signal line (hist turned negative)
    BEARISH_RECOVERY  — Histogram negative but MACD line still above signal
    BEARISH           — MACD below signal, histogram negative and growing
    NEUTRAL           — No clear directional signal

Usage:
    classifier = MACDClassifier()
    result = classify_macd(macd_data)
    strength = get_macd_signal_strength(result)
    valid = validate_macd_signal(result, required_confirmations=2)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class MACDSignal(Enum):
    """MACD signal classification types."""
    BULLISH_CROSS = "BULLISH_CROSS"
    BULLISH_RECOVERY = "BULLISH_RECOVERY"
    BULLISH = "BULLISH"
    BEARISH_CROSS = "BEARISH_CROSS"
    BEARISH_RECOVERY = "BEARISH_RECOVERY"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class MACDData:
    """
    Represents a single MACD data point.

    All values should be pre-calculated (the classifier doesn't compute MACD).
    """
    macd_line: float       # MACD line value
    signal_line: float     # Signal line (EMA of MACD)
    histogram: float       # MACD - Signal (= histogram)
    timestamp: float = 0.0
    volume: float = 0.0


@dataclass
class MACDResult:
    """
    Complete result of MACD classification.

    Attributes:
        signal: Classified MACD signal type.
        strength: Signal strength 0.0 (weak) to 1.0 (very strong).
        confirmed: Whether signal has enough confirmation candles.
        confirmations: Number of consecutive confirmation candles.
        histogram_trend: Direction of histogram change ("growing", "shrinking", "flat").
        macd_above_signal: Whether MACD line is above signal line.
        cross_just_happened: Whether a crossover just occurred.
        details: Human-readable description of the signal.
    """
    signal: MACDSignal
    strength: float
    confirmed: bool
    confirmations: int
    histogram_trend: str
    macd_above_signal: bool
    cross_just_happened: bool
    details: str

    @property
    def is_bullish(self) -> bool:
        return self.signal in (MACDSignal.BULLISH_CROSS, MACDSignal.BULLISH_RECOVERY, MACDSignal.BULLISH)

    @property
    def is_bearish(self) -> bool:
        return self.signal in (MACDSignal.BEARISH_CROSS, MACDSignal.BEARISH_RECOVERY, MACDSignal.BEARISH)

    @property
    def is_cross(self) -> bool:
        return self.signal in (MACDSignal.BULLISH_CROSS, MACDSignal.BEARISH_CROSS)


class MACDClassifier:
    """
    Proper MACD signal classification with confirmation requirements.

    Key improvement: Distinguishes actual crossover events from mere
    histogram states. Previous system labeled any positive histogram
    as BULLISH_CROSS, leading to false signals.
    """

    # How many candles the histogram must maintain direction for confirmation
    DEFAULT_REQUIRED_CONFIRMATIONS = 2

    # Minimum histogram change to count as "growing"
    HISTOGRAM_GROWTH_THRESHOLD = 0.001

    # Minimum absolute histogram value for a valid signal
    MIN_HISTOGRAM_MAGNITUDE = 0.0001

    def __init__(self, required_confirmations: int = DEFAULT_REQUIRED_CONFIRMATIONS):
        """
        Initialize the MACD classifier.

        Args:
            required_confirmations: Number of candles confirming direction needed.
        """
        self.required_confirmations = required_confirmations
        self._prev_histogram: Optional[float] = None
        self._prev_macd_above: Optional[bool] = None
        self._histogram_history: List[float] = []
        self._macd_above_history: List[bool] = []

    def _detect_histogram_trend(self, history: List[float]) -> str:
        """Determine if histogram is growing, shrinking, or flat."""
        if len(history) < 3:
            return "flat"

        recent = history[-3:]
        diffs = [recent[i+1] - recent[i] for i in range(len(recent)-1)]

        if all(d > self.HISTOGRAM_GROWTH_THRESHOLD for d in diffs):
            return "growing"
        elif all(d < -self.HISTOGRAM_GROWTH_THRESHOLD for d in diffs):
            return "shrinking"
        else:
            return "flat"

    def _check_cross(self, history: List[float], macd_above_history: List[bool]) -> Tuple[bool, bool]:
        """
        Check if a crossover just happened.

        Returns:
            Tuple of (cross_detected, was_bullish_cross). If cross_detected is False,
            was_bullish_cross is meaningless.
        """
        if len(macd_above_history) < 2:
            return False, False

        current = macd_above_history[-1]
        previous = macd_above_history[-2]

        if current != previous:
            return True, current  # current indicates if bullish (True) or bearish (False)

        return False, False

    def classify_macd(
        self,
        macd_data: MACDData,
        history: Optional[List[MACDData]] = None,
    ) -> MACDResult:
        """
        Classify the current MACD state into a signal type.

        This is the main classification function. It examines the current
        MACD values and recent history to determine the correct signal type.

        Args:
            macd_data: Current MACD values.
            history: Recent MACD data points (newest last). At least 5 recommended.

        Returns:
            MACDResult with signal classification and metadata.
        """
        if history is None:
            history = []

        # Add current to history for analysis
        all_data = history + [macd_data]
        if len(all_data) < 2:
            return MACDResult(
                signal=MACDSignal.NEUTRAL,
                strength=0.0,
                confirmed=False,
                confirmations=0,
                histogram_trend="flat",
                macd_above_signal=macd_data.macd_line > macd_data.signal_line,
                cross_just_happened=False,
                details="Insufficient data for MACD classification",
            )

        # Build histogram and macd_above histories — compute internally for consistency
        # Validate that provided histogram matches macd_line - signal_line
        histogram_vals = []
        for d in all_data:
            computed = d.macd_line - d.signal_line
            if abs(d.histogram - computed) > 1e-6:
                logger.warning(
                    f"Histogram inconsistency: provided={d.histogram}, "
                    f"computed={computed:.6f}. Using computed value."
                )
            histogram_vals.append(computed)
        macd_above_vals = [d.macd_line > d.signal_line for d in all_data]

        # Current state (use computed histogram for consistency)
        current_hist = histogram_vals[-1]
        current_macd_above = macd_data.macd_line > macd_data.signal_line
        hist_magnitude = abs(current_hist)

        # Reject trivial crosses where histogram magnitude is negligible
        cross_detected, cross_was_bullish = self._check_cross(histogram_vals, macd_above_vals)
        if cross_detected and hist_magnitude < self.MIN_HISTOGRAM_MAGNITUDE:
            cross_detected = False  # reject trivial crosses

        # Count consecutive histogram sign matches
        confirmations = 0
        target_sign = 1 if current_hist > 0 else -1
        for h in reversed(histogram_vals):
            if h * target_sign > 0:
                confirmations += 1
            else:
                break

        # Determine histogram trend
        histogram_trend = self._detect_histogram_trend(histogram_vals)

        # Classify signal
        signal = MACDSignal.NEUTRAL
        strength = 0.0
        details = ""
        cross_just_happened = False

        if cross_detected:
            cross_just_happened = True
            if cross_was_bullish:
                signal = MACDSignal.BULLISH_CROSS
                details = "Bullish crossover: MACD just crossed above signal line"
                strength = 0.7 + min(0.3, hist_magnitude * 100)
            else:
                signal = MACDSignal.BEARISH_CROSS
                details = "Bearish crossover: MACD just crossed below signal line"
                strength = 0.7 + min(0.3, hist_magnitude * 100)

        elif current_macd_above and current_hist > 0:
            if histogram_trend == "growing":
                signal = MACDSignal.BULLISH
                details = "Bullish: MACD above signal, histogram positive and growing"
                strength = 0.6 + min(0.4, hist_magnitude * 50)
            elif histogram_trend == "shrinking":
                # MACD above but histogram shrinking — weakening bullish
                signal = MACDSignal.BULLISH_RECOVERY
                details = "Bullish recovery weakening: histogram shrinking while above signal"
                strength = 0.3 + min(0.2, hist_magnitude * 30)
            else:
                signal = MACDSignal.BULLISH
                details = "Bullish: MACD above signal, histogram positive"
                strength = 0.5 + min(0.2, hist_magnitude * 30)

        elif not current_macd_above and current_hist < 0:
            if histogram_trend == "shrinking":
                # Note: for bearish, "shrinking" means histogram becoming more negative
                signal = MACDSignal.BEARISH
                details = "Bearish: MACD below signal, histogram negative and growing"
                strength = 0.6 + min(0.4, hist_magnitude * 50)
            elif histogram_trend == "growing":
                signal = MACDSignal.BEARISH_RECOVERY
                details = "Bearish recovery weakening: histogram shrinking while below signal"
                strength = 0.3 + min(0.2, hist_magnitude * 30)
            else:
                signal = MACDSignal.BEARISH
                details = "Bearish: MACD below signal, histogram negative"
                strength = 0.5 + min(0.2, hist_magnitude * 30)

        elif current_macd_above and current_hist < 0:
            # MACD above signal but histogram negative — bearish recovery
            signal = MACDSignal.BEARISH_RECOVERY
            details = "Bearish recovery: MACD above signal but histogram negative"
            strength = 0.2 + min(0.2, hist_magnitude * 20)

        elif not current_macd_above and current_hist > 0:
            # MACD below signal but histogram positive — bullish recovery
            signal = MACDSignal.BULLISH_RECOVERY
            details = "Bullish recovery: MACD below signal but histogram positive"
            strength = 0.2 + min(0.2, hist_magnitude * 20)

        else:
            details = "Neutral: no clear directional signal"
            strength = 0.0

        # Clamp strength
        strength = max(0.0, min(1.0, strength))

        # Check confirmation
        confirmed = confirmations >= self.required_confirmations

        result = MACDResult(
            signal=signal,
            strength=strength,
            confirmed=confirmed,
            confirmations=confirmations,
            histogram_trend=histogram_trend,
            macd_above_signal=current_macd_above,
            cross_just_happened=cross_just_happened,
            details=details,
        )

        logger.debug(
            f"MACD classified: {signal.value}, strength={strength:.2f}, "
            f"confirmed={confirmed} ({confirmations}/{self.required_confirmations}), "
            f"trend={histogram_trend}"
        )

        return result

    def get_macd_signal_strength(self, result: MACDResult) -> float:
        """
        Get a normalized signal strength from a classification result.

        Cross signals get a base boost since they represent actual events.

        Args:
            result: MACDResult from classify_macd().

        Returns:
            Signal strength 0.0 to 1.0.
        """
        base_strength = result.strength

        # Boost for actual crossover events
        if result.cross_just_happened:
            base_strength = min(1.0, base_strength + 0.1)

        # Boost for confirmed signals
        if result.confirmed:
            base_strength = min(1.0, base_strength + 0.05)

        # Penalty for unconfirmed signals
        if not result.confirmed and not result.cross_just_happened:
            base_strength *= 0.7

        return round(max(0.0, min(1.0, base_strength)), 3)

    def validate_macd_signal(
        self,
        result: MACDResult,
        required_confirmations: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Validate whether a MACD signal is actionable.

        Checks:
        1. Signal is not NEUTRAL
        2. Signal has enough confirmation candles
        3. Histogram magnitude is sufficient (not noise)
        4. For cross signals, validation is more lenient (they're events)

        Args:
            result: MACDResult from classify_macd().
            required_confirmations: Override default confirmation requirement.

        Returns:
            Tuple of (is_valid, reason_string).
        """
        req = required_confirmations or self.required_confirmations

        if result.signal == MACDSignal.NEUTRAL:
            return False, "Signal is NEUTRAL — no action"

        # Cross signals are validated immediately (they're events, not states)
        if result.cross_just_happened:
            return True, f"Valid crossover detected ({result.signal.value})"

        # For non-cross signals, require confirmation
        if result.confirmations < req:
            return False, (
                f"Insufficient confirmation: {result.confirmations}/{req} candles "
                f"confirming {result.signal.value}"
            )

        # Check minimum strength
        if result.strength < 0.2:
            return False, f"Signal too weak: strength={result.strength:.2f} (min 0.2)"

        return True, f"Valid signal: {result.signal.value} (strength={result.strength:.2f})"


# Module-level convenience functions

_default_classifier = MACDClassifier()


def classify_macd(
    macd_data: MACDData,
    history: Optional[List[MACDData]] = None,
    required_confirmations: int = 2,
) -> MACDResult:
    """
    Classify a MACD signal (convenience wrapper).

    Args:
        macd_data: Current MACD values.
        history: Recent MACD data points.
        required_confirmations: Minimum candles for confirmation.

    Returns:
        MACDResult with classification.
    """
    classifier = MACDClassifier(required_confirmations=required_confirmations)
    return classifier.classify_macd(macd_data, history)


def get_macd_signal_strength(result: MACDResult) -> float:
    """Get normalized signal strength from a classification result."""
    return _default_classifier.get_macd_signal_strength(result)


def validate_macd_signal(
    result: MACDResult,
    required_confirmations: int = 2,
) -> Tuple[bool, str]:
    """Validate whether a MACD signal is actionable."""
    classifier = MACDClassifier(required_confirmations=required_confirmations)
    return classifier.validate_macd_signal(result, required_confirmations)


if __name__ == "__main__":
    # Example usage
    print("=" * 60)
    print("MACD Classifier Example")
    print("=" * 60)

    # Simulate a history of MACD data leading to a crossover
    history_data = [
        MACDData(macd_line=0.005, signal_line=0.008, histogram=-0.003),
        MACDData(macd_line=0.004, signal_line=0.007, histogram=-0.003),
        MACDData(macd_line=0.006, signal_line=0.007, histogram=-0.001),
        MACDData(macd_line=0.008, signal_line=0.007, histogram=0.001),  # just crossed!
    ]

    # Current candle (after cross, histogram growing)
    current = MACDData(macd_line=0.010, signal_line=0.007, histogram=0.003)

    history = history_data[:-1]
    result = classify_macd(current, history, required_confirmations=2)

    print(f"Signal: {result.signal.value}")
    print(f"Strength: {result.strength:.2f}")
    print(f"Confirmed: {result.confirmed} ({result.confirmations} candles)")
    print(f"Histogram trend: {result.histogram_trend}")
    print(f"Cross just happened: {result.cross_just_happened}")
    print(f"Details: {result.details}")

    # Validate
    is_valid, reason = validate_macd_signal(result)
    print(f"\nValidation: {'PASS' if is_valid else 'FAIL'} — {reason}")

    # Example: BULLISH_RECOVERY (histogram positive but line below signal)
    print("\n--- BULLISH_RECOVERY Example ---")
    recovery_current = MACDData(macd_line=0.005, signal_line=0.008, histogram=0.003)
    recovery_hist = [
        MACDData(macd_line=0.003, signal_line=0.009, histogram=-0.006),
        MACDData(macd_line=0.004, signal_line=0.009, histogram=-0.005),
        MACDData(macd_line=0.005, signal_line=0.008, histogram=0.003),  # hist turned positive
        MACDData(macd_line=0.005, signal_line=0.007, histogram=0.002),  # but still below signal
    ]
    recovery_result = classify_macd(recovery_current, recovery_hist)
    print(f"Signal: {recovery_result.signal.value}")
    print(f"Strength: {recovery_result.strength:.2f}")
    print(f"Details: {recovery_result.details}")
