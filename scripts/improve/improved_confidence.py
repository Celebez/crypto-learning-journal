"""
improved_confidence.py — Dynamic Confidence Calculation System

Calculates a bounded confidence score (20-100) for trading signals based on
historical indicator performance, calibration state, and market conditions.
Includes a calibration recovery mechanism to escape the death spiral.

Usage:
    calculator = ConfidenceCalculator()
    score = calculator.calculate_confidence(indicators, calibration_multiplier)
    calculator.update_calibration(prediction_correct=True)
    threshold = calculator.get_dynamic_threshold()
"""

from __future__ import annotations

import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class IndicatorPerformance:
    """Tracks performance of a single indicator over a rolling window."""
    name: str
    wins: int = 0
    losses: int = 0
    total: int = 0
    recent_results: List[bool] = field(default_factory=list)
    last_updated: float = 0.0
    window_size: int = 20  # rolling window for recent performance

    @property
    def win_rate(self) -> float:
        """Overall win rate (0.0 - 1.0)."""
        if self.total == 0:
            return 0.5  # neutral prior
        return self.wins / self.total

    @property
    def recent_win_rate(self) -> float:
        """Win rate over the rolling window (more responsive to changes)."""
        if not self.recent_results:
            return self.win_rate  # fall back to overall
        return sum(self.recent_results) / len(self.recent_results)

    @property
    def performance_score(self) -> float:
        """
        Weighted score combining recent and overall performance.
        Recent performance weighted 70%, overall 30%.
        Range: 0.0 (terrible) to 1.0 (perfect).
        """
        recent = self.recent_win_rate
        overall = self.win_rate
        return 0.7 * recent + 0.3 * overall


