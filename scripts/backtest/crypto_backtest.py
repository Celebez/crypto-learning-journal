"""Independent crypto segment backtester."""

import csv
import os
import sys
from typing import Dict, List, Optional, Type

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from crypto.strategy import CryptoStrategy as BaselineCryptoStrategy
from crypto.strategy_v2 import CryptoStrategy as CryptoStrategyV2
from shared.utils import Candle, load_csv


class CryptoBacktester:
    """Backtest crypto symbols with ATR sizing and a daily loss gate."""

    PROFIT_PROTECTION_TRIGGER_PCT = 0.002
    PROFIT_PROTECTION_EXIT_PCT = 0.0005
    TRAILING_STOP_TIERS = (
        (0.02, 0.006),
        (0.012, 0.004),
        (0.007, 0.0025),
        (0.004, 0.0015),
        (0.002, 0.001),
    )
    TIME_EXIT_CANDLES = 6
    TIME_EXIT_TARGET_PCT = 0.02

    def __init__(self, initial_balance: float = 100.0):
        self.initial_balance = initial_balance

    def run(
        self,
        candles: List[Candle],
        symbol: str,
        candles_1h: Optional[List[Candle]] = None,
        strategy_class: Type = BaselineCryptoStrategy,
    ) -> Dict:
        strategy = strategy_class()
        balance = self.initial_balance
        day = ""
        day_start_balance = balance
        position = None
        trades: List[Dict] = []
        equity_curve = [balance]

        for idx in range(strategy.MIN_HISTORY, len(candles)):
            candle = candles[idx]
            current_day = candle.date.split()[0]
            if current_day != day:
                day = current_day
                day_start_balance = balance

            if position:
                exit_price, reason = self._intrabar_exit(position, candle)
                if exit_price is None and self._time_exit_due(position, idx):
                    exit_price, reason = candle.close, "time_exit"
                if exit_price is not None:
                    balance = self._close(position, exit_price, candle.date, reason, balance, trades)
                    position = None

            signal = strategy.generate_signal(candles, idx, candles_1h)
            daily_stop_hit = balance <= day_start_balance * (1.0 - strategy.DAILY_STOP)
            if signal["direction"] != "HOLD" and position and signal["direction"] != position["direction"]:
                balance = self._close(position, candle.close, candle.date, "reverse", balance, trades)
                position = None
                daily_stop_hit = balance <= day_start_balance * (1.0 - strategy.DAILY_STOP)

            if signal["direction"] != "HOLD" and not position and not daily_stop_hit:
                stop_distance = abs(candle.close - signal["stop_loss"])
                if stop_distance > 0:
                    position = {
                        "direction": signal["direction"],
                        "entry": candle.close,
                        "stop_loss": signal["stop_loss"],
                        "take_profit": signal["take_profit"],
                        "size": balance * strategy.RISK_PER_TRADE / stop_distance,
                        "entry_time": candle.date,
                        "confidence": signal["confidence"],
                        "max_favorable_excursion": 0.0,
                        "entry_index": idx,
                        "use_trailing_stop": strategy_class is CryptoStrategyV2,
                    }

            equity_curve.append(balance + self._unrealized(position, candle.close))

        if position:
            balance = self._close(position, candles[-1].close, candles[-1].date, "end_of_backtest", balance, trades)
            equity_curve.append(balance)
        return self._results(symbol, candles, trades, equity_curve, balance)

    @classmethod
    def _intrabar_exit(cls, position: Dict, candle: Candle):
        if position["use_trailing_stop"]:
            return cls._trailing_stop_exit(position, candle)

        entry = position["entry"]
        protection_armed = position["max_favorable_excursion"] >= cls.PROFIT_PROTECTION_TRIGGER_PCT
        if position["direction"] == "BUY":
            protection_exit = entry * (1.0 - cls.PROFIT_PROTECTION_EXIT_PCT)
            if protection_armed and candle.low <= protection_exit:
                return protection_exit, "profit_protection"
            if candle.low <= position["stop_loss"]:
                return position["stop_loss"], "stop_loss"
            if candle.high >= position["take_profit"]:
                return position["take_profit"], "take_profit"
            favorable_excursion = (candle.high - entry) / entry
        else:
            protection_exit = entry * (1.0 + cls.PROFIT_PROTECTION_EXIT_PCT)
            if protection_armed and candle.high >= protection_exit:
                return protection_exit, "profit_protection"
            if candle.high >= position["stop_loss"]:
                return position["stop_loss"], "stop_loss"
            if candle.low <= position["take_profit"]:
                return position["take_profit"], "take_profit"
            favorable_excursion = (entry - candle.low) / entry
        position["max_favorable_excursion"] = max(position["max_favorable_excursion"], favorable_excursion)
        return None, ""

    @classmethod
    def _trailing_stop_exit(cls, position: Dict, candle: Candle):
        entry = position["entry"]
        if position["direction"] == "BUY":
            if candle.low <= position["stop_loss"]:
                return position["stop_loss"], "trailing_stop"
            favorable_price = candle.high
            favorable_excursion = (favorable_price - entry) / entry
        else:
            if candle.high >= position["stop_loss"]:
                return position["stop_loss"], "trailing_stop"
            favorable_price = candle.low
            favorable_excursion = (entry - favorable_price) / entry

        position["max_favorable_excursion"] = max(position["max_favorable_excursion"], favorable_excursion)
        trail_distance = cls._trail_distance(position["max_favorable_excursion"])
        if trail_distance is None:
            return None, ""

        if position["direction"] == "BUY":
            position["stop_loss"] = max(position["stop_loss"], favorable_price * (1.0 - trail_distance))
            if candle.low <= position["stop_loss"]:
                return position["stop_loss"], "trailing_stop"
        else:
            position["stop_loss"] = min(position["stop_loss"], favorable_price * (1.0 + trail_distance))
            if candle.high >= position["stop_loss"]:
                return position["stop_loss"], "trailing_stop"
        return None, ""

    @classmethod
    def _trail_distance(cls, favorable_excursion: float) -> Optional[float]:
        for trigger, distance in cls.TRAILING_STOP_TIERS:
            if favorable_excursion >= trigger:
                return distance
        return None

    @classmethod
    def _time_exit_due(cls, position: Dict, index: int) -> bool:
        return (
            position["use_trailing_stop"]
            and index - position["entry_index"] >= cls.TIME_EXIT_CANDLES
            and position["max_favorable_excursion"] < cls.TIME_EXIT_TARGET_PCT
        )

    @staticmethod
    def _unrealized(position: Optional[Dict], price: float) -> float:
        if not position:
            return 0.0
        move = price - position["entry"] if position["direction"] == "BUY" else position["entry"] - price
        return move * position["size"]

    @classmethod
    def _close(cls, position: Dict, price: float, exit_time: str, reason: str, balance: float, trades: List[Dict]) -> float:
        pnl = cls._unrealized(position, price)
        balance += pnl
        trades.append({
            "direction": position["direction"], "entry_price": position["entry"], "exit_price": price,
            "entry_time": position["entry_time"], "exit_time": exit_time, "size": position["size"],
            "pnl": pnl, "confidence": position["confidence"], "exit_reason": reason, "balance": balance,
        })
        return balance

    def _results(self, symbol: str, candles: List[Candle], trades: List[Dict], equity: List[float], balance: float) -> Dict:
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        loss_total = abs(sum(t["pnl"] for t in losses))
        peak, max_drawdown = self.initial_balance, 0.0
        for value in equity:
            peak = max(peak, value)
            max_drawdown = max(max_drawdown, (peak - value) / peak if peak else 0.0)
        return {
            "segment": "Crypto", "symbol": symbol, "period": f"{candles[0].date} to {candles[-1].date}",
            "total_trades": len(trades), "win_rate": len(wins) / len(trades) if trades else 0.0,
            "profit_factor": sum(t["pnl"] for t in wins) / loss_total if loss_total else float("inf") if wins else 0.0,
            "max_drawdown": max_drawdown, "total_return": (balance - self.initial_balance) / self.initial_balance,
            "trades": trades,
        }


