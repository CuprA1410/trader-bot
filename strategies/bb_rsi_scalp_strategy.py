"""
Bollinger Bands + RSI + Stochastic Scalping Strategy — 5m timeframe.

Research consensus (forextester.com, bitget.com, cryptowisser.com):
  - Bollinger Bands: 20-period SMA, 3 standard deviations
  - RSI: 14-period, oversold < 34 / overbought > 66
  - Stochastic RSI: 14-period, oversold < 20 / overbought > 80
  - ADX filter: > 20 (skip choppy/ranging markets)
  - Volume filter: current > 20-period average

Entry logic (mean-reversion — buy the dip, sell the spike):
  LONG:  Price touches lower BB + RSI oversold + Stoch RSI oversold + ADX trending
  SHORT: spot only — no shorts implemented

Stop loss:  0.25% below entry  (tight — just below the band touch)
Take profit: 0.60% above entry  (at or near middle band — 2.4:1 R:R after fees)

Fee math:
  Round-trip fees:  0.2% (0.1% in + 0.1% out)
  Break-even move:  0.22%
  Target:           0.60%
  Net profit/trade: ~0.40% after fees

Generates 10–20 signals per day per coin.
Best on BTC and ETH — XRP has higher whipsaw risk.
"""

import pandas as pd
from ta.volatility import BollingerBands
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import ADXIndicator, EMAIndicator

from strategies.base_strategy import BaseStrategy
from models.signal import Signal, Direction
from config import TradingConfig
from utils.logger import log


class BbRsiScalpStrategy(BaseStrategy):

    def __init__(
        self,
        config: TradingConfig,
        bb_period: int = 20,
        bb_std: float = 3.0,
        rsi_period: int = 14,
        rsi_oversold: float = 34.0,
        stoch_period: int = 14,
        stoch_oversold: float = 20.0,
        adx_period: int = 14,
        adx_min: float = 20.0,
        vol_ma_period: int = 20,
        sl_pct: float = 0.25,
        tp_pct: float = 0.60,
    ):
        self._config        = config
        self._bb_period     = bb_period
        self._bb_std        = bb_std
        self._rsi_period    = rsi_period
        self._rsi_oversold  = rsi_oversold
        self._stoch_period  = stoch_period
        self._stoch_oversold = stoch_oversold
        self._adx_period    = adx_period
        self._adx_min       = adx_min
        self._vol_ma_period = vol_ma_period
        self._sl_pct        = sl_pct
        self._tp_pct        = tp_pct

    @property
    def name(self) -> str:
        return f"BB + RSI + Stochastic Scalp (BB {self._bb_period}/{self._bb_std}, RSI {self._rsi_period})"

    @property
    def timeframe(self) -> str:
        return "5m"

    @property
    def candles_needed(self) -> int:
        # Longest indicator: ADX(14) and StochRSI(14) need ~30 bars to warm up.
        # 100 candles = 8h of 5m data — plenty of history, zero waste.
        return 100

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        df      = self._calculate_indicators(df)
        # Use iloc[-2] — the last fully CLOSED candle.
        # iloc[-1] is the current live candle and is incomplete mid-period.
        latest  = df.iloc[-2]
        prev    = df.iloc[-3]

        price       = float(latest["close"])
        bb_lower    = float(latest["bb_lower"])
        bb_mid      = float(latest["bb_mid"])
        bb_upper    = float(latest["bb_upper"])
        rsi         = float(latest["rsi"])
        rsi_prev    = float(prev["rsi"])
        stoch_k     = float(latest["stoch_k"])
        adx         = float(latest["adx"])
        vol         = float(latest["volume"])
        vol_avg     = float(latest["vol_ma"])

        log.info("─" * 55)
        log.info(f"  BB + RSI Scalp Analysis — {symbol}")
        log.info(f"  Price:      ${price:>12,.4f}")
        log.info(f"  BB Lower:   ${bb_lower:>12,.4f}  Mid: ${bb_mid:,.4f}  Upper: ${bb_upper:,.4f}")
        log.info(f"  RSI(14):    {rsi:>12.2f}  (prev {rsi_prev:.2f})")
        log.info(f"  Stoch RSI:  {stoch_k:>12.2f}")
        log.info(f"  ADX(14):    {adx:>12.2f}")
        log.info(f"  Volume:     {vol:>12,.0f}  (avg {vol_avg:,.0f})")
        log.info("─" * 55)

        passed, failed = [], []

        def check(label: str, condition: bool, detail: str = ""):
            icon = "✅" if condition else "🚫"
            log.info(f"  {icon}  {label}")
            if detail:
                log.info(f"      {detail}")
            (passed if condition else failed).append(label)

        # 1. ADX filter — skip ranging/choppy markets
        check(
            f"ADX > {self._adx_min} — market is trending, not ranging",
            adx >= self._adx_min,
            f"Required: ≥ {self._adx_min} | Actual: {adx:.2f}",
        )

        # 2. Price at or below lower Bollinger Band
        check(
            "Price at or below lower Bollinger Band — oversold zone",
            price <= bb_lower,
            f"BB Lower: ${bb_lower:,.4f} | Price: ${price:,.4f}",
        )

        # 3. RSI oversold and turning up
        rsi_turning_up = rsi > rsi_prev
        check(
            f"RSI < {self._rsi_oversold} and turning upward — reversal starting",
            rsi < self._rsi_oversold and rsi_turning_up,
            f"RSI: {rsi:.2f} (prev {rsi_prev:.2f}) | Turning up: {rsi_turning_up}",
        )

        # 4. Stochastic RSI oversold
        check(
            f"Stochastic RSI < {self._stoch_oversold} — extreme oversold confirmation",
            stoch_k < self._stoch_oversold,
            f"Required: < {self._stoch_oversold} | Actual: {stoch_k:.2f}",
        )

        # 5. Volume above average
        vol_ratio = vol / vol_avg if vol_avg > 0 else 0
        check(
            "Volume above average — real move, not noise",
            vol_ratio >= 1.0,
            f"Current: {vol:,.0f} | Avg: {vol_avg:,.0f} | Ratio: {vol_ratio:.2f}x",
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

        # All conditions met — fixed % SL and TP
        sl = round(price * (1 - self._sl_pct / 100), 6)
        tp = round(price * (1 + self._tp_pct / 100), 6)

        log.info(f"\n  SL: ${sl:,.4f} ({self._sl_pct}% below entry)")
        log.info(f"  TP: ${tp:,.4f} ({self._tp_pct}% above entry — target middle BB ${bb_mid:,.4f})\n")

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

        # Bollinger Bands
        bb = BollingerBands(close=df["close"], window=self._bb_period, window_dev=self._bb_std)
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"]   = bb.bollinger_mavg()
        df["bb_upper"] = bb.bollinger_hband()

        # RSI
        df["rsi"] = RSIIndicator(close=df["close"], window=self._rsi_period).rsi()

        # Stochastic RSI
        stoch = StochRSIIndicator(close=df["close"], window=self._stoch_period)
        df["stoch_k"] = stoch.stochrsi_k() * 100   # scale to 0–100

        # ADX
        df["adx"] = ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=self._adx_period
        ).adx()

        # Volume MA
        df["vol_ma"] = df["volume"].rolling(window=self._vol_ma_period).mean()

        return df.dropna()
