"""
PositionMonitor — checks all open positions on every bot run.

Responsibilities:
  - For live futures: query BitGet directly to see if position is still open
  - For paper / spot: compare current price against SL/TP levels
  - Record closes, write journal, trigger Claude trade analysis
"""
from __future__ import annotations

import uuid
from datetime import datetime

import ccxt

from models.position import Position
from models.trade import Trade, CloseReason
from repositories.journal_repository import JournalRepository
from repositories.position_repository import PositionRepository
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
        self._positions     = position_repo
        self._trade_repos   = trade_repos
        self._journal       = journal_repo
        self._market        = market_data
        self._exchange      = exchange
        self._paper_trading = paper_trading
        self._analyst       = trade_analyst

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
        """
        Route evaluation based on mode:
          - Live futures → ask BitGet if position is still open
          - Paper / spot → compare Binance price against SL/TP
        """
        trade_mode = getattr(position, "trade_mode", "spot")
        is_futures = trade_mode in ("futures", "swap")

        if not self._paper_trading and is_futures:
            return self._evaluate_live_futures(position)
        else:
            return self._evaluate_by_price(position)

    # ── Live futures: query BitGet directly ──────────────────────────────────

    def _evaluate_live_futures(self, position: Position) -> Trade | None:
        """
        Ask BitGet whether the position is still open.
        If it's gone → the exchange closed it via native TP/SL → record it.
        If it's still open → nothing to do this cycle.
        Falls back to price-check if the API call fails.
        """
        trade_mode = getattr(position, "trade_mode", "futures")
        ccxt_sym   = normalise_symbol(position.symbol, trade_mode)
        ccxt_side  = "long" if position.side == "LONG" else "short"

        try:
            exchange_positions = self._exchange.fetch_positions([ccxt_sym])
        except Exception as e:
            log.warning(f"  fetch_positions failed for {position.symbol}: {e} — falling back to price check")
            return self._evaluate_by_price(position)

        # BitGet returns all positions; find ours by side and non-zero contracts
        open_on_exchange = next(
            (
                p for p in exchange_positions
                if p.get("side") == ccxt_side and float(p.get("contracts") or 0) > 0
            ),
            None,
        )

        if open_on_exchange:
            # Position is still open — log current mark price and move on
            mark_price = float(
                open_on_exchange.get("markPrice")
                or open_on_exchange.get("lastPrice")
                or open_on_exchange.get("info", {}).get("markPrice")
                or 0
            )
            if mark_price == 0:
                mark_price = self._market.get_current_price(position.symbol)

            unrealised_pnl = float(open_on_exchange.get("unrealizedPnl") or 0)
            log.info(
                f"  {position.symbol} {position.side} [FUTURES] still open on BitGet"
                f" | Entry ${position.entry_price:,.2f}"
                f" | Mark ${mark_price:,.2f}"
                f" | SL ${position.stop_loss:,.2f} | TP ${position.take_profit:,.2f}"
                f" | uPnL ${unrealised_pnl:+.4f}"
            )
            return None

        # Position is gone from BitGet — it was closed by native TP/SL
        log.info(f"  {position.symbol} {position.side} [FUTURES] — position closed on BitGet")

        # Determine close reason and exit price.
        # Use the preset TP/SL prices directly since that's where the native order filled.
        current_price = self._market.get_current_price(position.symbol)
        close_reason, exit_price = self._infer_close_from_exchange(position, current_price)

        log.info(f"    Inferred: {close_reason.value} | exit ~${exit_price:,.4f}")
        return self._record_close(position, exit_price, close_reason)

    def _infer_close_from_exchange(
        self, position: Position, current_price: float
    ) -> tuple[CloseReason, float]:
        """
        When BitGet already closed the position natively, determine whether
        it was TP or SL, and return the most accurate exit price we can get.

        Strategy:
          1. Try to fetch the most recent closed trade from BitGet for this symbol
          2. Fall back to: whichever of TP/SL the current price is closest to
        """
        # Attempt 1: fetch recent trades from BitGet to get actual fill price
        try:
            trade_mode = getattr(position, "trade_mode", "futures")
            ccxt_sym   = normalise_symbol(position.symbol, trade_mode)
            # fetch last 5 trades, find the close (opposite side to position)
            close_side = "sell" if position.side == "LONG" else "buy"
            trades = self._exchange.fetch_my_trades(ccxt_sym, limit=10)
            # Most recent close trade after position was opened
            for t in reversed(trades):
                if (t.get("side") == close_side
                        and t.get("timestamp", 0) >= position.opened_at.timestamp() * 1000):
                    fill = float(t.get("price") or t.get("average") or 0)
                    if fill > 0:
                        reason = (
                            CloseReason.TAKE_PROFIT
                            if (position.side == "LONG" and fill >= position.entry_price)
                            or (position.side == "SHORT" and fill <= position.entry_price)
                            else CloseReason.STOP_LOSS
                        )
                        log.info(f"    Actual fill from trade history: ${fill:,.4f}")
                        return reason, fill
        except Exception as e:
            log.warning(f"    Could not fetch trade history: {e} — using price heuristic")

        # Attempt 2: heuristic — whichever of TP/SL current price is closest to
        sl_dist = abs(current_price - position.stop_loss)
        tp_dist = abs(current_price - position.take_profit)

        if tp_dist <= sl_dist:
            return CloseReason.TAKE_PROFIT, position.take_profit
        else:
            return CloseReason.STOP_LOSS, position.stop_loss

    # ── Paper / spot: compare price against SL/TP ────────────────────────────

    def _evaluate_by_price(self, position: Position) -> Trade | None:
        """Check a position by comparing current Binance price to SL/TP levels."""
        try:
            current_price = self._market.get_current_price(position.symbol)
        except Exception as e:
            log.warning(f"  Could not fetch price for {position.symbol}: {e}")
            return None

        trade_mode = getattr(position, "trade_mode", "spot")
        log.info(
            f"  {position.symbol} {position.side} [{trade_mode.upper()}]"
            f" | Entry ${position.entry_price:,.2f}"
            f" | Current ${current_price:,.2f}"
            f" | SL ${position.stop_loss:,.2f} | TP ${position.take_profit:,.2f}"
        )

        close_reason = self._detect_close_reason(position, current_price)
        if close_reason is None:
            log.info(f"    Still open. No action.")
            return None

        log.info(f"    {close_reason.value} hit at ${current_price:,.2f}")

        # For paper mode, simulate fill at SL/TP price (not current, which may have moved)
        if self._paper_trading:
            exit_price = position.take_profit if close_reason == CloseReason.TAKE_PROFIT else position.stop_loss
            log.info(f"    PAPER — simulated fill at ${exit_price:,.2f}")
        else:
            exit_price = self._place_close_order(position, current_price)

        return self._record_close(position, exit_price, close_reason)

    # ── Shared close logic ────────────────────────────────────────────────────

    def _record_close(
        self, position: Position, exit_price: float, close_reason: CloseReason
    ) -> Trade | None:
        """Persist the closed trade, write journal, trigger analysis."""
        trade = self._build_trade(position, exit_price, close_reason)

        trade_repo = self._trade_repos.get(position.symbol)
        if trade_repo is None:
            log.error(f"    No TradeRepository for {position.symbol} — cannot save closed trade.")
            return None

        self._positions.close(position.id)
        trade_repo.save(trade)
        journal_path = self._journal.write(trade)

        outcome = "WIN" if trade.is_winner else "LOSS"
        log.info(
            f"    {outcome} | P&L ${trade.pnl_usd:+.4f} ({trade.pnl_pct:+.2f}%)"
            f" | Journal -> {journal_path}"
        )

        if self._analyst:
            self._analyst.analyze(trade, journal_path)

        return trade

    def _place_close_order(self, position: Position, current_price: float) -> float:
        """Place a market close order for spot/margin positions (futures use native TP/SL)."""
        try:
            trade_mode = getattr(position, "trade_mode", "spot")
            is_futures = trade_mode in ("futures", "swap")
            close_side = "sell" if position.side == "LONG" else "buy"
            ccxt_sym   = normalise_symbol(position.symbol, trade_mode)

            if is_futures:
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
            closed_at=datetime.now(),
            order_id=position.order_id,
            strategy_name=position.strategy_name,
            trade_mode=getattr(position, "trade_mode", "spot"),
            entry_conditions=position.entry_conditions,
        )
