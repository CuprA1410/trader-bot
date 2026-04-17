"""
Supertrend + RSI Strategy — 1H timeframe, crypto optimised.

Research consensus parameters:
  - Supertrend: ATR period 10, multiplier 3.0 (4.0 for altcoins)
  - RSI: period 14, midline 50
  - Volume filter: current volume > 1.5x 20-period average
  - EMA 200 bias: only longs above EMA200

Entry conditions (ALL must pass for LONG):
  1. Supertrend is bullish — price above the green line
  2. RSI between 50 and 70 — momentum confirmed, not overbought
  3. Volume > 1.5x 20-period average — real move, not noise
  4. Price above EMA(200) — macro trend filter

Stop loss:  entry - (1.5 × ATR)   — dynamic, accounts for current volatility
Take profit: entry + (3.0 × ATR)  — 2:1 R:R based on ATR SL distance

Spot only — no shorts. Generates 2–5 signals per day per coin on 1H.
"""

import numpy as np
import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

from strategies.base_strategy import BaseStrategy
from models.signal import Signal, Direction
from config import TradingConfig
from utils.logger import log


class SupertrendRsiStrategy(BaseStrategy):

    def __init__(
        self,
        config: TradingConfig,
        atr_period: int = 10,
        atr_multiplier: float = 3.0,
        rsi_period: int = 14,
        volume_ma_period: int = 20,
        volume_multiplier: float = 1.5,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 3.0,
    ):
        self._config         = config
        self._atr_period     = atr_period
        self._multiplier     = atr_multiplier
        self._rsi_period     = rsi_period
        self._vol_ma_period  = volume_ma_period
        self._vol_mult       = volume_multiplier
        self._sl_atr_mult    = sl_atr_mult
        self._tp_atr_mult    = tp_atr_mult

    @property
    def name(self) -> str:
        return f"Supertrend + RSI (ATR {self._atr_period}/{self._multiplier}, RSI {self._rsi_period})"

    @property
    def timeframe(self) -> str:
        return "1h"

    @property
    def candles_needed(self) -> int:
        # EMA(200) is the longest indicator — needs 200 bars to produce values.
        # 250 gives a 50-bar warm-up buffer so the first values aren't distorted.
        return 250

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        df = self._calculate_indicators(df)
        # Use iloc[-2] — the last fully CLOSED candle.
        # iloc[-1] is the current live candle and is incomplete mid-period.
        latest   = df.iloc[-2]
        previous = df.iloc[-3]

        price      = float(latest["close"])
        st_bull    = int(latest["st_direction"]) == 1
        st_line    = float(latest["supertrend"])
        rsi        = float(latest["rsi14"])
        atr        = float(latest["atr"])
        vol        = float(latest["volume"])
        vol_avg    = float(latest["vol_ma"])
        ema200     = float(latest["ema200"])

        log.info("─" * 55)
        log.info(f"  Supertrend + RSI Analysis — {symbol}")
        log.info(f"  Price:       ${price:>12,.2f}")
        log.info(f"  Supertrend:  ${st_line:>12,.2f}  ({'🟢 BULL' if st_bull else '🔴 BEAR'})")
        log.info(f"  RSI(14):     {rsi:>12.2f}")
        log.info(f"  ATR:         ${atr:>12,.2f}")
        log.info(f"  Volume:      {vol:>12,.0f}  (avg {vol_avg:,.0f})")
        log.info(f"  EMA(200):    ${ema200:>12,.2f}")
        log.info("─" * 55)

        passed, failed = [], []

        def check(label: str, condition: bool, detail: str = ""):
            icon = "✅" if condition else "🚫"
            log.info(f"  {icon}  {label}")
            if detail:
                log.info(f"      {detail}")
            (passed if condition else failed).append(label)

        # 1. Supertrend bullish
        check(
            "Supertrend bullish — price above green line",
            st_bull and price > st_line,
            f"Supertrend line: ${st_line:,.2f} | Price: ${price:,.2f}",
        )

        # 2. RSI momentum — between 50 and 70
        check(
            "RSI(14) between 50–70 — momentum confirmed, not overbought",
            50 <= rsi <= 70,
            f"Required: 50–70 | Actual: {rsi:.2f}",
        )

        # 3. Volume confirmation
        vol_ratio = vol / vol_avg if vol_avg > 0 else 0
        check(
            f"Volume > {self._vol_mult}x average — real move, not noise",
            vol_ratio >= self._vol_mult,
            f"Current: {vol:,.0f} | Avg: {vol_avg:,.0f} | Ratio: {vol_ratio:.2f}x",
        )

        # 4. EMA 200 macro filter
        check(
            "Price above EMA(200) — macro bull market",
            price > ema200,
            f"Required > ${ema200:,.2f} | Actual ${price:,.2f}",
        )

        if failed:
            return Signal(
                direction=Direction.NONE,
                symbol=symbol,
                entry_price=price,
                stop_loss=0.0,
                take_profit=0.0,
                timeframe=self.timeframe,
                passed_conditions=passed,
                failed_conditions=failed,
            )

        # All conditions met — ATR-based SL and TP
        sl = round(price - self._sl_atr_mult * atr, 2)
        tp = round(price + self._tp_atr_mult * atr, 2)

        log.info(f"\n  SL: ${sl:,.2f} ({self._sl_atr_mult}× ATR below entry)")
        log.info(f"  TP: ${tp:,.2f} ({self._tp_atr_mult}× ATR above entry — 2:1 R:R)\n")

        return Signal(
            direction=Direction.LONG,
            symbol=symbol,
            entry_price=price,
            stop_loss=sl,
            take_profit=tp,
            timeframe=self.timeframe,
            passed_conditions=passed,
            failed_conditions=[],
        )

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # ATR
        atr_ind     = AverageTrueRange(df["high"], df["low"], df["close"], window=self._atr_period)
        df["atr"]   = atr_ind.average_true_range()

        # Supertrend
        df["supertrend"], df["st_direction"] = self._supertrend(
            df["high"], df["low"], df["close"], df["atr"], self._multiplier
        )

        # RSI
        df["rsi14"]  = RSIIndicator(df["close"], window=self._rsi_period).rsi()

        # EMA 200
        df["ema200"] = EMAIndicator(df["close"], window=200).ema_indicator()

        # Volume moving average
        df["vol_ma"] = df["volume"].rolling(window=self._vol_ma_period).mean()

        return df.dropna()

    @staticmethod
    def _supertrend(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        atr: pd.Series,
        multiplier: float,
    ) -> tuple[pd.Series, pd.Series]:
        """
        Calculate Supertrend line and direction.
        direction: 1 = bullish (green), -1 = bearish (red)
        """
        hl2         = (high + low) / 2
        basic_upper = (hl2 + multiplier * atr).values
        basic_lower = (hl2 - multiplier * atr).values
        close_v     = close.values
        n           = len(close_v)

        final_upper = basic_upper.copy()
        final_lower = basic_lower.copy()
        supertrend  = np.zeros(n)
        direction   = np.zeros(n, dtype=int)

        # Initialise
        supertrend[0] = final_upper[0]
        direction[0]  = -1

        for i in range(1, n):
            # Ratchet upper band down, lower band up
            final_upper[i] = (
                basic_upper[i]
                if basic_upper[i] < final_upper[i - 1] or close_v[i - 1] > final_upper[i - 1]
                else final_upper[i - 1]
            )
            final_lower[i] = (
                basic_lower[i]
                if basic_lower[i] > final_lower[i - 1] or close_v[i - 1] < final_lower[i - 1]
                else final_lower[i - 1]
            )

            # Flip direction when price crosses the active line
            if supertrend[i - 1] == final_upper[i - 1]:
                if close_v[i] > final_upper[i]:
                    supertrend[i] = final_lower[i]
                    direction[i]  = 1    # flipped bullish
                else:
                    supertrend[i] = final_upper[i]
                    direction[i]  = -1
            else:
                if close_v[i] < final_lower[i]:
                    supertrend[i] = final_upper[i]
                    direction[i]  = -1   # flipped bearish
                else:
                    supertrend[i] = final_lower[i]
                    direction[i]  = 1

        return (
            pd.Series(supertrend, index=close.index),
            pd.Series(direction,  index=close.index),
        )
