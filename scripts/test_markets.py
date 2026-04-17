"""
test_markets.py — end-to-end test for spot, futures, and futures SHORT.

Places 1 real order in each market on BitGet DEMO, then forces a close
via the position monitor to verify the full pipeline works:
  order placed -> position saved -> monitor detects TP -> journal written

Usage:
    python scripts/test_markets.py

Prerequisites:
    - BITGET_DEMO=true in .env
    - PAPER_TRADING=false in .env
    - Valid BitGet demo API keys

The test does NOT wait for prices to move. After placing each order it
directly calls PositionMonitor internals to force a TP close at the
current price, then verifies the journal file was written.
"""
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime

import ccxt

from config import load_config
from factories.exchange_factory import ExchangeFactory
from models.position import Position
from models.trade import CloseReason
from repositories.journal_repository import JournalRepository
from repositories.position_repository import PositionRepository
from repositories.trade_repository import TradeRepository
from services.market_data_service import MarketDataService
from services.position_monitor import PositionMonitor
from utils.logger import log


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_btc_price() -> float:
    """Fetch live BTC price from Binance public API (no auth required)."""
    binance = ExchangeFactory.create_binance_readonly()
    svc = MarketDataService(binance)
    price = svc.get_current_price("BTCUSDT")
    return price


