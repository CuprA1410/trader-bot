"""
TradeRepository — persists closed trades to a per-symbol CSV file.

Each symbol gets its own file:
  data/trades_BTCUSDT.csv
  data/trades_ETHUSDT.csv
  data/trades_SOLUSDT.csv
  data/trades_XRPUSDT.csv

Owns the CSV schema entirely. Nothing outside this class reads or writes
these files directly.
"""

import os
import csv
from datetime import datetime
from models.trade import Trade
from utils.logger import log


CSV_COLUMNS = [
    "Date", "Time (UTC)", "Exchange", "Symbol", "Side", "Quantity",
    "Entry Price", "Exit Price", "Total USD", "PnL USD", "PnL %",
    "Fee (est.)", "Close Reason", "Duration (h)", "Order ID", "Mode",
    "Market", "Strategy", "Notes",
]


class TradeRepository:

    def __init__(self, log_dir: str, symbol: str):
        self._symbol = symbol
        self._path = os.path.join(log_dir, f"trades_{symbol}.csv")
        self._ensure_file()

    # ── Public interface ──────────────────────────────────────────────────────

    def save(self, trade: Trade) -> None:
        """Append a closed trade to this symbol's CSV."""
        row = trade.to_csv_row()
        with open(self._path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writerow(row)
        log.info(f"  Trade saved → {self._path}")

    def count_today(self) -> int:
        """Count trades executed today (UTC) — excludes BLOCKED rows."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        count = 0
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Date") == today and row.get("Close Reason") not in ("BLOCKED", ""):
                        count += 1
        except FileNotFoundError:
            pass
        return count

    # ── Private helpers ───────────────────────────────────────────────────────

    def _ensure_file(self) -> None:
        """Create the CSV with headers if it doesn't exist yet."""
        if not os.path.exists(self._path):
            with open(self._path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
            log.info(f"  Created {self._path}")
