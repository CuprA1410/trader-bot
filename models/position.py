"""
Position — an open trade being tracked by the bot.
Created when a signal fires, removed when SL or TP is hit.
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class Position:
    id: str
    symbol: str
    side: str                  # LONG or SHORT
    entry_price: float
    stop_loss: float
    take_profit: float
    size_usd: float
    quantity: float
    paper_trading: bool
    opened_at: datetime
    status: PositionStatus = PositionStatus.OPEN
    order_id: str = ""
    sl_order_id: str = ""       # BitGet stop-loss order ID (live only)
    tp_order_id: str = ""       # BitGet take-profit order ID (live only)
    strategy_name: str = ""
    entry_conditions: list[str] = field(default_factory=list)
    trade_mode: str = "spot"    # "spot", "futures", or "margin"

    def risk_reward_ratio(self) -> float:
        """How much we can gain vs how much we risk."""
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return round(reward / risk, 2) if risk > 0 else 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "size_usd": self.size_usd,
            "quantity": self.quantity,
            "paper_trading": self.paper_trading,
            "opened_at": self.opened_at.isoformat(),
            "status": self.status.value,
            "order_id": self.order_id,
            "sl_order_id": self.sl_order_id,
            "tp_order_id": self.tp_order_id,
            "strategy_name": self.strategy_name,
            "entry_conditions": self.entry_conditions,
            "trade_mode": self.trade_mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(
            id=data["id"],
            symbol=data["symbol"],
            side=data["side"],
            entry_price=data["entry_price"],
            stop_loss=data["stop_loss"],
            take_profit=data["take_profit"],
            size_usd=data["size_usd"],
            quantity=data["quantity"],
            paper_trading=data["paper_trading"],
            opened_at=datetime.fromisoformat(data["opened_at"]),
            status=PositionStatus(data.get("status", "OPEN")),
            order_id=data.get("order_id", ""),
            sl_order_id=data.get("sl_order_id", ""),
            tp_order_id=data.get("tp_order_id", ""),
            strategy_name=data.get("strategy_name", ""),
            entry_conditions=data.get("entry_conditions", []),
            trade_mode=data.get("trade_mode", "spot"),
        )
