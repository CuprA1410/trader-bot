"""
PositionMonitor — checks all open positions on every bot run.

Responsibilities:
  - Fetch current price for each open position
  - Detect if SL or TP has been breached
  - Close the position on the exchange (or simulate in paper mode)
  - Delegate persistence to TradeRepository, PositionRepository, JournalRepository
"""

import uuid
from datetime import datetime

import ccxt

from models.position import Position
from models.trade import Trade, CloseReason
from repositories.position_repository import PositionRepository
from repositories.trade_repository import TradeRepository
from repositories.journal_repository import JournalRepository
from services.market_data_service import MarketDataService
from services.trade_analyst import TradeAnalyst
from utils.logger import log
from utils.market import normalise_symbol


class PositionMonitor:

    def __init__(
        self,
        position_repo: PositionRepository,
        trade_repos: dict,          # dict[symbol, TradeRepository] — one CSV per symbol
        journal_repo: JournalRepository,
        market_data: MarketDataService,
        exchange: ccxt.Exchange,
        paper_trading: bool,
        trade_analyst: TradeAnalyst | None = None,
    ):
        self._positions    = position_repo
        self._trade_repos  = trade_repos
        self._journal      = journal_repo
        self._market       = market_data
        self._exchange     = exchange
        self._paper_trading = paper_trading
        self._analyst      = trade_analyst

    def check_all(self) -> list[Trade]:
        """
        Check every open position. Close any that have hit SL or TP.
        Returns a list of trades that were closed this run.
        """
        open_positions = self._positions.get_open()

        if not open_positions:
            log.info("  No open positions to monitor.")
            return []

        log.info(f"  Monitoring {len(open_positions)} open position(s)...")
        closed_trades = []

        for position in open_positions:
            trade = self._evaluate(position)
            if trade:
                closed_trades.append(trade)

        return closed_trades

    # ── Private helpers ───────────────────────────────────────────────────────

    def _evaluate(self, position: Position) -> Trade | None:
        """Check a single position against current price. Return Trade if closed."""
        try:
            current_price = self._market.get_current_price(position.symbol)
        except Exception as e:
            log.warning(f"  Could not fetch price for {position.symbol}: {e}")
            return None

        log.info(
            f"  {position.symbol} {position.side} [{position.trade_mode}] "
            f"| Entry ${position.entry_price:,.2f} "
            f"| Current ${current_price:,.2f} | SL ${position.stop_loss:,.2f} | TP ${position.take_profit:,.2f}"
        )

        close_reason = self._detect_close_reason(position, current_price)
        if close_reason is None:
            log.info(f"    Still open. No action.")
            return None

        log.info(f"    {close_reason.value} hit at ${current_price:,.2f}")

        exit_price = self._execute_close(position, current_price)
        trade = self._build_trade(position, exit_price, close_reason)

        # Persist — use the symbol-specific trade repo
        trade_repo = self._trade_repos.get(position.symbol)
        if trade_repo is None:
            log.error(f"    No TradeRepository for {position.symbol} — cannot save closed trade.")
            return None
        self._positions.close(position.id)
        trade_repo.save(trade)
        journal_path = self._journal.write(trade)

        outcome = "WIN" if trade.is_winner else "LOSS"
        log.info(
            f"    {outcome} | P&L ${trade.pnl_usd:+.4f} ({trade.pnl_pct:+.2f}%) "
            f"| Journal -> {journal_path}"
        )

        # Ask Claude to analyze the closed trade and enrich the journal
        if self._analyst:
            self._analyst.analyze(trade, journal_path)

        return trade

    @staticmethod
    def _detect_close_reason(position: Position, price: float) -> CloseReason | None:
        if position.side == "LONG":
            if price <= position.stop_loss:
                return CloseReason.STOP_LOSS
            if price >= position.take_profit:
                return CloseReason.TAKE_PROFIT
        elif position.side == "SHORT":
            if price >= position.stop_loss:
                return CloseReason.STOP_LOSS
            if price <= position.take_profit:
                return CloseReason.TAKE_PROFIT
        return None

    def _execute_close(self, position: Position, current_price: float) -> float:
        """
        Close the position on the exchange.

        Paper mode: simulate the fill price.
        Live with bracket orders (futures native TP/SL): exchange already handled it.
        Live without bracket orders (spot/margin or fallback): place a market close order.
        """
        if self._paper_trading:
            log.info(f"    PAPER — simulated close at ${current_price:,.2f}")
            return current_price

        # Live futures: if bracket orders were placed, the exchange already closed when
        # TP/SL triggered. Just return the price for record-keeping.
        if position.sl_order_id or position.tp_order_id:
            log.info(f"    LIVE — bracket order triggered at ~${current_price:,.2f} (exchange handled close)")
            return current_price

        # Live mode without bracket orders: place a market close order manually.
        # Futures need reduceOnly=True; spot/margin use a plain market sell/buy.
        try:
            trade_mode  = getattr(position, "trade_mode", "spot")
            is_futures  = trade_mode in ("futures", "swap")
            close_side  = "sell" if position.side == "LONG" else "buy"
            ccxt_sym    = normalise_symbol(position.symbol, trade_mode)

            if is_futures:
                # BitGet v2 one-way mode: need tradeSide="close" + reduceOnly to close
                order = self._exchange.create_order(
                    symbol=ccxt_sym,
                    type="market",
                    side=close_side,
                    amount=position.quantity,
                    price=None,
                    params={"reduceOnly": True, "tradeSide": "close"},
                )
            else:
                order = self._exchange.create_order(
                    symbol=ccxt_sym,
                    type="market",
                    side=close_side,
                    amount=position.quantity,
                    price=None,
                )

            fill_price = float(order.get("average") or order.get("price") or current_price)
            log.info(f"    LIVE close order placed | {trade_mode} | Fill: ${fill_price:,.2f}")
            return fill_price
        except Exception as e:
            log.error(f"    Close order failed: {e} — using market price for record")
            return current_price

    @staticmethod
    def _build_trade(position: Position, exit_price: float, reason: CloseReason) -> Trade:
        return Trade(
            id=str(uuid.uuid4()),
            symbol=position.symbol,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            size_usd=position.size_usd,
            quantity=position.quantity,
            close_reason=reason,
            paper_trading=position.paper_trading,
            opened_at=position.opened_at,
            closed_at=datetime.utcnow(),
            order_id=position.order_id,
            strategy_name=position.strategy_name,
            trade_mode=getattr(position, "trade_mode", "spot"),
            entry_conditions=position.entry_conditions,
        )
