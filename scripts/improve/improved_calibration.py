"""
improved_calibration.py — Calibration Recovery Mechanism

Fixes the death spiral: when calibration multiplier drops below 0.6,
the old system blocked ALL predictions permanently. This module introduces:

1. Shadow predictions: tracked but not traded during low calibration
2. Bayesian updating: more stable calibration than simple rolling window
3. Recovery mechanism: gradual path back from low calibration

Usage:
    calibrator = CalibrationManager()
    shadow = calibrator.get_shadow_mode()
    calibrator.update_calibration_bayesian(prediction_correct=True, confidence=75)
    calibrator.recover_calibration()
"""

from __future__ import annotations

import math
import time
import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class CalibrationState(Enum):
    """Current calibration state."""
    HEALTHY = "HEALTHY"           # multiplier > 0.8, normal operation
    DEGRADED = "DEGRADED"         # multiplier 0.6 - 0.8, caution
    SHADOW = "SHADOW"             # multiplier 0.3 - 0.6, shadow mode
    CRITICAL = "CRITICAL"         # multiplier < 0.3, severe underperformance
    RECOVERING = "RECOVERING"     # actively recovering from low calibration


@dataclass
class PredictionRecord:
    """Record of a single prediction for calibration tracking."""
    timestamp: float
    prediction_correct: bool
    confidence: float           # confidence score at time of prediction
    was_shadow: bool            # True if this was tracked but not traded
    symbol: str = ""
    signal_type: str = ""


@dataclass
class CalibrationStatus:
    """Complete calibration status for monitoring."""
    multiplier: float
    state: CalibrationState
    in_shadow_mode: bool
    total_predictions: int
    recent_accuracy: float
    bayesian_prior_strength: float
    predictions_until_recovery: Optional[int]
    next_trade_allowed: bool
    details: str


