"""
ExchangeFactory — creates authenticated ccxt exchange instances.

Centralises all ccxt setup logic. Services never import ccxt directly —
they ask the factory for a connection. To add Bybit or OKX support,
extend this factory without touching anything else.
"""

import ccxt
from config import BitGetConfig
from utils.logger import log


class ExchangeFactory:

    @staticmethod
    def create_bitget(config: BitGetConfig, paper_trading: bool = True) -> ccxt.bitget:
        """
        Return a ccxt BitGet instance.
        - paper_trading=True  → orders are blocked in place_order.py (no API calls)
        - config.demo=True    → connects to BitGet demo environment (real API calls, fake money)
        - demo=False          → connects to BitGet live environment (real money)
        """
        exchange = ccxt.bitget({
            "apiKey":     config.api_key,
            "secret":     config.secret_key,
            "password":   config.passphrase,
            "options": {
                "defaultType": "spot",
            },
        })

        if config.demo:
            exchange.set_sandbox_mode(True)
            log.info("  Exchange: BitGet | Mode: DEMO (sandbox)")
        else:
            mode = "PAPER (local simulation)" if paper_trading else "LIVE"
            log.info(f"  Exchange: BitGet | Mode: {mode}")

        return exchange

    @staticmethod
    def create_binance_readonly() -> ccxt.binance:
        """
        Return a public (no-auth) Binance instance for market data only.
        No API key required — uses the free public endpoints.
        """
        return ccxt.binance({"options": {"defaultType": "spot"}})
