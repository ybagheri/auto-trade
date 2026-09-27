"""Reference strategy: copy this file and replace decide().

This is the whole integration surface. A strategy is any object with a string
``name`` and an ``evaluate(context)`` method that returns a TradeSignal, a
mapping that TradeSignal.from_dict accepts, or None for "no trade right now".

Put the file in this directory and point AUTO_TRADE_STRATEGY at it:

    AUTO_TRADE_STRATEGY=example_strategy:build

Nothing else in the project needs to change.
"""

from __future__ import annotations

from auto_trade.application.strategy import StrategyContext
from auto_trade.domain.models import TradeSignal, utc_now


class ExampleStrategy:
    """Trivial example. It trades only when the symbol has no open position."""

    name = "example-strategy"

    def __init__(self, volume: str = "0.01") -> None:
        self.volume = volume

    def evaluate(self, context: StrategyContext) -> TradeSignal | None:
        if context.open_positions_for:
            return None
        moment = utc_now()
        return TradeSignal.from_dict(
            {
                "id": f"example-{moment.strftime('%Y%m%dT%H%M%SZ')}",
                "timestamp": moment.isoformat().replace("+00:00", "Z"),
                "source": self.name,
                "symbol": context.symbol,
                "action": "BUY",
                "volume": self.volume,
                "comment": "replace this with your library's decision",
            }
        )


def build() -> ExampleStrategy:
    """Factory referenced by AUTO_TRADE_STRATEGY."""
    return ExampleStrategy()