def _print_result(result: Dict) -> None:
    print(f'  {result["symbol"]}: trades={result["total_trades"]}, win={result["win_rate"]:.1%}, '
          f'PF={result["profit_factor"]:.2f}, maxDD={result["max_drawdown"]:.2%}, return={result["total_return"]:.2%}')


def _save_trades(path: str, trades: List[Dict]) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "direction", "entry_price", "exit_price", "entry_time", "exit_time", "size",
            "pnl", "confidence", "exit_reason", "balance",
        ])
        writer.writeheader()
        writer.writerows(trades)


def run_crypto_backtest(mode: str = "baseline") -> List[Dict]:
    """Load crypto CSV files and print one result per symbol."""
    strategies = {
        "baseline": BaselineCryptoStrategy,
        "v2": CryptoStrategyV2,
    }
    if mode not in (*strategies, "compare"):
        raise ValueError(f"Unknown mode: {mode}")
    root = os.path.dirname(os.path.dirname(__file__))
    data_dir = os.path.join(root, "backtest", "data")
    results_dir = os.path.join(root, "backtest", "results")
    os.makedirs(results_dir, exist_ok=True)
    results = []
    btc_1h_path = os.path.join(data_dir, "BTCUSDT_1h.csv")
    btc_1h = load_csv(btc_1h_path) if os.path.exists(btc_1h_path) else None
    selected = strategies.items() if mode == "compare" else ((mode, strategies[mode]),)
    for strategy_name, strategy_class in selected:
        print(f"\nCRYPTO SEGMENT ({strategy_name})")
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            candles = load_csv(os.path.join(data_dir, f"{symbol}_4h.csv"))[-5000:]
            result = CryptoBacktester().run(
                candles,
                symbol,
                btc_1h if symbol == "BTCUSDT" else None,
                strategy_class=strategy_class,
            )
            result["strategy"] = strategy_name
            results.append(result)
            _print_result(result)
            _save_trades(os.path.join(results_dir, f"crypto_{strategy_name}_{symbol}_trades.csv"), result["trades"])
    if mode == "compare":
        print("\nCOMPARISON (v2 - baseline)")
        baseline = {result["symbol"]: result for result in results if result["strategy"] == "baseline"}
        for result in (item for item in results if item["strategy"] == "v2"):
            previous = baseline[result["symbol"]]
            print(
                f'  {result["symbol"]}: trades={result["total_trades"] - previous["total_trades"]:+d}, '
                f'win={result["win_rate"] - previous["win_rate"]:+.1%}, '
                f'return={result["total_return"] - previous["total_return"]:+.2%}'
            )
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("baseline", "v2", "compare"), default="baseline")
    args = parser.parse_args()
    run_crypto_backtest(args.mode)
