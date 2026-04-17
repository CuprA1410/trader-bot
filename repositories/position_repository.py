"""
PositionRepository — persists open positions to positions.json.

Positions survive container restarts on Railway via the persistent volume.
This is the source of truth for what the bot currently holds.
"""
from __future__ import annotations

import json
import os

from models.position import Position, PositionStatus
from utils.logger import log


class PositionRepository:

    def __init__(self, log_dir: str):
        self._path = os.path.join(log_dir, "positions.json")

    # ── Public interface ──────────────────────────────────────────────────────

    def get_open(self) -> list[Position]:
        """Return all positions with OPEN status."""
        return [p for p in self._load_all() if p.status == PositionStatus.OPEN]

    def save(self, position: Position) -> None:
        """Add or update a position in the store."""
        all_positions = self._load_all()
        existing_ids = {p.id for p in all_positions}

        if position.id in existing_ids:
            all_positions = [position if p.id == position.id else p for p in all_positions]
        else:
            all_positions.append(position)

        self._write(all_positions)
        log.info(f"  Position saved: {position.id} | {position.side} {position.symbol} @ ${position.entry_price:,.2f}")

    def close(self, position_id: str) -> None:
        """Mark a position as CLOSED."""
        all_positions = self._load_all()
        for p in all_positions:
            if p.id == position_id:
                p.status = PositionStatus.CLOSED
        self._write(all_positions)
        log.info(f"  Position closed: {position_id}")

    def has_open_position(self, symbol: str) -> bool:
        """Check if any strategy has an open position for this symbol."""
        return any(p.symbol == symbol for p in self.get_open())

    def has_open_position_for_strategy(self, symbol: str, strategy_name: str) -> bool:
        """Check if THIS specific strategy already has an open position for this symbol.
        Allows multiple strategies to hold simultaneous positions on the same symbol."""
        return any(
            p.symbol == symbol and p.strategy_name == strategy_name
            for p in self.get_open()
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_all(self) -> list[Position]:
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [Position.from_dict(p) for p in data]
        except (json.JSONDecodeError, KeyError):
            log.warning(f"  Could not parse {self._path} — starting fresh")
            return []

    def _write(self, positions: list[Position]) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump([p.to_dict() for p in positions], f, indent=2)
