"""
MarketDataService — fetches OHLCV candle data from Binance (public, no auth).

The only class that talks to Binance. Returns a clean pandas DataFrame
that strategies consume directly. Uses ccxt for consistent data format.
"""

import pandas as pd
import ccxt
from utils.logger import log


# Map our timeframe strings to ccxt format
TIMEFRAME_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1h", "1h": "1h", "4H": "4h", "4h": "4h",
    "1D": "1d", "1d": "1d", "1W": "1w", "1w": "1w",
}


class MarketDataService:

    # Need 500 bars so EMA(200) has enough history to warm up accurately
    DEFAULT_LIMIT = 500

    def __init__(self, exchange: ccxt.Exchange):
        self._exchange = exchange

    def fetch_candles(self, symbol: str, timeframe: str, limit: int = DEFAULT_LIMIT) -> pd.DataFrame:
        """
        Fetch OHLCV bars and return a DataFrame sorted oldest → newest.

        Args:
            symbol:    e.g. "BTCUSDT" — will be normalised to "BTC/USDT" for ccxt
            timeframe: e.g. "4h", "4H", "1D"
            limit:     number of bars to fetch

        Returns:
            DataFrame with columns: [time, open, high, low, close, volume]
        """
        ccxt_symbol = self._normalise_symbol(symbol)
        ccxt_tf = TIMEFRAME_MAP.get(timeframe, timeframe.lower())

        log.info(f"  Fetching {limit} × {ccxt_tf} candles for {ccxt_symbol} from Binance")

        raw = self._exchange.fetch_ohlcv(ccxt_symbol, ccxt_tf, limit=limit)

        df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = df.sort_values("time").reset_index(drop=True)

        log.info(f"  Fetched {len(df)} bars | Latest close: ${df['close'].iloc[-1]:,.2f}")
        return df

    def get_current_price(self, symbol: str) -> float:
        """Fetch the latest close price for a symbol."""
        df = self.fetch_candles(symbol, "1m", limit=2)
        return float(df["close"].iloc[-1])

    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        """Convert BTCUSDT → BTC/USDT for ccxt."""
        if "/" in symbol:
            return symbol
        # Handle common quote currencies
        for quote in ("USDT", "USDC", "BTC", "ETH", "BNB"):
            if symbol.endswith(quote):
                base = symbol[: -len(quote)]
                return f"{base}/{quote}"
        return symbol