class CalibrationManager:
    """
    Bayesian calibration system with shadow mode recovery.

    Key improvements over old system:
    - Bayesian updating: uses prior belief + evidence for smoother transitions
    - Shadow mode: tracks predictions without trading them during low calibration
    - Gradual recovery: path back from death spiral instead of permanent block
    - Separate accuracy tracking for shadow vs active predictions
    """

    # Calibration thresholds
    MULTIPLIER_HEALTHY = 0.8
    MULTIPLIER_DEGRADED = 0.6
    MULTIPLIER_SHADOW = 0.3
    MULTIPLIER_RECOVERY_TARGET = 0.7  # recover to this level

    # Bayesian prior: start with assumption of 50% accuracy (neutral)
    PRIOR_ALPHA = 1.0  # prior correct predictions (Dirichlet parameter)
    PRIOR_BETA = 1.0   # prior incorrect predictions (Dirichlet parameter)

    # Shadow mode settings
    SHADOW_MIN_PREDICTIONS = 10    # minimum shadow predictions before recovery check
    SHADOW_RECOVERY_THRESHOLD = 0.6  # shadow accuracy needed to exit shadow mode

    # Recovery settings
    RECOVERY_RATE = 0.05  # how fast multiplier recovers per correct prediction
    RECOVERY_PENALTY = 0.03  # how fast multiplier drops per incorrect prediction
    MIN_RECOVERY_MULTIPLIER = 0.2  # floor for recovery

    def __init__(
        self,
        initial_multiplier: float = 1.0,
        prior_alpha: float = PRIOR_ALPHA,
        prior_beta: float = PRIOR_BETA,
    ):
        """
        Initialize calibration manager.

        Args:
            initial_multiplier: Starting calibration multiplier.
            prior_alpha: Bayesian prior strength for correct predictions.
            prior_beta: Bayesian prior strength for incorrect predictions.
        """
        self._multiplier = max(0.1, min(1.5, initial_multiplier))
        self._state = self._determine_state()
        self._prior_alpha = prior_alpha
        self._prior_beta = prior_beta

        # Prediction tracking
        self._active_predictions: List[PredictionRecord] = []
        self._shadow_predictions: List[PredictionRecord] = []
        self._total_history: List[PredictionRecord] = []

        # Recovery tracking
        self._recovery_predictions: int = 0
        self._recovery_correct: int = 0

        # Bayesian state
        self._bayesian_alpha = float(prior_alpha)
        self._bayesian_beta = float(prior_beta)

    @property
    def multiplier(self) -> float:
        return self._multiplier

    @property
    def state(self) -> CalibrationState:
        return self._state

    def _determine_state(self) -> CalibrationState:
        """Determine calibration state from current multiplier."""
        if self._multiplier >= self.MULTIPLIER_HEALTHY:
            return CalibrationState.HEALTHY
        elif self._multiplier >= self.MULTIPLIER_DEGRADED:
            return CalibrationState.DEGRADED
        elif self._multiplier >= self.MULTIPLIER_SHADOW:
            return CalibrationState.SHADOW
        else:
            return CalibrationState.CRITICAL

    def update_calibration_bayesian(
        self,
        prediction_correct: bool,
        confidence: float = 50.0,
        symbol: str = "",
        signal_type: str = "",
    ) -> float:
        """
        Update calibration using Bayesian updating.

        Bayesian approach is smoother than rolling windows because:
        - Prior belief prevents extreme swings from small samples
        - Each new data point updates the belief proportionally
        - Confidence of the prediction affects update strength

        Args:
            prediction_correct: Whether the prediction was correct.
            confidence: Confidence score at time of prediction (20-100).
            symbol: Trading pair symbol (for logging).
            signal_type: Signal type (for logging).

        Returns:
            Updated calibration multiplier.
        """
        # Determine if this should be shadow or active
        in_shadow = self.get_shadow_mode()
        ts = time.time()

        record = PredictionRecord(
            timestamp=ts,
            prediction_correct=prediction_correct,
            confidence=confidence,
            was_shadow=in_shadow,
            symbol=symbol,
            signal_type=signal_type,
        )

        # Track prediction
        self._total_history.append(record)
        if in_shadow:
            self._shadow_predictions.append(record)
            logger.info(
                f"Shadow prediction recorded: {'correct' if prediction_correct else 'incorrect'} "
                f"(confidence={confidence:.1f}, symbol={symbol})"
            )
        else:
            self._active_predictions.append(record)

        # Bayesian update: adjust alpha/beta
        # Weight the update by how confident the prediction was
        # High confidence correct = strong positive signal
        # Low confidence correct = weaker positive signal
        weight = confidence / 100.0  # 0.2 to 1.0

        if prediction_correct:
            self._bayesian_alpha += weight
        else:
            self._bayesian_beta += weight

        # Bayesian mean: expected accuracy
        total = self._bayesian_alpha + self._bayesian_beta
        bayesian_accuracy = self._bayesian_alpha / total if total > 0 else 0.5

        # Map Bayesian accuracy to multiplier: 0% accuracy -> 0.5x, 50% -> 1.0x, 100% -> 1.5x
        new_multiplier = 0.5 + bayesian_accuracy

        # Smooth transition: don't jump too fast
        alpha = 0.3  # smoothing factor (0 = no change, 1 = instant)
        self._multiplier = self._multiplier * (1 - alpha) + new_multiplier * alpha

        # Bound
        self._multiplier = max(0.1, min(1.5, self._multiplier))

        # Track if we were in recovery before state update
        was_recovering = self._state == CalibrationState.RECOVERING

        # Update state
        self._state = self._determine_state()

        # If was in recovery, preserve recovery state until criteria met
        if was_recovering:
            self._state = CalibrationState.RECOVERING
            self._recovery_predictions += 1
            if prediction_correct:
                self._recovery_correct += 1
            # Check if we've recovered
            shadow_acc = self._get_shadow_accuracy()
            if (
                self._recovery_predictions >= self.SHADOW_MIN_PREDICTIONS
                and shadow_acc >= self.SHADOW_RECOVERY_THRESHOLD
            ):
                self._state = CalibrationState.DEGRADED
                logger.info(
                    f"Calibration recovered: shadow accuracy={shadow_acc:.2f}, "
                    f"multiplier={self._multiplier:.2f}"
                )

        logger.debug(
            f"Calibration updated: correct={prediction_correct}, "
            f"alpha={self._bayesian_alpha:.2f}, beta={self._bayesian_beta:.2f}, "
            f"multiplier={self._multiplier:.3f}, state={self._state.value}"
        )

        return self._multiplier

    def get_shadow_mode(self) -> bool:
        """
        Check if predictions should be tracked but not traded.

        Shadow mode activates when:
        - Multiplier drops below DEGRADED threshold (0.6)
        - We're not already in recovery or critical state

        Returns:
            True if in shadow mode (predictions tracked but not traded).
        """
        return self._multiplier < self.MULTIPLIER_DEGRADED

    def recover_calibration(self) -> bool:
        """
        Attempt to initiate calibration recovery.

        Recovery process:
        1. Enter RECOVERING state
        2. Track shadow predictions (not traded)
        3. If shadow accuracy >= threshold for N predictions, exit recovery
        4. Gradually increase multiplier as evidence accumulates

        Returns:
            True if recovery was initiated or is already in progress.
        """
        if self._state in (CalibrationState.HEALTHY, CalibrationState.DEGRADED):
            logger.info("Calibration is healthy/degraded — no recovery needed")
            return False

        if self._state == CalibrationState.RECOVERING:
            logger.info("Already in recovery mode")
            return True

        # Enter recovery mode
        self._state = CalibrationState.RECOVERING
        self._recovery_predictions = 0
        self._recovery_correct = 0

        # Reset Bayesian priors to be less extreme
        # Give benefit of doubt: assume slightly better prior
        self._prior_alpha = 2.0
        self._prior_beta = 1.5
        self._bayesian_alpha = self._prior_alpha
        self._bayesian_beta = self._prior_beta

        logger.info(
            f"Calibration recovery initiated: multiplier={self._multiplier:.3f}, "
            f"need {self.SHADOW_MIN_PREDICTIONS} shadow predictions with "
            f"{self.SHADOW_RECOVERY_THRESHOLD:.0%} accuracy to recover"
        )
        return True

    def force_recovery_boost(self, boost: float = 0.1) -> float:
        """
        Apply an emergency boost to multiplier (use with caution).

        This simulates external correction (e.g., manually adjusting after
        discovering indicator miscalculation).

        Args:
            boost: Amount to increase multiplier by.

        Returns:
            New multiplier value.
        """
        old = self._multiplier
        self._multiplier = min(1.5, self._multiplier + boost)
        self._state = self._determine_state()
        logger.warning(f"Emergency calibration boost: {old:.3f} -> {self._multiplier:.3f}")
        return self._multiplier

    def _get_shadow_accuracy(self) -> float:
        """Get accuracy of shadow predictions."""
        if not self._shadow_predictions:
            return 0.0
        correct = sum(1 for p in self._shadow_predictions if p.prediction_correct)
        return correct / len(self._shadow_predictions)

    def _get_active_accuracy(self) -> float:
        """Get accuracy of active (non-shadow) predictions."""
        if not self._active_predictions:
            return 0.5
        correct = sum(1 for p in self._active_predictions if p.prediction_correct)
        return correct / len(self._active_predictions)

    def _get_recent_accuracy(self, window: int = 20) -> float:
        """Get accuracy over recent predictions."""
        recent = self._total_history[-window:]
        if not recent:
            return 0.5
        correct = sum(1 for p in recent if p.prediction_correct)
        return correct / len(recent)

    def get_predictions_until_recovery(self) -> Optional[int]:
        """
        Get estimated predictions remaining until potential recovery.

        Returns None if not in recovery, or number of predictions needed.
        """
        if self._state != CalibrationState.RECOVERING:
            return None

        remaining = max(0, self.SHADOW_MIN_PREDICTIONS - self._recovery_predictions)
        return remaining

    def get_status(self) -> CalibrationStatus:
        """Get complete calibration status for monitoring."""
        predictions_until = self.get_predictions_until_recovery()
        shadow_acc = self._get_shadow_accuracy()

        details_parts = []
        details_parts.append(f"Multiplier: {self._multiplier:.3f}")
        details_parts.append(f"State: {self._state.value}")
        details_parts.append(f"Shadow mode: {self.get_shadow_mode()}")
        details_parts.append(f"Active accuracy: {self._get_active_accuracy():.1%}")
        details_parts.append(f"Shadow accuracy: {shadow_acc:.1%}")
        details_parts.append(f"Recent accuracy: {self._get_recent_accuracy():.1%}")
        if predictions_until is not None:
            details_parts.append(f"Predictions until recovery check: {predictions_until}")
        details_parts.append(f"Bayesian alpha: {self._bayesian_alpha:.2f}")
        details_parts.append(f"Beta: {self._bayesian_beta:.2f}")

        return CalibrationStatus(
            multiplier=round(self._multiplier, 3),
            state=self._state,
            in_shadow_mode=self.get_shadow_mode(),
            total_predictions=len(self._total_history),
            recent_accuracy=round(self._get_recent_accuracy(), 3),
            bayesian_prior_strength=round(self._bayesian_alpha + self._bayesian_beta, 2),
            predictions_until_recovery=predictions_until,
            next_trade_allowed=not self.get_shadow_mode(),
            details=" | ".join(details_parts),
        )


