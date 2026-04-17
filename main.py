"""
main.py — Composition Root + loop runner.

Runs on a configurable interval (LOOP_INTERVAL_SECONDS in .env, default 600 = 10 min).

Each symbol gets its own trades_SYMBOL.csv file:
  data/trades_BTCUSDT.csv
  data/trades_ETHUSDT.csv
  data/trades_SOLUSDT.csv
  data/trades_XRPUSDT.csv

Token-efficient design:
  - Python calculates all indicators every cycle for all symbols
  - Claude is only invoked when a valid signal fires
  - Most cycles cost zero tokens (blocked → logged to CSV by Python)

Usage:
  python main.py          ← loops forever (Ctrl+C to stop)
  python main.py --once   ← single run, useful for testing
"""

import argparse
import os
import time

from config import load_config
from factories.exchange_factory import ExchangeFactory
from strategies.van_de_poppe_strategy import VanDePoppeStrategy
from strategies.supertrend_rsi_strategy import SupertrendRsiStrategy
from strategies.bb_rsi_scalp_strategy import BbRsiScalpStrategy
from repositories.position_repository import PositionRepository
from repositories.trade_repository import TradeRepository
from repositories.journal_repository import JournalRepository
from services.market_data_service import MarketDataService
from services.position_monitor import PositionMonitor
from services.signal_handler import SignalHandler
from services.trade_analyst import TradeAnalyst
from services.trading_service import TradingService
from utils.logger import log


def _build_strategies(cfg):
    """Build all active strategies from STRATEGIES env var (comma-separated)."""
    registry = {
        "van_de_poppe":   lambda: VanDePoppeStrategy(),
        "supertrend_rsi": lambda: SupertrendRsiStrategy(cfg),
        "bb_rsi_scalp":   lambda: BbRsiScalpStrategy(cfg),
    }
    active = []
    for name in cfg.strategies:
        key = name.lower()
        if key not in registry:
            raise ValueError(f"Unknown strategy '{key}'. Choose: {list(registry.keys())}")
        strategy = registry[key]()
        log.info(f"Loaded strategy: {strategy.name} ({strategy.timeframe})")
        active.append(strategy)
    return active


def build_service() -> TradingService:
    """Wire all dependencies together. Called once at startup."""
    config = load_config()
    cfg    = config.trading

    log.info(f"Starting bot for symbols: {', '.join(cfg.symbols)}")

    binance = ExchangeFactory.create_binance_readonly()
    bitget  = ExchangeFactory.create_bitget(config.bitget, cfg.paper_trading, cfg.trade_mode)

    # One TradeRepository per symbol → one CSV per symbol
    trade_repos = {
        symbol: TradeRepository(cfg.log_dir, symbol)
        for symbol in cfg.symbols
    }

    position_repo = PositionRepository(cfg.log_dir)
    journal_repo  = JournalRepository(cfg.log_dir)
    market_data = MarketDataService(binance)
    strategies  = _build_strategies(cfg)

    working_dir    = os.path.dirname(os.path.abspath(__file__))
    signal_handler = SignalHandler(working_dir=working_dir)
    trade_analyst  = TradeAnalyst(working_dir=working_dir)

    position_monitor = PositionMonitor(
        position_repo=position_repo,
        trade_repos=trade_repos,
        journal_repo=journal_repo,
        market_data=market_data,
        exchange=bitget,
        paper_trading=cfg.paper_trading,
        trade_analyst=trade_analyst,
    )

    return TradingService(
        config=config,
        strategies=strategies,
        market_data=market_data,
        position_monitor=position_monitor,
        position_repo=position_repo,
        trade_repos=trade_repos,
        journal_repo=journal_repo,
        exchange=bitget,
        signal_handler=signal_handler,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    args = parser.parse_args()

    interval = int(os.getenv("LOOP_INTERVAL_SECONDS", "600"))
    service  = build_service()

    if args.once:
        service.run()
        return

    log.info(f"Bot started — checking every {interval}s. Press Ctrl+C to stop.")

    while True:
        try:
            service.run()
        except Exception as e:
            log.error(f"Cycle error (will retry next interval): {e}", exc_info=True)

        log.info(f"Sleeping {interval}s until next cycle...\n")
        time.sleep(interval)


if __name__ == "__main__":
    main()