class ConfidenceCalculator:
    """
    Dynamic confidence calculation system.

    Instead of static weights, this system adjusts confidence based on
    how well each indicator has actually performed recently.
    """

    # Bounds for final confidence score
    MIN_CONFIDENCE = 20
    MAX_CONFIDENCE = 100
    BASE_SCORE = 50  # starting point (neutral)

    # Default weights when no history exists
    DEFAULT_INDICATOR_WEIGHTS: Dict[str, float] = {
        "rsi": 1.0,
        "macd": 1.2,   # MACD is primary, slightly higher default weight
        "bb_squeeze": 1.5,  # BB Squeeze historically unreliable, starts low
        "volume": 0.8,
        "ema_trend": 1.0,
        "support_resistance": 1.0,
    }

    # Threshold calibration defaults
    DEFAULT_THRESHOLD = 55.0
    MIN_THRESHOLD = 35.0  # absolute floor for threshold
    DEATH_SPIRAL_MULTIPLIER = 0.6

    def __init__(
        self,
        indicators: Optional[Dict[str, IndicatorPerformance]] = None,
        calibration_multiplier: float = 1.0,
        calibration_history: Optional[List[Tuple[float, bool]]] = None,
    ):
        """
        Initialize the confidence calculator.

        Args:
            indicators: Dict mapping indicator names to their performance objects.
            calibration_multiplier: Current calibration multiplier (0.0 - 2.0).
            calibration_history: List of (timestamp, was_correct) tuples.
        """
        self.indicators = indicators or {}
        self.calibration_multiplier = calibration_multiplier
        self.calibration_history = calibration_history or []
        self._last_threshold = self.DEFAULT_THRESHOLD

    def calculate_confidence(
        self,
        active_signals: Dict[str, float],
        market_regime: str = "normal",
        calibration_multiplier: Optional[float] = None,
        direction: str = "long",
    ) -> float:
        """
        Calculate a dynamic confidence score for a trading signal.

        Args:
            active_signals: Dict mapping indicator names to their signal strength
                           (-1.0 to +1.0 range, positive = bullish).
            market_regime: Current market regime ("trending", "ranging", "volatile", "normal").
            calibration_multiplier: Override calibration multiplier (uses stored value if None).
            direction: Trade direction ("long" or "short"). Signals are projected onto this
                       direction so bearish signals boost confidence for short trades.

        Returns:
            Confidence score between MIN_CONFIDENCE and MAX_CONFIDENCE.
        """
        if not active_signals:
            logger.warning("No active signals provided, returning base score")
            return float(self.BASE_SCORE)

        mult = calibration_multiplier if calibration_multiplier is not None else self.calibration_multiplier

        # Start from base score
        score = float(self.BASE_SCORE)

        # Calculate dynamic weight for each indicator
        total_weight = 0.0
        weighted_contribution = 0.0

        for name, signal_strength in active_signals.items():
            indicator = self.indicators.get(name)
            if indicator is None:
                # No history for this indicator, use default weight
                default_w = self.DEFAULT_INDICATOR_WEIGHTS.get(name, 1.0)
                perf = 0.5  # neutral
                weight = default_w
            else:
                perf = indicator.performance_score
                # Dynamic weight: higher when indicator is performing well
                base_w = self.DEFAULT_INDICATOR_WEIGHTS.get(name, 1.0)
                weight = base_w * (0.5 + perf)  # scale between 0.5x and 1.5x base

            # Regime adjustment removed from weights to avoid cancellation during normalization
            # Applied to final score below instead

            # Project signal onto trade direction: aligned = positive, opposing = negative
            direction_sign = 1.0 if direction == "long" else -1.0
            projected = signal_strength * direction_sign
            contribution = weight * projected
            weighted_contribution += contribution
            total_weight += weight

        if total_weight > 0:
            # Normalize and scale contribution to ±25 points
            normalized = weighted_contribution / total_weight
            score += normalized * 25.0

        # Apply market regime adjustment to final score (not weights)
        if market_regime == "volatile":
            score *= 0.9  # reduce confidence in volatile markets
        elif market_regime == "trending":
            score *= 1.1  # boost confidence in trending markets

        # Apply calibration multiplier (but not as harsh penalty)
        if mult < 1.0:
            # Dampen the score rather than multiply directly
            dampening = 0.7 + 0.3 * mult  # ranges from 0.7 (at mult=0) to 1.0 (at mult=1)
            score *= dampening
        elif mult > 1.0:
            score *= (0.9 + 0.1 * mult)  # modest boost for over-performing

        # Apply calibration recovery mechanism
        if mult < self.DEATH_SPIRAL_MULTIPLIER:
            recovery_threshold = mult * 80.0
            logger.info(
                f"Calibration recovery: mult={mult:.2f}, "
                f"threshold lowered to {recovery_threshold:.1f} (was {self._last_threshold:.1f})"
            )
            self._last_threshold = max(self.MIN_THRESHOLD, recovery_threshold)

        # Bound the output
        score = max(self.MIN_CONFIDENCE, min(self.MAX_CONFIDENCE, score))

        return round(score, 1)

    def update_calibration(
        self,
        prediction_correct: bool,
        timestamp: Optional[float] = None,
        window_size: int = 20,
    ) -> float:
        """
        Update calibration multiplier based on prediction outcome.

        Uses a rolling window approach for more stable calibration.

        Args:
            prediction_correct: Whether the prediction was correct.
            timestamp: When the prediction resolved (default: now).
            window_size: Number of recent predictions to consider.

        Returns:
            Updated calibration multiplier (0.0 - 2.0).
        """
        ts = timestamp if timestamp is not None else time.time()
        self.calibration_history.append((ts, prediction_correct))

        # Trim to window
        if len(self.calibration_history) > window_size:
            self.calibration_history = self.calibration_history[-window_size:]

        # Calculate multiplier from recent performance
        correct = sum(1 for _, c in self.calibration_history[-window_size:] if c)
        total = min(len(self.calibration_history), window_size)

        if total == 0:
            self.calibration_multiplier = 1.0
        else:
            win_rate = correct / total
            # Map win_rate to multiplier: 0.0 wins -> 0.5x, 0.5 -> 1.0x, 1.0 -> 1.5x
            self.calibration_multiplier = 0.5 + win_rate

        self.calibration_multiplier = max(0.1, min(2.0, self.calibration_multiplier))

        logger.debug(
            f"Calibration updated: {correct}/{total} correct, "
            f"multiplier={self.calibration_multiplier:.2f}"
        )
        return self.calibration_multiplier

    def get_dynamic_threshold(self) -> float:
        """
        Get the current dynamic confidence threshold.

        When calibration is poor (multiplier < 0.6), the threshold is lowered
        to allow more trades through (but they're tracked as shadow predictions).

        Returns:
            Current confidence threshold (MIN_THRESHOLD to DEFAULT_THRESHOLD).
        """
        return self._last_threshold

    def reset_threshold(self) -> None:
        """Reset threshold to default value."""
        self._last_threshold = self.DEFAULT_THRESHOLD

    def get_status(self) -> Dict:
        """Get current calculator status for monitoring."""
        return {
            "calibration_multiplier": round(self.calibration_multiplier, 3),
            "current_threshold": round(self._last_threshold, 1),
            "calibration_history_size": len(self.calibration_history),
            "indicators_tracked": list(self.indicators.keys()),
            "in_recovery_mode": self.calibration_multiplier < self.DEATH_SPIRAL_MULTIPLIER,
        }


if __name__ == "__main__":
    # Example usage
    print("=" * 60)
    print("Confidence Calculator Example")
    print("=" * 60)

    calc = ConfidenceCalculator()

    # Simulate some indicator performance history
    for name in ["rsi", "macd", "bb_squeeze", "volume"]:
        perf = IndicatorPerformance(name=name, window_size=20)
        # Simulate past results
        for correct in [True, True, False, True, False, True, True, True, False, True]:
            perf.recent_results.append(correct)
            perf.total += 1
            if correct:
                perf.wins += 1
            else:
                perf.losses += 1
        calc.indicators[name] = perf

    # Example signal
    signals = {
        "rsi": 0.7,       # strong bullish RSI
        "macd": 0.5,      # moderate bullish MACD
        "bb_squeeze": 0.8, # strong BB Squeeze signal
        "volume": 0.3,    # weak volume confirmation
    }

    confidence = calc.calculate_confidence(signals, market_regime="trending")
    print(f"Confidence score: {confidence}")
    print(f"Dynamic threshold: {calc.get_dynamic_threshold()}")
    print(f"Calculator status: {calc.get_status()}")

    # Simulate calibration updates
    for correct in [True, False, False, True, False]:
        mult = calc.update_calibration(correct)
        print(f"  After {'correct' if correct else 'incorrect'}: multiplier={mult:.2f}")

    print(f"Final threshold: {calc.get_dynamic_threshold()}")
