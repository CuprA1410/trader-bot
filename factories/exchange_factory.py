"""
ExchangeFactory — creates authenticated ccxt exchange instances.

Centralises all ccxt setup logic. Services never import ccxt directly —
they ask the factory for a connection. To add Bybit or OKX support,
extend this factory without touching anything else.
"""

import ccxt
from config import BitGetConfig
from utils.logger import log

# Map trade_mode → ccxt defaultType for BitGet
_BITGET_TYPE_MAP = {
    "spot":    "spot",
    "margin":  "margin",
    "futures": "swap",
    "swap":    "swap",
}


class ExchangeFactory:

    @staticmethod
    def create_bitget(
        config: BitGetConfig,
        paper_trading: bool = True,
        trade_mode: str = "spot",
    ) -> ccxt.bitget:
        """
        Return a ccxt BitGet instance configured for the requested trade mode.

        trade_mode values:
          "spot"    → defaultType "spot"   (basic BTC/USDT market)
          "margin"  → defaultType "margin" (spot margin)
          "futures" → defaultType "swap"   (linear perpetual, BTC/USDT:USDT)

        paper_trading=True  → orders are blocked in place_order.py (no API calls)
        config.demo=True    → connects to BitGet demo environment (real API calls, fake money)
        """
        ccxt_type = _BITGET_TYPE_MAP.get(trade_mode.lower(), "spot")

        exchange = ccxt.bitget({
            "apiKey":   config.api_key,
            "secret":   config.secret_key,
            "password": config.passphrase,
            "options": {
                "defaultType": ccxt_type,
            },
        })

        if config.demo:
            exchange.set_sandbox_mode(True)
            log.info(f"  Exchange: BitGet | Mode: DEMO (sandbox) | Market: {trade_mode} (ccxt type: {ccxt_type})")
        else:
            mode = "PAPER (local simulation)" if paper_trading else "LIVE"
            log.info(f"  Exchange: BitGet | Mode: {mode} | Market: {trade_mode} (ccxt type: {ccxt_type})")

        return exchange

    @staticmethod
    def create_binance_readonly() -> ccxt.binance:
        """
        Return a public (no-auth) Binance instance for market data only.
        No API key required — uses the free public endpoints.
        """
        return ccxt.binance({"options": {"defaultType": "spot"}})
