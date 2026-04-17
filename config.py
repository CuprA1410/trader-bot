"""
Application configuration — loads all environment variables into typed dataclasses.
Single source of truth for every configurable value in the bot.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class BitGetConfig:
    api_key: str
    secret_key: str
    passphrase: str
    base_url: str = "https://api.bitget.com"
    demo: bool = False      # True = BitGet demo trading (sandbox), False = live


@dataclass(frozen=True)
class TradingConfig:
    strategies: list[str]       # one or more: ["ema_scalp", "supertrend_qqe"]
    symbols: list[str]          # all pairs to monitor e.g. ["BTCUSDT", "ETHUSDT"]
    portfolio_value_usd: float
    risk_pct: float             # fraction of portfolio to risk per trade (e.g. 0.01 = 1%)
    max_trade_size_usd: float   # safety cap on margin per trade (prevents runaway sizing)
    max_trades_per_day: int     # per symbol
    paper_trading: bool
    trade_mode: str             # "spot" | "futures" | "margin"
    futures_leverage: int       # leverage for futures orders (ignored on spot/margin)
    log_dir: str


@dataclass(frozen=True)
class AppConfig:
    bitget: BitGetConfig
    trading: TradingConfig


def load_config() -> AppConfig:
    """Build and return the full application config from environment variables."""
    log_dir = os.getenv("LOG_DIR", "data")
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(f"{log_dir}/journal", exist_ok=True)
    os.makedirs(f"{log_dir}/screenshots", exist_ok=True)

    # SYMBOLS env var is comma-separated: "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT"
    # Falls back to legacy SYMBOL single value for backwards compatibility
    symbols_raw = os.getenv("SYMBOLS") or os.getenv("SYMBOL", "BTCUSDT")
    symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]

    # STRATEGIES is comma-separated: "supertrend_rsi,bb_rsi_scalp"
    # Falls back to legacy STRATEGY (single value) for backwards compatibility
    strategies_raw = os.getenv("STRATEGIES") or os.getenv("STRATEGY", "supertrend_rsi")
    strategies = [s.strip() for s in strategies_raw.split(",") if s.strip()]

    return AppConfig(
        bitget=BitGetConfig(
            api_key=os.getenv("BITGET_API_KEY", ""),
            secret_key=os.getenv("BITGET_SECRET_KEY", ""),
            passphrase=os.getenv("BITGET_PASSPHRASE", ""),
            base_url=os.getenv("BITGET_BASE_URL", "https://api.bitget.com"),
            demo=os.getenv("BITGET_DEMO", "false").lower() == "true",
        ),
        trading=TradingConfig(
            strategies=strategies,
            symbols=symbols,
            portfolio_value_usd=float(os.getenv("PORTFOLIO_VALUE_USD", "1000")),
            risk_pct=float(os.getenv("RISK_PCT", "0.01")),
            max_trade_size_usd=float(os.getenv("MAX_TRADE_SIZE_USD", "200")),
            max_trades_per_day=int(os.getenv("MAX_TRADES_PER_DAY", "50")),
            paper_trading=os.getenv("PAPER_TRADING", "true").lower() != "false",
            trade_mode=os.getenv("TRADE_MODE", "spot"),
            futures_leverage=int(os.getenv("FUTURES_LEVERAGE", "5")),
            log_dir=log_dir,
        ),
    )
