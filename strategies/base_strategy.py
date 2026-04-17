"""
BaseStrategy — abstract interface all trading strategies must implement.

Adding a new strategy:
  1. Create strategies/my_strategy.py
  2. Subclass BaseStrategy
  3. Implement analyze() and the name property
  4. Pass it to TradingService in main.py

No other file needs to change.
"""

from abc import ABC, abstractmethod
import pandas as pd
from models.signal import Signal


class BaseStrategy(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name, shown in logs and journal entries."""
        ...

    @property
    @abstractmethod
    def timeframe(self) -> str:
        """
        Candle timeframe this strategy is designed for (e.g. "1h", "4h", "1d").
        Used by TradingService when fetching market data — no need to set TIMEFRAME in .env.
        """
        ...

    @property
    def candles_needed(self) -> int:
        """
        How many candles to fetch from the exchange.
        Override in each strategy based on the longest indicator period used.
        Default 250 — enough to warm up EMA(200) with a safety margin.
        Strategies without EMA(200) should override with a smaller value.
        """
        return 250

    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        """
        Analyse candle data and return a Signal.

        Args:
            df: OHLCV DataFrame with columns [open, high, low, close, volume].
                Rows are sorted oldest → newest. Last row = current candle.
            symbol: Trading pair (e.g. "BTCUSDT")

        Returns:
            Signal with direction LONG, SHORT, or NONE.
            NONE means conditions were not met — no trade should be placed.
        """
        ...
