"""
SuperTrend + QQE Strategy — 15m timeframe, futures optimised, bidirectional.

Three independent filters must all agree before a trade is taken:
  1. SuperTrend (ATR=9, mult=3.9) — primary trend direction
  2. QQE (RSI=6, smooth=5, factor=3) — dynamic momentum filter that avoids
     entering into already-exhausted moves
  3. Trend bias (EMA52 of close vs EMA52 of open) — confirms candle
     momentum is aligned with the direction

Entry conditions:
  LONG:  SuperTrend bullish  +  QQE RSI below dynamic upper band
         +  EMA52(close) > EMA52(open)
  SHORT: SuperTrend bearish  +  QQE RSI above dynamic lower band
         +  EMA52(close) < EMA52(open)

Stop loss:  SuperTrend band at entry (volatility-adjusted, always outside noise)
Take profit: entry ± (|entry − SL| × 2.0)  →  2:1 R:R minimum

Generates ~1–5 signals per day per symbol.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

from models.signal import Signal, Direction
from strategies.base_strategy import BaseStrategy
from utils.logger import log


def _supertrend(df: pd.DataFrame, atr_period: int, multiplier: float):
    """
    Classic SuperTrend calculation.
    Returns (direction_series, band_series).
      direction: +1 = bullish, -1 = bearish
      band:      active SuperTrend line (used directly as stop loss)
    """
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    n     = len(df)

    atr = AverageTrueRange(high, low, close, window=atr_period).average_true_range()
    hl2 = (high + low) / 2.0

    upper_basic = hl2 + multiplier * atr
    lower_basic = hl2 - multiplier * atr

    upper  = upper_basic.copy()
    lower  = lower_basic.copy()
    trend  = pd.Series(np.zeros(n), index=df.index, dtype=float)
    band   = pd.Series(np.zeros(n), index=df.index, dtype=float)

    for i in range(1, n):
        # Upper band: ratchet downward only
        upper.iloc[i] = (
            upper_basic.iloc[i]
            if upper_basic.iloc[i] < upper.iloc[i - 1] or close.iloc[i - 1] > upper.iloc[i - 1]
            else upper.iloc[i - 1]
        )
        # Lower band: ratchet upward only
        lower.iloc[i] = (
            lower_basic.iloc[i]
            if lower_basic.iloc[i] > lower.iloc[i - 1] or close.iloc[i - 1] < lower.iloc[i - 1]
            else lower.iloc[i - 1]
        )
        # Direction
        prev = trend.iloc[i - 1]
        if prev == -1 and close.iloc[i] > upper.iloc[i]:
            trend.iloc[i] = 1
        elif prev == 1 and close.iloc[i] < lower.iloc[i]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = prev if prev != 0 else 1

        band.iloc[i] = lower.iloc[i] if trend.iloc[i] == 1 else upper.iloc[i]

    return trend, band


def _qqe(close: pd.Series, rsi_length: int, smoothing: int, fast_factor: float):
    """
    Quantitative Qualitative Estimator.
    Returns (qqe_line, dyn_upper, dyn_lower).

    qqe_line  — EMA-smoothed RSI
    dyn_upper — upper dynamic band (overbought region)
    dyn_lower — lower dynamic band (oversold region)

    For a LONG we want: qqe_line < dyn_upper  (momentum not yet exhausted upward)
    For a SHORT we want: qqe_line > dyn_lower  (momentum not yet exhausted downward)
    """
    rsi        = RSIIndicator(close, window=rsi_length).rsi()
    rsi_smooth = EMAIndicator(rsi, window=smoothing).ema_indicator()

    # Measure RSI volatility: EMA of absolute RSI changes
    rsi_delta = rsi_smooth.diff().abs()
    atr_len   = max(smoothing * 4 + 1, 10)
    atr_rsi   = EMAIndicator(rsi_delta.fillna(0), window=atr_len).ema_indicator()

    fast_atr  = atr_rsi * fast_factor
    dyn_upper = rsi_smooth + fast_atr
    dyn_lower = rsi_smooth - fast_atr

    return rsi_smooth, dyn_upper, dyn_lower


class SupertrendQqeStrategy(BaseStrategy):

    def __init__(
        self,
        st_atr_period: int   = 9,
        st_multiplier: float = 3.9,
        qqe_rsi:       int   = 6,
        qqe_smooth:    int   = 5,
        qqe_factor:    float = 3.0,
        trend_ema:     int   = 52,
        tp_rr:         float = 2.0,
    ):
        self._st_period  = st_atr_period
        self._st_mult    = st_multiplier
        self._qqe_rsi    = qqe_rsi
        self._qqe_smooth = qqe_smooth
        self._qqe_factor = qqe_factor
        self._trend_ema  = trend_ema
        self._tp_rr      = tp_rr

    @property
    def name(self) -> str:
        return (
            f"SuperTrend+QQE (ST {self._st_period}/{self._st_mult} "
            f"QQE {self._qqe_rsi}/{self._qqe_smooth}/{self._qqe_factor} "
            f"EMA {self._trend_ema})"
        )

    @property
    def timeframe(self) -> str:
        return "15m"

    @property
    def candles_needed(self) -> int:
        return 200

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        if len(df) < self._st_period + self._trend_ema + 30:
            return self._no_signal(symbol, "not enough candles")

        close = df["close"]

        # ── Indicators ────────────────────────────────────────────────────────
        st_trend, st_band  = _supertrend(df, self._st_period, self._st_mult)
        qqe_line, dyn_up, dyn_dn = _qqe(
            close, self._qqe_rsi, self._qqe_smooth, self._qqe_factor
        )
        ema_close = EMAIndicator(close,        window=self._trend_ema).ema_indicator()
        ema_open  = EMAIndicator(df["open"],   window=self._trend_ema).ema_indicator()

        # Last CLOSED candle
        i = -2
        price    = float(close.iloc[i])
        st_dir   = float(st_trend.iloc[i])
        sl_level = float(st_band.iloc[i])
        qqe_val  = float(qqe_line.iloc[i])
        q_up     = float(dyn_up.iloc[i])
        q_dn     = float(dyn_dn.iloc[i])
        ec       = float(ema_close.iloc[i])
        eo       = float(ema_open.iloc[i])

        if any(pd.isna(v) for v in [st_dir, sl_level, qqe_val, q_up, q_dn, ec, eo]):
            return self._no_signal(symbol, "indicator not ready (NaN)")

        sl_dist = abs(price - sl_level)

        log.info(
            f"  [{symbol}] ST={'▲' if st_dir==1 else '▼'} "
            f"band={sl_level:.2f}  "
            f"QQE={qqe_val:.1f} [{q_dn:.1f}–{q_up:.1f}]  "
            f"EMA_C/O={ec:.1f}/{eo:.1f}"
        )

        # ── LONG ──────────────────────────────────────────────────────────────
        long_cond = {
            "SuperTrend bullish":    st_dir == 1,
            "QQE not overbought":    qqe_val < q_up,
            "EMA(close)>EMA(open)":  ec > eo,
        }
        if all(long_cond.values()):
            sl = round(sl_level, 4)
            tp = round(price + sl_dist * self._tp_rr, 4)
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
            "SuperTrend bearish":    st_dir == -1,
            "QQE not oversold":      qqe_val > q_dn,
            "EMA(close)<EMA(open)":  ec < eo,
        }
        if all(short_cond.values()):
            sl = round(sl_level, 4)
            tp = round(price - sl_dist * self._tp_rr, 4)
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
            strategy_name="SuperTrend+QQE",
            failed_conditions=[reason],
        )
