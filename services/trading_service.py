"""
TradingService — the main orchestrator. Called once per loop cycle.

Token-efficient hybrid approach:
  - Python does ALL indicator calculations and condition checks for all symbols
  - BLOCKED trades are logged to per-symbol CSVs directly — zero Claude tokens
  - Claude is only invoked when Python finds a valid signal (rare)
  - When invoked, Claude does: TradingView visual confirmation → screenshot → place order

Run order every cycle:
  1. Check open positions for SL/TP hits (all symbols)
  2. For each symbol, for each active strategy: fetch candles (at strategy's timeframe), run analysis
     2a. No signal → log BLOCKED to that symbol's CSV (no Claude)
     2b. Signal → call Claude for visual confirmation and execution
     2c. If position was opened, skip remaining strategies for that symbol

Multiple strategies run independently — each uses its own timeframe. Only one position
per symbol is allowed at a time; the first strategy that fires wins.
"""

import uuid
from datetime import datetime
from typing import List

import ccxt

from config import AppConfig
from models.signal import Signal, Direction
from models.position import Position
from models.trade import Trade, CloseReason
from strategies.base_strategy import BaseStrategy
from repositories.position_repository import PositionRepository
from repositories.trade_repository import TradeRepository
from repositories.journal_repository import JournalRepository
from services.market_data_service import MarketDataService
from services.position_monitor import PositionMonitor
from services.signal_handler import SignalHandler
from utils.logger import log


class TradingService:

    def __init__(
        self,
        config: AppConfig,
        strategies: List[BaseStrategy],
        market_data: MarketDataService,
        position_monitor: PositionMonitor,
        position_repo: PositionRepository,
        trade_repos: dict,              # dict[symbol, TradeRepository]
        journal_repo: JournalRepository,
        exchange: ccxt.Exchange,
        signal_handler: SignalHandler,
    ):
        self._config = config
        self._strategies = strategies
        self._market = market_data
        self._monitor = position_monitor
        self._positions = position_repo
        self._trade_repos = trade_repos
        self._journal = journal_repo
        self._exchange = exchange
        self._signal_handler = signal_handler

    def run(self) -> None:
        """Execute one full bot cycle across all configured symbols."""
        cfg = self._config.trading
        self._print_header()

        # ── Step 1: check all open positions (across all symbols) ─────────────
        log.info("\n── Position Monitor ─────────────────────────────────────\n")
        self._monitor.check_all()

        # ── Step 2: analyse each symbol with all strategies ───────────────────
        for symbol in cfg.symbols:
            log.info(f"\n{'═' * 57}")
            log.info(f"  Analysing {symbol}")
            log.info(f"{'═' * 57}\n")
            self._analyse_symbol(symbol)

        self._print_footer()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _analyse_symbol(self, symbol: str) -> None:
        cfg        = self._config.trading
        trade_repo = self._trade_repos[symbol]

        # Check daily limit per symbol (shared across all strategies)
        trades_today = trade_repo.count_today()
        if trades_today >= cfg.max_trades_per_day:
            log.info(f"  Daily limit reached for {symbol}: {trades_today}/{cfg.max_trades_per_day}")
            return
        log.info(f"  Trades today ({symbol}): {trades_today}/{cfg.max_trades_per_day}")

        trade_size = min(cfg.portfolio_value_usd * 0.02, cfg.max_trade_size_usd)

        for strategy in self._strategies:
            # Each strategy checks only its own open positions — different strategies
            # can hold simultaneous positions on the same symbol (e.g. BB Scalp 5m
            # and Supertrend 1H are independent trades with different SL/TP levels)
            if self._positions.has_open_position_for_strategy(symbol, strategy.name):
                log.info(f"  [{strategy.name}] already has open position on {symbol} — skipping.")
                continue

            log.info(f"\n  ── {strategy.name} ({strategy.timeframe}) ──")
            df     = self._market.fetch_candles(symbol, strategy.timeframe, limit=strategy.candles_needed)
            signal = strategy.analyze(df, symbol)
            signal.strategy_name = strategy.name   # stamp so place_order records correct name

            log.info(f"\n  {signal.summary()}\n")

            # SHORT signals are only valid on futures/swap — skip silently on spot/margin
            if (signal.direction == Direction.SHORT
                    and cfg.trade_mode.lower() not in ("futures", "swap")):
                log.info(f"  SHORT signal skipped — TRADE_MODE={cfg.trade_mode} does not support shorting.")
                self._record_blocked(signal, trade_size, trade_repo, strategy)
                continue

            if not signal.is_actionable:
                # No signal — log to CSV directly, zero Claude tokens
                self._record_blocked(signal, trade_size, trade_repo, strategy)
                log.info(f"  No signal for {symbol} [{strategy.name}]. Claude not invoked.")
                continue

            # Valid signal — place immediately, screenshot after for journal
            log.info(f"  Signal: {signal.direction.value} {symbol} @ ${signal.entry_price:,.2f}")
            self._signal_handler.execute(signal)

    def _record_blocked(
        self,
        signal: Signal,
        trade_size: float,
        trade_repo: TradeRepository,
        strategy: BaseStrategy,
    ) -> None:
        """Log a BLOCKED decision to this symbol's CSV."""
        for condition in signal.failed_conditions:
            log.info(f"     - {condition}")

        entry = signal.entry_price if signal.entry_price > 0 else 1
        trade = Trade(
            id=str(uuid.uuid4()),
            symbol=signal.symbol,
            side=signal.direction.value if signal.direction.value != "NONE" else "LONG",
            entry_price=signal.entry_price,
            exit_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            size_usd=trade_size,
            quantity=round(trade_size / entry, 6),
            close_reason=CloseReason.BLOCKED,
            paper_trading=self._config.trading.paper_trading,
            opened_at=datetime.utcnow(),
            closed_at=datetime.utcnow(),
            strategy_name=strategy.name,
            entry_conditions=signal.passed_conditions,
            failed_conditions=signal.failed_conditions,
        )
        trade_repo.save(trade)

    def _print_header(self) -> None:
        cfg      = self._config.trading
        mode     = "PAPER TRADING" if cfg.paper_trading else "LIVE TRADING"
        symbols  = ", ".join(cfg.symbols)
        strat_summary = " | ".join(
            f"{s.name} ({s.timeframe})" for s in self._strategies
        )
        log.info("═" * 57)
        log.info("  Claude Trading Bot v2")
        log.info(f"  {datetime.utcnow().isoformat()}")
        log.info(f"  Mode: {mode}")
        log.info(f"  Strategies ({len(self._strategies)}): {strat_summary}")
        log.info(f"  Symbols: {symbols}")
        log.info("═" * 57)

    @staticmethod
    def _print_footer() -> None:
        log.info("\n" + "═" * 57 + "\n")