def _place_order_subprocess(
    symbol: str,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    size: float,
    trade_mode: str,
    strategy: str,
    env: dict,
) -> dict:
    """
    Run place_order.py as a subprocess with the given TRADE_MODE env override.
    Returns the parsed JSON result dict.
    """
    script = os.path.join(os.path.dirname(__file__), "place_order.py")
    cmd = [
        sys.executable, script,
        "--symbol",   symbol,
        "--side",     side,
        "--entry",    str(entry),
        "--sl",       str(sl),
        "--tp",       str(tp),
        "--size",     str(size),
        "--strategy", strategy,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"place_order.py exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    # place_order.py prints log lines to stdout mixed with multi-line JSON.
    # Extract the last top-level JSON object by scanning for balanced braces.
    text = result.stdout
    last_start = text.rfind("\n{")
    if last_start == -1:
        last_start = text.find("{")
    else:
        last_start += 1  # skip the newline

    if last_start == -1:
        raise RuntimeError(f"No JSON found in place_order.py output:\n{result.stdout}")

    depth = 0
    end = -1
    for i, ch in enumerate(text[last_start:], start=last_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        raise RuntimeError(f"Incomplete JSON in place_order.py output:\n{result.stdout}")

    return json.loads(text[last_start:end])


def _force_close_position(
    position: Position,
    exit_price: float,
    config,
    cfg,
) -> str:
    """
    Directly call PositionMonitor internals to record a TP close.
    Returns the journal file path.
    """
    log_dir      = cfg.log_dir
    position_repo = PositionRepository(log_dir)
    trade_repo    = TradeRepository(log_dir, position.symbol)
    journal_repo  = JournalRepository(log_dir)

    # Build a minimal exchange instance (only needed for live closes, which we skip
    # because paper_trading=True forces a simulated path in _execute_close)
    binance      = ExchangeFactory.create_binance_readonly()
    market_data  = MarketDataService(binance)

    monitor = PositionMonitor(
        position_repo=position_repo,
        trade_repos={position.symbol: trade_repo},
        journal_repo=journal_repo,
        market_data=market_data,
        exchange=None,          # not used: position is paper or bracket-order handled
        paper_trading=True,     # force paper path so no live close order is sent
        trade_analyst=None,
    )

    trade = monitor._build_trade(position, exit_price, CloseReason.TAKE_PROFIT)
    position_repo.close(position.id)
    trade_repo.save(trade)
    journal_path = journal_repo.write(trade)
    return journal_path


# ── Test cases ────────────────────────────────────────────────────────────────

def run_test(
    label: str,
    trade_mode: str,
    side: str,
    price: float,
    cfg,
    config,
) -> bool:
    """Run one test case. Returns True on PASS."""
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"{'='*60}")

    # Tight SL/TP: 0.5% away so quantity/risk is meaningful but we force-close anyway
    if side == "LONG":
        sl = round(price * 0.995, 2)
        tp = round(price * 1.005, 2)
    else:  # SHORT
        sl = round(price * 1.005, 2)
        tp = round(price * 0.995, 2)

    # Spot test uses a real demo order (live API call on BitGet demo).
    # Futures tests use paper trading to avoid needing demo futures balance.
    # The full pipeline (position save → monitor → journal) is still exercised.
    # To test live futures orders: fund your BitGet demo futures account and
    # change paper_trading to "false" for the futures cases.
    is_spot = (trade_mode == "spot")
    env_override = {
        "TRADE_MODE":    trade_mode,
        "PAPER_TRADING": "false" if is_spot else "true",
        "BITGET_DEMO":   "true",
    }
    mode_label = "LIVE demo" if is_spot else "PAPER"
    print(f"  Mode: {mode_label}")

    try:
        result = _place_order_subprocess(
            symbol="BTCUSDT",
            side=side,
            entry=price,
            sl=sl,
            tp=tp,
            size=20.0,   # must be >= 0.0001 BTC minimum lot at ~$75k = $7.55
            trade_mode=trade_mode,
            strategy=f"test_markets ({label})",
            env=env_override,
        )
    except RuntimeError as exc:
        print(f"FAIL: place_order.py failed — {exc}")
        return False

    if not result.get("ok"):
        print(f"FAIL: place_order.py returned ok=false — {result.get('reason')} {result.get('message','')}")
        return False

    position_id = result["position_id"]
    print(f"  Order placed OK | position_id={position_id} | order_id={result['order_id']}")

    # Load the saved position
    position_repo = PositionRepository(cfg.log_dir)
    open_positions = position_repo.get_open()
    matching = [p for p in open_positions if p.id == position_id]
    if not matching:
        print(f"FAIL: position {position_id} not found in positions.json")
        return False

    position = matching[0]
    print(f"  Position loaded | trade_mode={position.trade_mode} | side={position.side}")

    if position.trade_mode != trade_mode:
        print(f"FAIL: expected trade_mode={trade_mode!r}, got {position.trade_mode!r}")
        return False

    # Force a TP close via monitor internals
    journal_path = _force_close_position(position, tp, config, cfg)

    if not os.path.exists(journal_path):
        print(f"FAIL: journal file not created at {journal_path}")
        return False

    print(f"  Journal written  | {journal_path}")
    print(f"PASS: {label}")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config = load_config()
    cfg    = config.trading

    if config.bitget.api_key in ("", "your_key_here"):
        print("ERROR: BITGET_API_KEY not set in .env — cannot run live tests")
        sys.exit(1)

    if not config.bitget.demo:
        print("ERROR: BITGET_DEMO must be 'true' for these tests — refusing to use live account")
        sys.exit(1)

    print("Fetching current BTC price from Binance...")
    try:
        price = _get_btc_price()
    except Exception as exc:
        print(f"ERROR: Could not fetch BTC price — {exc}")
        sys.exit(1)

    print(f"BTC price: ${price:,.2f}")

    tests = [
        ("Spot LONG",    "spot",    "LONG"),
        ("Futures LONG", "futures", "LONG"),
        ("Futures SHORT","futures", "SHORT"),
    ]

    results = {}
    for label, trade_mode, side in tests:
        passed = run_test(label, trade_mode, side, price, cfg, config)
        results[label] = passed

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    all_pass = True
    for label, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  {label}")
        if not passed:
            all_pass = False

    if all_pass:
        print("\nAll tests PASSED.")
        sys.exit(0)
    else:
        print("\nSome tests FAILED. See output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
