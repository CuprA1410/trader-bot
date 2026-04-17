"""
EMA Scalp Strategy — 5m timeframe, futures optimised, bidirectional.

Uses three EMAs for trend alignment, MACD histogram for momentum
confirmation, and RSI to avoid entering into exhausted moves.

Entry conditions:
  LONG:  EMA9 > EMA55 > EMA200  +  RSI > 51  +  MACD histogram > 0
  SHORT: EMA9 < EMA55 < EMA200  +  RSI < 49  +  MACD histogram < 0

Stop loss:  0.5% from entry    (tight — scalp style)
Take profit: 1.0% from entry   (2:1 R:R)

Generates ~10–30 signals per day per symbol.
"""

import pandas as pd
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator

from strategies.base_strategy import BaseStrategy
from models.signal import Signal, Direction
from utils.logger import log


class EmaScalpStrategy(BaseStrategy):

    def __init__(
        self,
        ema_fast:    int   = 9,
        ema_mid:     int   = 55,
        ema_slow:    int   = 200,
        rsi_period:  int   = 14,
        macd_fast:   int   = 12,
        macd_slow:   int   = 26,
        macd_signal: int   = 9,
        sl_pct:      float = 0.005,   # 0.5%
        tp_pct:      float = 0.010,   # 1.0%
    ):
        self._ema_fast    = ema_fast
        self._ema_mid     = ema_mid
        self._ema_slow    = ema_slow
        self._rsi_period  = rsi_period
        self._macd_fast   = macd_fast
        self._macd_slow   = macd_slow
        self._macd_signal = macd_signal
        self._sl_pct      = sl_pct
        self._tp_pct      = tp_pct

    @property
    def name(self) -> str:
        return (
            f"EMA Scalp ({self._ema_fast}/{self._ema_mid}/{self._ema_slow} "
            f"MACD {self._macd_fast}/{self._macd_slow}/{self._macd_signal} "
            f"RSI {self._rsi_period})"
        )

    @property
    def timeframe(self) -> str:
        return "5m"

    @property
    def candles_needed(self) -> int:
        return 300   # warm up EMA200 with margin

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self._ema_slow + 10:
            return self._no_signal(symbol, "not enough candles")

        close = df["close"]

        # ── Indicators ────────────────────────────────────────────────────────
        ema_fast = EMAIndicator(close, window=self._ema_fast).ema_indicator()
        ema_mid  = EMAIndicator(close, window=self._ema_mid).ema_indicator()
        ema_slow = EMAIndicator(close, window=self._ema_slow).ema_indicator()
        rsi      = RSIIndicator(close, window=self._rsi_period).rsi()
        macd_obj = MACD(close,
                        window_slow=self._macd_slow,
                        window_fast=self._macd_fast,
                        window_sign=self._macd_signal)
        hist     = macd_obj.macd_diff()   # histogram = MACD line − signal line

        # Use last CLOSED candle (iloc[-2]) — iloc[-1] is still forming
        i = -2
        price = float(close.iloc[i])
        ef    = float(ema_fast.iloc[i])
        em    = float(ema_mid.iloc[i])
        es    = float(ema_slow.iloc[i])
        rsi_v = float(rsi.iloc[i])
        h     = float(hist.iloc[i])

        if any(pd.isna(v) for v in [ef, em, es, rsi_v, h]):
            return self._no_signal(symbol, "indicator not ready (NaN)")

        log.info(
            f"  [{symbol}] EMA {ef:.1f}/{em:.1f}/{es:.1f}  "
            f"RSI {rsi_v:.1f}  MACD-H {h:.4f}"
        )

        # ── LONG ──────────────────────────────────────────────────────────────
        long_cond = {
            f"EMA{self._ema_fast}>{self._ema_mid}":  ef > em,
            f"EMA{self._ema_mid}>{self._ema_slow}":  em > es,
            "RSI>51":   rsi_v > 51,
            "MACD-H>0": h > 0,
        }
        if all(long_cond.values()):
            sl = round(price * (1 - self._sl_pct), 4)
            tp = round(price * (1 + self._tp_pct), 4)
            return Signal(
                direction=Direction.LONG,
                symbol=symbol,
                entry_price=price,
                stop_loss=sl,
                take_profit=tp,
                timeframe=self.timeframe,
                strategy_name=self.name,
                passed_conditions=[f"LONG: {k}" for k in long_cond],
            )

        # ── SHORT ─────────────────────────────────────────────────────────────
        short_cond = {
            f"EMA{self._ema_fast}<{self._ema_mid}":  ef < em,
            f"EMA{self._ema_mid}<{self._ema_slow}":  em < es,
            "RSI<49":   rsi_v < 49,
            "MACD-H<0": h < 0,
        }
        if all(short_cond.values()):
            sl = round(price * (1 + self._sl_pct), 4)
            tp = round(price * (1 - self._tp_pct), 4)
            return Signal(
                direction=Direction.SHORT,
                symbol=symbol,
                entry_price=price,
                stop_loss=sl,
                take_profit=tp,
                timeframe=self.timeframe,
                strategy_name=self.name,
                passed_conditions=[f"SHORT: {k}" for k in short_cond],
            )

        # ── No signal ─────────────────────────────────────────────────────────
        failed = [k for k, v in {**long_cond, **short_cond}.items() if not v]
        return Signal(
            direction=Direction.NONE,
            symbol=symbol,
            entry_price=price,
            stop_loss=0.0,
            take_profit=0.0,
            timeframe=self.timeframe,
            strategy_name=self.name,
            failed_conditions=failed[:3],
        )

    @staticmethod
    def _no_signal(symbol: str, reason: str) -> Signal:
        return Signal(
            direction=Direction.NONE,
            symbol=symbol,
            entry_price=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            strategy_name="EMA Scalp",
            failed_conditions=[reason],
        )
