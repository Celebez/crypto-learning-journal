"""
improved_risk.py — Position Sizing and Risk Management

Implements proper risk management with:
- ATR-based dynamic stop losses (not fixed percentages)
- Confidence-scaled position sizing
- Exposure caps (per-asset and total)
- Correlation-based risk limits
- Kill switch for excessive drawdown

Usage:
    risk_manager = RiskManager(account_balance=10000)
    size = risk_manager.calculate_position_size(confidence=75, atr=150, entry_price=50000)
    stop = risk_manager.get_stop_loss(entry_price=50000, atr=150, direction="long")
    ok = risk_manager.check_exposure_limits("BTCUSDT", 5000)
    trading_enabled = risk_manager.check_kill_switch()
"""

from __future__ import annotations

import time
import math
import logging
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open position for exposure tracking."""
    symbol: str
    side: str           # "long" or "short"
    entry_price: float
    size: float         # position size in quote currency (e.g., USD)
    quantity: float     # position size in base currency
    stop_loss: float
    take_profit: Optional[float] = None
    timestamp: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class StopLossResult:
    """
    Stop loss calculation result.

    Attributes:
        stop_price: The stop loss price.
        stop_distance: Distance from entry (in price units).
        stop_percentage: Distance as percentage of entry price.
        method: Method used ("atr", "percentage", "fixed").
    """
    stop_price: float
    stop_distance: float
    stop_percentage: float
    method: str


@dataclass
class PositionSizeResult:
    """
    Position sizing result.

    Attributes:
        size_quote: Position size in quote currency (USD).
        size_base: Position size in base currency.
        risk_amount: Maximum loss at stop loss.
        risk_percentage: Risk as percentage of account balance.
        confidence_factor: How confidence affected sizing.
    """
    size_quote: float
    size_base: float
    risk_amount: float
    risk_percentage: float
    confidence_factor: float


@dataclass
class ExposureStatus:
    """Current exposure status."""
    total_exposure: float           # total exposure in quote currency
    total_exposure_pct: float       # as percentage of balance
    per_asset: Dict[str, float]     # per-asset exposure
    per_asset_pct: Dict[str, float] # per-asset as percentage
    max_per_asset_pct: float
    max_total_pct: float
    within_limits: bool
    details: str


@dataclass
class KillSwitchStatus:
    """Kill switch status."""
    is_active: bool
    current_drawdown: float
    max_drawdown: float
    peak_balance: float
    current_balance: float
    threshold: float
    details: str


class RiskManager:
    """
    Comprehensive risk management system.

    Features:
    1. ATR-based dynamic stop losses
    2. Confidence-scaled position sizing
    3. Exposure caps (per-asset and total)
    4. Correlation-based risk limits
    5. Kill switch for excessive drawdown
    """

    # Position sizing defaults
    DEFAULT_RISK_PER_TRADE = 0.02  # 2% of account per trade
    ATR_STOP_MULTIPLIER = 2.0      # stop loss at 2x ATR from entry

    # Confidence scaling: maps confidence (20-100) to risk multiplier (0.3-1.2)
    CONFIDENCE_RISK_MIN = 0.3       # at confidence 20
    CONFIDENCE_RISK_MAX = 1.2       # at confidence 100
    CONFIDENCE_MIDPOINT = 60        # neutral point

    # Exposure limits
    MAX_PER_ASSET_PCT = 0.10        # 10% per asset
    MAX_TOTAL_EXPOSURE_PCT = 0.30   # 30% total

    # Kill switch
    KILL_SWITCH_DRAWDOWN_THRESHOLD = 0.05  # 5% drawdown triggers kill switch
    KILL_SWITCH_RECOVERY_THRESHOLD = 0.03  # recover at 3% drawdown

    # Correlation
    HIGH_CORRELATION_THRESHOLD = 0.7  # assets above this are "highly correlated"

    def __init__(
        self,
        account_balance: float = 10000.0,
        risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
        positions: Optional[List[Position]] = None,
    ):
        """
        Initialize risk manager.

        Args:
            account_balance: Current account balance in quote currency.
            risk_per_trade: Maximum risk per trade as fraction of balance.
            positions: Existing open positions.
        """
        self._account_balance = account_balance
        self._risk_per_trade = risk_per_trade
        self._positions: List[Position] = positions or []
        self._peak_balance = account_balance
        self._kill_switch_active = False
        self._kill_switch_deactivated_at: Optional[float] = None

        # Correlation matrix cache
        self._correlation_cache: Dict[Tuple[str, str], float] = {}

    @property
    def account_balance(self) -> float:
        return self._account_balance

    @account_balance.setter
    def account_balance(self, value: float):
        self._account_balance = value
        self._peak_balance = max(self._peak_balance, value)

    def _confidence_to_risk_factor(self, confidence: float) -> float:
        """
        Map confidence score to a risk scaling factor.

        Higher confidence = willing to risk more per trade.
        Lower confidence = reduce position size.

        Uses sigmoid-like curve for smooth scaling.
        """
        # Clamp confidence to valid range
        conf = max(20.0, min(100.0, confidence))

        # Linear interpolation with bounds
        t = (conf - 20.0) / 80.0  # normalize to 0-1
        factor = self.CONFIDENCE_RISK_MIN + t * (self.CONFIDENCE_RISK_MAX - self.CONFIDENCE_RISK_MIN)

        return round(factor, 3)

    def calculate_position_size(
        self,
        confidence: float,
        atr: float,
        entry_price: float,
        direction: str = "long",
    ) -> PositionSizeResult:
        """
        Calculate position size based on ATR-based risk and confidence.

        Method:
        1. Calculate risk amount = balance × risk_per_trade × confidence_factor
        2. Calculate stop distance = ATR × multiplier
        3. Position size = risk_amount / stop_distance

        Args:
            confidence: Signal confidence score (20-100).
            atr: Average True Range value.
            entry_price: Planned entry price.
            direction: "long" or "short".

        Returns:
            PositionSizeResult with sizing details.
        """
        if atr <= 0 or entry_price <= 0:
            raise ValueError(f"ATR ({atr}) and entry_price ({entry_price}) must be positive")

        # Confidence-scaled risk factor
        confidence_factor = self._confidence_to_risk_factor(confidence)

        # Risk amount in quote currency
        risk_amount = self._account_balance * self._risk_per_trade * confidence_factor

        # Stop distance
        stop_distance = atr * self.ATR_STOP_MULTIPLIER
        stop_percentage = stop_distance / entry_price

        # Position size in base currency: risk_amount / stop_distance = units
        size_base = risk_amount / stop_distance if stop_distance > 0 else 0
        size_base = max(0, size_base)

        # Position size in quote currency
        size_quote = size_base * entry_price if entry_price > 0 else 0

        # Risk percentage of account
        risk_percentage = risk_amount / self._account_balance if self._account_balance > 0 else 0

        result = PositionSizeResult(
            size_quote=round(size_quote, 2),
            size_base=round(size_base, 6),
            risk_amount=round(risk_amount, 2),
            risk_percentage=round(risk_percentage, 4),
            confidence_factor=confidence_factor,
        )

        logger.debug(
            f"Position size: {size_quote:.2f} USD ({size_base:.6f} units), "
            f"risk={risk_amount:.2f} ({risk_percentage:.1%}), "
            f"confidence_factor={confidence_factor:.2f}"
        )

        return result

    def get_stop_loss(
        self,
        entry_price: float,
        atr: float,
        direction: str = "long",
        custom_atr_multiplier: Optional[float] = None,
    ) -> StopLossResult:
        """
        Calculate ATR-based dynamic stop loss.

        Stop placement:
        - Long: entry - (ATR × multiplier)
        - Short: entry + (ATR × multiplier)

        Args:
            entry_price: Planned entry price.
            atr: Average True Range value.
            direction: "long" or "short".
            custom_atr_multiplier: Override default ATR multiplier.

        Returns:
            StopLossResult with stop price and metadata.
        """
        if atr <= 0 or entry_price <= 0:
            raise ValueError(f"ATR ({atr}) and entry_price ({entry_price}) must be positive")

        multiplier = custom_atr_multiplier or self.ATR_STOP_MULTIPLIER
        stop_distance = atr * multiplier

        if direction == "long":
            stop_price = entry_price - stop_distance
        elif direction == "short":
            stop_price = entry_price + stop_distance
        else:
            raise ValueError(f"Invalid direction: {direction}")

        stop_percentage = stop_distance / entry_price

        return StopLossResult(
            stop_price=round(stop_price, 2),
            stop_distance=round(stop_distance, 2),
            stop_percentage=round(stop_percentage, 4),
            method="atr",
        )

    def check_exposure_limits(
        self,
        symbol: str,
        proposed_size: float,
    ) -> Tuple[bool, ExposureStatus]:
        """
        Check if adding a position would exceed exposure limits.

        Checks:
        1. Per-asset limit: no single asset > MAX_PER_ASSET_PCT of balance
        2. Total exposure limit: all positions < MAX_TOTAL_EXPOSURE_PCT of balance

        Args:
            symbol: Trading pair symbol.
            proposed_size: Size of proposed position in quote currency.

        Returns:
            Tuple of (within_limits, ExposureStatus).
        """
        # Calculate current exposure
        per_asset: Dict[str, float] = defaultdict(float)
        for pos in self._positions:
            per_asset[pos.symbol] += pos.size

        # Add proposed position
        per_asset[symbol] += proposed_size
        total_exposure = sum(per_asset.values())

        # Calculate percentages
        per_asset_pct = {
            s: size / self._account_balance if self._account_balance > 0 else 0
            for s, size in per_asset.items()
        }
        total_pct = total_exposure / self._account_balance if self._account_balance > 0 else 0

        # Check limits
        asset_ok = per_asset_pct.get(symbol, 0) <= self.MAX_PER_ASSET_PCT
        total_ok = total_pct <= self.MAX_TOTAL_EXPOSURE_PCT
        within_limits = asset_ok and total_ok

        # Build details
        violations = []
        if not asset_ok:
            violations.append(
                f"Per-asset limit exceeded: {symbol}={per_asset_pct[symbol]:.1%} "
                f"(max {self.MAX_PER_ASSET_PCT:.0%})"
            )
        if not total_ok:
            violations.append(
                f"Total exposure limit exceeded: {total_pct:.1%} "
                f"(max {self.MAX_TOTAL_EXPOSURE_PCT:.0%})"
            )

        details = " | ".join(violations) if violations else "Within limits"

        status = ExposureStatus(
            total_exposure=round(total_exposure, 2),
            total_exposure_pct=round(total_pct, 4),
            per_asset=dict(per_asset),
            per_asset_pct=per_asset_pct,
            max_per_asset_pct=self.MAX_PER_ASSET_PCT,
            max_total_pct=self.MAX_TOTAL_EXPOSURE_PCT,
            within_limits=within_limits,
            details=details,
        )

        return within_limits, status

    def check_correlation_risk(
        self,
        symbol: str,
        correlations: Dict[str, float],
    ) -> Tuple[bool, str]:
        """
        Check if adding a position would create excessive correlated exposure.

        If the proposed symbol is highly correlated with existing positions,
        and combined exposure would be large, this is flagged as risky.

        Args:
            symbol: Trading pair symbol.
            correlations: Dict mapping existing position symbols to their
                         correlation with the proposed symbol (-1 to +1).

        Returns:
            Tuple of (is_acceptable, reason_string).
        """
        # Find correlated existing positions
        correlated_exposure = 0.0
        correlated_symbols = []

        for pos in self._positions:
            corr = correlations.get(pos.symbol, 0.0)
            if abs(corr) >= self.HIGH_CORRELATION_THRESHOLD:
                correlated_exposure += pos.size
                correlated_symbols.append(f"{pos.symbol} (corr={corr:.2f})")

        if not correlated_symbols:
            return True, "No highly correlated positions"

        # Combined correlated exposure
        combined_pct = correlated_exposure / self._account_balance if self._account_balance > 0 else 0

        if combined_pct > self.MAX_TOTAL_EXPOSURE_PCT * 0.5:
            return False, (
                f"High correlated exposure: {combined_pct:.1%} across "
                f"{', '.join(correlated_symbols)} — exceeds 50% of total limit"
            )

        return True, (
            f"Correlated exposure: {combined_pct:.1%} across "
            f"{', '.join(correlated_symbols)} — within safe limits"
        )

    def check_kill_switch(self) -> KillSwitchStatus:
        """
        Check if the kill switch should be activated.

        Kill switch triggers when drawdown exceeds threshold (default 5%).
        When active, all trading is disabled until drawdown recovers below
        the recovery threshold (default 3%).

        Returns:
            KillSwitchStatus with current status.
        """
        # Update peak balance
        self._peak_balance = max(self._peak_balance, self._account_balance)

        # Calculate drawdown
        if self._peak_balance > 0:
            drawdown = (self._peak_balance - self._account_balance) / self._peak_balance
        else:
            drawdown = 0.0

        # Check activation/deactivation
        if not self._kill_switch_active:
            if drawdown >= self.KILL_SWITCH_DRAWDOWN_THRESHOLD:
                self._kill_switch_active = True
                self._kill_switch_deactivated_at = None
                logger.warning(
                    f"KILL SWITCH ACTIVATED: drawdown={drawdown:.1%} "
                    f"(threshold={self.KILL_SWITCH_DRAWDOWN_THRESHOLD:.0%})"
                )
        else:
            # Check for recovery
            if drawdown <= self.KILL_SWITCH_RECOVERY_THRESHOLD:
                self._kill_switch_active = False
                self._kill_switch_deactivated_at = time.time()
                logger.info(
                    f"Kill switch deactivated: drawdown recovered to {drawdown:.1%}"
                )

        details = (
            f"Drawdown: {drawdown:.1%}, "
            f"Peak: {self._peak_balance:.2f}, "
            f"Current: {self._account_balance:.2f}"
        )
        if self._kill_switch_active:
            details += " — TRADING DISABLED"

        return KillSwitchStatus(
            is_active=self._kill_switch_active,
            current_drawdown=round(drawdown, 4),
            max_drawdown=round(
                (self._peak_balance - self._account_balance) / self._peak_balance
                if self._peak_balance > 0 else 0, 4
            ),
            peak_balance=round(self._peak_balance, 2),
            current_balance=round(self._account_balance, 2),
            threshold=self.KILL_SWITCH_DRAWDOWN_THRESHOLD,
            details=details,
        )

    def get_full_risk_assessment(
        self,
        symbol: str,
        confidence: float,
        atr: float,
        entry_price: float,
        direction: str = "long",
        correlations: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """
        Comprehensive risk assessment for a proposed trade.

        Runs all checks and returns a unified result.

        Args:
            symbol: Trading pair symbol.
            confidence: Signal confidence (20-100).
            atr: Average True Range.
            entry_price: Planned entry price.
            direction: "long" or "short".
            correlations: Correlation with existing positions.

        Returns:
            Dict with full risk assessment including all checks.
        """
        assessment = {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "entry_price": entry_price,
            "approved": True,
            "warnings": [],
            "rejections": [],
        }

        # 1. Kill switch check
        ks = self.check_kill_switch()
        assessment["kill_switch"] = ks
        if ks.is_active:
            assessment["approved"] = False
            assessment["rejections"].append(f"Kill switch active: {ks.details}")

        # 2. Position sizing
        sizing = self.calculate_position_size(confidence, atr, entry_price, direction)
        assessment["sizing"] = sizing

        # 3. Stop loss
        stop = self.get_stop_loss(entry_price, atr, direction)
        assessment["stop_loss"] = stop

        # 4. Exposure check
        within_exposure, exposure_status = self.check_exposure_limits(symbol, sizing.size_quote)
        assessment["exposure"] = exposure_status
        if not within_exposure:
            assessment["approved"] = False
            assessment["rejections"].append(f"Exposure limits: {exposure_status.details}")

        # 5. Correlation check
        if correlations:
            corr_ok, corr_msg = self.check_correlation_risk(symbol, correlations)
            assessment["correlation"] = {"ok": corr_ok, "details": corr_msg}
            if not corr_ok:
                assessment["approved"] = False
                assessment["rejections"].append(corr_msg)

        # 6. Risk per trade check
        if sizing.risk_percentage > self._risk_per_trade * 1.5:
            assessment["warnings"].append(
                f"Risk per trade ({sizing.risk_percentage:.1%}) exceeds "
                f"1.5x target ({self._risk_per_trade * 1.5:.1%})"
            )

        return assessment

    def add_position(self, position: Position) -> None:
        """Add a position to tracking."""
        self._positions.append(position)

    def remove_position(self, symbol: str) -> Optional[Position]:
        """Remove and return the first position for a symbol."""
        for i, pos in enumerate(self._positions):
            if pos.symbol == symbol:
                return self._positions.pop(i)
        return None

    def get_positions(self) -> List[Position]:
        """Get all tracked positions."""
        return list(self._positions)


# Module-level convenience functions

_default_risk_manager = RiskManager()


def calculate_position_size(
    confidence: float,
    atr: float,
    entry_price: float,
    direction: str = "long",
) -> PositionSizeResult:
    """Calculate position size (convenience wrapper)."""
    return _default_risk_manager.calculate_position_size(confidence, atr, entry_price, direction)


def get_stop_loss(
    entry_price: float,
    atr: float,
    direction: str = "long",
) -> StopLossResult:
    """Calculate stop loss (convenience wrapper)."""
    return _default_risk_manager.get_stop_loss(entry_price, atr, direction)


def check_exposure_limits(
    symbol: str,
    proposed_size: float,
) -> Tuple[bool, ExposureStatus]:
    """Check exposure limits (convenience wrapper)."""
    return _default_risk_manager.check_exposure_limits(symbol, proposed_size)


def check_kill_switch() -> KillSwitchStatus:
    """Check kill switch status (convenience wrapper)."""
    return _default_risk_manager.check_kill_switch()


if __name__ == "__main__":
    # Example usage
    print("=" * 60)
    print("Risk Manager Example")
    print("=" * 60)

    risk = RiskManager(account_balance=10000)

    # Example: BTC position
    print("\n--- BTC Position Sizing ---")
    sizing = risk.calculate_position_size(
        confidence=75, atr=150.0, entry_price=50000.0, direction="long"
    )
    print(f"Position size: ${sizing.size_quote:.2f} ({sizing.size_base:.6f} BTC)")
    print(f"Risk amount: ${sizing.risk_amount:.2f} ({sizing.risk_percentage:.1%})")
    print(f"Confidence factor: {sizing.confidence_factor}")

    stop = risk.get_stop_loss(50000.0, 150.0, "long")
    print(f"Stop loss: ${stop.stop_price:.2f} ({stop.stop_percentage:.1%} from entry)")

    # Check exposure
    ok, exposure = risk.check_exposure_limits("BTCUSDT", sizing.size_quote)
    print(f"Exposure OK: {ok} — {exposure.details}")

    # Kill switch check
    ks = risk.check_kill_switch()
    print(f"Kill switch: {'ACTIVE' if ks.is_active else 'inactive'} — {ks.details}")

    # Simulate a drawdown
    print("\n--- Simulating Drawdown ---")
    risk.account_balance = 9400  # 6% drawdown
    ks = risk.check_kill_switch()
    print(f"Kill switch: {'ACTIVE' if ks.is_active else 'inactive'} — {ks.details}")

    # Recovery
    risk.account_balance = 9700  # recovered to 3%
    ks = risk.check_kill_switch()
    print(f"After recovery: {'ACTIVE' if ks.is_active else 'inactive'} — {ks.details}")

    # Full risk assessment
    print("\n--- Full Risk Assessment ---")
    assessment = risk.get_full_risk_assessment(
        symbol="ETHUSDT",
        confidence=65,
        atr=12.0,
        entry_price=3000.0,
        direction="long",
        correlations={"BTCUSDT": 0.85},
    )
    print(f"Approved: {assessment['approved']}")
    print(f"Warnings: {assessment['warnings']}")
    print(f"Rejections: {assessment['rejections']}")
