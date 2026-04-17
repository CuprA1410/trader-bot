"""
check_positions.py — checks all open positions for SL/TP hits.

Called at the start of every /loop cycle before checking for new entries.
Uses per-symbol trade repositories so each closed trade goes to the right CSV.

Usage:
  python check_positions.py

Output: JSON summary of what was checked and closed.
"""

import json
import sys

from config import load_config
from factories.exchange_factory import ExchangeFactory
from repositories.position_repository import PositionRepository
from repositories.trade_repository import TradeRepository
from repositories.journal_repository import JournalRepository
from services.market_data_service import MarketDataService
from services.position_monitor import PositionMonitor


def main():
    config = load_config()
    cfg    = config.trading

    binance       = ExchangeFactory.create_binance_readonly()
    bitget        = ExchangeFactory.create_bitget(config.bitget, cfg.paper_trading)
    market_data   = MarketDataService(binance)
    position_repo = PositionRepository(cfg.log_dir)
    journal_repo  = JournalRepository(cfg.log_dir)

    # Build per-symbol trade repos — covers all configured symbols
    # plus any symbol found in open positions (in case config changed)
    open_positions = position_repo.get_open()
    all_symbols    = set(cfg.symbols) | {p.symbol for p in open_positions}
    trade_repos    = {s: TradeRepository(cfg.log_dir, s) for s in all_symbols}

    monitor = PositionMonitor(
        position_repo=position_repo,
        trade_repos=trade_repos,
        journal_repo=journal_repo,
        market_data=market_data,
        exchange=bitget,
        paper_trading=cfg.paper_trading,
    )

    closed_trades  = monitor.check_all()
    open_positions = position_repo.get_open()

    result = {
        "ok": True,
        "open_positions": len(open_positions),
        "closed_this_run": len(closed_trades),
        "closed": [
            {
                "symbol": t.symbol,
                "side": t.side,
                "close_reason": t.close_reason.value,
                "entry": t.entry_price,
                "exit": t.exit_price,
                "pnl_usd": round(t.pnl_usd, 4),
                "pnl_pct": t.pnl_pct,
                "outcome": "WIN" if t.is_winner else "LOSS",
            }
            for t in closed_trades
        ],
        "still_open": [
            {
                "symbol": p.symbol,
                "side": p.side,
                "entry": p.entry_price,
                "sl": p.stop_loss,
                "tp": p.take_profit,
            }
            for p in open_positions
        ],
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)
