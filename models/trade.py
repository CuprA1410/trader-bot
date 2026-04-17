"""
Trade — a completed (closed) position with full P&L data.
Written to trades.csv and triggers a journal entry.
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class CloseReason(str, Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    MANUAL = "MANUAL"
    BLOCKED = "BLOCKED"       # Signal was generated but safety check failed


@dataclass
class Trade:
    id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    size_usd: float
    quantity: float
    close_reason: CloseReason
    paper_trading: bool
    opened_at: datetime
    closed_at: datetime
    order_id: str = ""
    strategy_name: str = ""
    trade_mode: str = "spot"          # "spot" | "futures" | "margin"
    entry_conditions: list[str] = field(default_factory=list)
    failed_conditions: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def pnl_usd(self) -> float:
        """Gross P&L in USD."""
        if self.side == "LONG":
            return (self.exit_price - self.entry_price) * self.quantity
        return (self.entry_price - self.exit_price) * self.quantity

    @property
    def pnl_pct(self) -> float:
        """P&L as a percentage of entry price."""
        if self.entry_price == 0:
            return 0.0
        return round((self.pnl_usd / self.size_usd) * 100, 2)

    @property
    def is_winner(self) -> bool:
        return self.pnl_usd > 0

    @property
    def duration_hours(self) -> float:
        delta = self.closed_at - self.opened_at
        return round(delta.total_seconds() / 3600, 1)

    def to_csv_row(self) -> dict:
        fee = self.size_usd * 0.001
        return {
            "Date": self.closed_at.strftime("%Y-%m-%d"),
            "Time (UTC)": self.closed_at.strftime("%H:%M:%S"),
            "Exchange": "BitGet",
            "Symbol": self.symbol,
            "Side": self.side,
            "Quantity": round(self.quantity, 6),
            "Entry Price": round(self.entry_price, 2),
            "Exit Price": round(self.exit_price, 2),
            "Total USD": round(self.size_usd, 2),
            "PnL USD": round(self.pnl_usd, 4),
            "PnL %": self.pnl_pct,
            "Fee (est.)": round(fee, 4),
            "Close Reason": self.close_reason.value,
            "Duration (h)": self.duration_hours,
            "Order ID": self.order_id,
            "Mode": "PAPER" if self.paper_trading else "LIVE",
            "Market": self.trade_mode.upper(),
            "Strategy": self.strategy_name,
            "Notes": self.notes,
        }
