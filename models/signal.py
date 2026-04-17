"""
Signal — the output of a strategy analysis.
Carries everything needed to decide whether to place a trade.
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


@dataclass
class Signal:
    direction: Direction
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: float
    timeframe: str = "1h"
    strategy_name: str = ""
    passed_conditions: list[str] = field(default_factory=list)
    failed_conditions: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_actionable(self) -> bool:
        """True when the signal has a clear direction and no failed conditions."""
        return self.direction != Direction.NONE and len(self.failed_conditions) == 0

    def summary(self) -> str:
        if self.is_actionable:
            return (
                f"✅ {self.direction.value} signal on {self.symbol} @ ${self.entry_price:,.2f} "
                f"| SL ${self.stop_loss:,.2f} | TP ${self.take_profit:,.2f}"
            )
        failed = ", ".join(self.failed_conditions)
        return f"🚫 No trade — failed: {failed}"