# Module-level convenience functions

_default_calibrator = CalibrationManager()


def update_calibration_bayesian(
    prediction_correct: bool,
    confidence: float = 50.0,
    symbol: str = "",
    signal_type: str = "",
) -> float:
    """Update calibration using Bayesian updating (convenience wrapper)."""
    return _default_calibrator.update_calibration_bayesian(
        prediction_correct, confidence, symbol, signal_type
    )


def get_shadow_mode() -> bool:
    """Check if predictions should be tracked but not traded."""
    return _default_calibrator.get_shadow_mode()


def recover_calibration() -> bool:
    """Attempt to initiate calibration recovery."""
    return _default_calibrator.recover_calibration()


if __name__ == "__main__":
    # Example usage
    print("=" * 60)
    print("Calibration Manager Example")
    print("=" * 60)

    # Start with a degraded multiplier (simulating the death spiral)
    calibrator = CalibrationManager(initial_multiplier=0.5)

    print(f"Initial state: {calibrator.state.value}")
    print(f"Shadow mode: {calibrator.get_shadow_mode()}")
    print(f"Multiplier: {calibrator.multiplier:.3f}")

    # Try to recover
    calibrator.recover_calibration()
    print(f"\nAfter recovery initiation: {calibrator.state.value}")

    # Simulate shadow predictions
    print("\n--- Shadow Predictions ---")
    import random
    random.seed(42)

    for i in range(15):
        # Simulate 70% accuracy in shadow mode
        correct = random.random() < 0.7
        confidence = random.uniform(40, 90)
        mult = calibrator.update_calibration_bayesian(
            correct, confidence, symbol="BTCUSDT", signal_type="BULLISH"
        )
        status = calibrator.get_status()
        if i % 5 == 0:
            print(f"  Prediction {i+1}: {'✓' if correct else '✗'}, "
                  f"mult={mult:.3f}, shadow_acc={status.recent_accuracy:.1%}")

    # Check final status
    print("\n--- Final Status ---")
    final_status = calibrator.get_status()
    print(f"  State: {final_status.state.value}")
    print(f"  Multiplier: {final_status.multiplier}")
    print(f"  Shadow mode: {final_status.in_shadow_mode}")
    print(f"  Total predictions: {final_status.total_predictions}")
    print(f"  Next trade allowed: {final_status.next_trade_allowed}")
    print(f"  Details: {final_status.details}")
