"""
place_order.py — CLI entry point for placing a single trade.

Called by the Claude /loop agent after it reads TradingView and confirms
all strategy conditions are met.

Usage:
  python place_order.py \
    --symbol BTCUSDT \
    --side LONG \
    --entry 84000 \
    --sl 82320 \
    --tp 87360 \
    --size 20 \
    --conditions "Price above EMA21 and EMA50" "Price above EMA200" "RSI14 in range"

Output: JSON printed to stdout so Claude can read the result.
"""
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import json
import sys
import uuid
from datetime import datetime

from config import load_config
from factories.exchange_factory import ExchangeFactory
from models.position import Position
from repositories.position_repository import PositionRepository
from repositories.trade_repository import TradeRepository
from services.market_data_service import MarketDataService
from utils.logger import log
from utils.market import normalise_symbol


def parse_args():
    parser = argparse.ArgumentParser(description="Place a trade order")
    parser.add_argument("--symbol",     required=True,  help="e.g. BTCUSDT")
    parser.add_argument("--side",       required=True,  help="LONG or SHORT")
    parser.add_argument("--entry",      required=True,  type=float, help="Entry price")
    parser.add_argument("--sl",         required=True,  type=float, help="Stop loss price")
    parser.add_argument("--tp",         required=True,  type=float, help="Take profit price")
    parser.add_argument("--size",       type=float,     default=None, help="Trade size in USD (overrides config)")
    parser.add_argument("--strategy",   default="",     help="Strategy name (for journal)")
    parser.add_argument("--conditions", nargs="+",      default=[], help="Passed conditions (for journal)")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()
    cfg = config.trading

    # ── Validate ──────────────────────────────────────────────────────────────
    if args.side.upper() not in ("LONG", "SHORT"):
        print(json.dumps({"ok": False, "error": "side must be LONG or SHORT"}))
        sys.exit(1)

    trade_mode = cfg.trade_mode.lower()

    # Spot/margin cannot short — reject early rather than failing at the exchange
    if args.side.upper() == "SHORT" and trade_mode not in ("futures", "swap"):
        result = {
            "ok": False,
            "reason": "SHORT_NOT_SUPPORTED",
            "message": f"SHORT signals require TRADE_MODE=futures (current: {trade_mode}). Skipping.",
        }
        print(json.dumps(result))
        return

    position_repo = PositionRepository(cfg.log_dir)
    trade_repo    = TradeRepository(cfg.log_dir, args.symbol)

    # ── Check for existing open position on this symbol ───────────────────────
    if position_repo.has_open_position(args.symbol):
        result = {
            "ok": False,
            "reason": "ALREADY_OPEN",
            "message": f"Already holding an open position on {args.symbol} — skipping.",
        }
        print(json.dumps(result))
        return

    # ── Check daily trade limit ───────────────────────────────────────────────
    trades_today = trade_repo.count_today()
    if trades_today >= cfg.max_trades_per_day:
        result = {
            "ok": False,
            "reason": "DAILY_LIMIT",
            "message": f"Max trades per day reached: {trades_today}/{cfg.max_trades_per_day}",
        }
        print(json.dumps(result))
        return

    # ── Price staleness check ─────────────────────────────────────────────────
    # Reject the trade if price has moved too far from the signal entry.
    # Protects against stale signals, especially on fast timeframes like 5m.
    try:
        binance    = ExchangeFactory.create_binance_readonly()
        market     = MarketDataService(binance)
        live_price = market.get_current_price(args.symbol)
        slippage   = abs(live_price - args.entry) / args.entry * 100
        max_slip   = 0.5   # reject if price moved more than 0.5% from signal entry

        if slippage > max_slip:
            result = {
                "ok": False,
                "reason": "STALE_SIGNAL",
                "message": (
                    f"Price moved {slippage:.2f}% from signal entry ${args.entry:,.4f} "
                    f"to current ${live_price:,.4f} — signal is stale, no order placed."
                ),
            }
            print(json.dumps(result))
            return

        log.info(f"  Price check OK — entry ${args.entry:,.4f} | live ${live_price:,.4f} | slippage {slippage:.3f}%")
    except Exception as e:
        log.warning(f"  Price staleness check failed ({e}) — proceeding anyway")

    # ── Calculate trade size ──────────────────────────────────────────────────
    trade_size = args.size if args.size else min(cfg.portfolio_value_usd * 0.02, cfg.max_trade_size_usd)
    quantity   = round(trade_size / args.entry, 6)

    # ── Place order ───────────────────────────────────────────────────────────
    order_id    = ""
    sl_order_id = ""
    tp_order_id = ""

    if cfg.paper_trading:
        order_id = f"PAPER-{int(datetime.utcnow().timestamp())}"
        log.info(f"PAPER TRADE | {args.side} {args.symbol} ${trade_size:.2f} @ ${args.entry:,.2f}")
        log.info(f"   SL: ${args.sl:,.2f} | TP: ${args.tp:,.2f} | Mode: {trade_mode}")
    else:
        try:
            exchange  = ExchangeFactory.create_bitget(
                config.bitget,
                paper_trading=False,
                trade_mode=trade_mode,
            )
            exchange.load_markets()
            ccxt_sym  = normalise_symbol(args.symbol, trade_mode)
            ccxt_side = "buy" if args.side.upper() == "LONG" else "sell"

            # Enforce exchange minimum lot size.
            # If the minimum lot costs more than MAX_TRADE_SIZE_USD, reject the trade —
            # the guardrail exists for a reason and should never be silently bypassed.
            min_qty = float(
                exchange.markets.get(ccxt_sym, {})
                .get("limits", {}).get("amount", {}).get("min") or 0
            )
            if min_qty and quantity < min_qty:
                min_cost = round(min_qty * args.entry, 2)
                if min_cost > cfg.max_trade_size_usd:
                    result = {
                        "ok": False,
                        "reason": "MIN_LOT_EXCEEDS_MAX_SIZE",
                        "message": (
                            f"Exchange minimum lot for {args.symbol} is {min_qty} "
                            f"(~${min_cost:.2f}) which exceeds MAX_TRADE_SIZE_USD="
                            f"${cfg.max_trade_size_usd:.2f}. "
                            f"Raise MAX_TRADE_SIZE_USD or reduce position on this symbol."
                        ),
                    }
                    print(json.dumps(result))
                    return
                quantity   = min_qty
                trade_size = round(min_cost, 4)
                log.info(
                    f"  Qty below exchange minimum ({min_qty}) "
                    f"— adjusted to {quantity} (${trade_size:.2f})"
                )

            is_futures = trade_mode in ("futures", "swap")

            if is_futures:
                # Set leverage before placing the order
                try:
                    exchange.set_leverage(cfg.futures_leverage, ccxt_sym)
                    log.info(f"  Leverage set to {cfg.futures_leverage}x on {ccxt_sym}")
                except Exception as e:
                    log.warning(f"  Could not set leverage: {e} — proceeding with account default")

                # Futures/swap: market order with preset TP/SL.
                # BitGet v2 one-way (unilateral) mode requires tradeSide="open".
                # presetTakeProfitPrice / presetStopLossPrice attach native TP/SL to
                # the order so the exchange closes the position even if the bot goes
                # offline. PositionMonitor also tracks them in software as a backup.
                # Round TP/SL to the market's tick size (e.g. 0.1 for BTC/USDT:USDT)
                tp_str = exchange.price_to_precision(ccxt_sym, args.tp)
                sl_str = exchange.price_to_precision(ccxt_sym, args.sl)
                order = exchange.create_order(
                    symbol=ccxt_sym,
                    type="market",
                    side=ccxt_side,
                    amount=quantity,
                    price=None,
                    params={
                        "tradeSide":             "open",
                        "presetTakeProfitPrice": tp_str,
                        "presetStopLossPrice":   sl_str,
                    },
                )
                # BitGet echoes preset prices in info; use them as IDs for tracking
                tp_order_id = str(order.get("info", {}).get("presetTakeProfitPrice", "") or "")
                sl_order_id = str(order.get("info", {}).get("presetStopLossPrice",   "") or "")
            else:
                # Spot / margin — plain market order; bot monitors SL/TP in software.
                # BitGet spot market BUY requires a price to calculate cost (amount * price).
                # Passing the signal entry price satisfies this; fill is still at market.
                price_param = args.entry if ccxt_side == "buy" else None
                order = exchange.create_order(
                    symbol=ccxt_sym,
                    type="market",
                    side=ccxt_side,
                    amount=quantity,
                    price=price_param,
                )

            order_id = order.get("id", "")
            fill     = float(order.get("average") or order.get("price") or args.entry)
            log.info(f"ORDER placed | {trade_mode} | entry #{order_id} | fill ${fill:,.4f}")
            log.info(f"   SL: ${args.sl:,.4f} | TP: ${args.tp:,.4f}")

        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            sys.exit(1)

    # ── Save position ─────────────────────────────────────────────────────────
    position = Position(
        id=str(uuid.uuid4()),
        symbol=args.symbol,
        side=args.side.upper(),
        entry_price=args.entry,
        stop_loss=args.sl,
        take_profit=args.tp,
        size_usd=trade_size,
        quantity=quantity,
        paper_trading=cfg.paper_trading,
        opened_at=datetime.utcnow(),
        order_id=order_id,
        sl_order_id=sl_order_id,
        tp_order_id=tp_order_id,
        strategy_name=args.strategy or "Unknown",
        entry_conditions=args.conditions,
        trade_mode=trade_mode,
    )
    position_repo.save(position)

    result = {
        "ok": True,
        "mode": "PAPER" if cfg.paper_trading else "LIVE",
        "trade_mode": trade_mode,
        "position_id": position.id,
        "symbol": args.symbol,
        "side": args.side.upper(),
        "entry": args.entry,
        "sl": args.sl,
        "tp": args.tp,
        "size_usd": trade_size,
        "quantity": quantity,
        "order_id": order_id,
        "sl_order_id": sl_order_id,
        "tp_order_id": tp_order_id,
        "rr_ratio": position.risk_reward_ratio(),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
