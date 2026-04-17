"""
Van de Poppe Strategy — Golden Pocket + Market Structure.

Entry conditions (all must pass for LONG):
  1. Price above EMA(21) AND EMA(50)  — bullish bias confirmed
  2. Price above EMA(200)             — macro bull market
  3. Price within 0.6% of EMA21/50   — pullback to entry confluence zone
  4. RSI(14) between 40 and 65       — momentum present, not overbought at entry

Spot bot only — no shorts implemented.
"""

import pandas as pd
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

from strategies.base_strategy import BaseStrategy
from models.signal import Signal, Direction
from utils.logger import log


class VanDePoppeStrategy(BaseStrategy):

    # SL/TP owned by the strategy — same as Supertrend and BB Scalp
    _sl_pct: float = 2.0   # 2% below entry
    _tp_pct: float = 4.0   # 4% above entry (2:1 R:R)

    @property
    def name(self) -> str:
        return "Van de Poppe — Golden Pocket + Market Structure"

    @property
    def timeframe(self) -> str:
        return "4h"

    @property
    def candles_needed(self) -> int:
        # EMA(200) is the longest indicator.
        # 250 gives a 50-bar warm-up buffer above the minimum 200 needed.
        return 250

    def analyze(self, df: pd.DataFrame, symbol: str) -> Signal:
        df = self._calculate_indicators(df)
        # Use iloc[-2] — the last fully CLOSED candle.
        # iloc[-1] is the current live candle and is incomplete mid-period.
        latest = df.iloc[-2]

        price   = float(latest["close"])
        ema21   = float(latest["ema21"])
        ema50   = float(latest["ema50"])
        ema200  = float(latest["ema200"])
        rsi14   = float(latest["rsi14"])

        log.info("─" * 55)
        log.info(f"  Van de Poppe Analysis — {symbol}")
        log.info(f"  Price:    ${price:>12,.2f}")
        log.info(f"  EMA(21):  ${ema21:>12,.2f}")
        log.info(f"  EMA(50):  ${ema50:>12,.2f}")
        log.info(f"  EMA(200): ${ema200:>12,.2f}")
        log.info(f"  RSI(14):  {rsi14:>12.2f}")
        log.info("─" * 55)

        passed, failed = [], []

        def check(label: str, condition: bool, detail: str = ""):
            icon = "✅" if condition else "🚫"
            log.info(f"  {icon}  {label}")
            if detail:
                log.info(f"      {detail}")
            (passed if condition else failed).append(label)

        # Determine bias first — no point checking entry zone if bias is wrong
        bullish_bias = price > ema21 and price > ema50 and rsi14 > 50

        if not bullish_bias:
            bias_label = "BEARISH" if price < ema21 and price < ema50 else "NEUTRAL"
            log.info(f"  Bias: {bias_label} — no long entry. No trade.")
            return Signal(
                direction=Direction.NONE,
                symbol=symbol,
                entry_price=price,
                stop_loss=0.0,
                take_profit=0.0,
                timeframe=self.timeframe,
                passed_conditions=[],
                failed_conditions=[f"Bias is {bias_label} — price not above EMA21 & EMA50 with RSI > 50"],
            )

        log.info("  Bias: BULLISH — checking long entry conditions")

        # 1. Price above EMA21 and EMA50
        check(
            "Price above EMA(21) and EMA(50) — bullish bias",
            price > ema21 and price > ema50,
            f"EMA21 ${ema21:,.2f} | EMA50 ${ema50:,.2f} | Price ${price:,.2f}",
        )

        # 2. Price above EMA200 — macro bull market
        check(
            "Price above EMA(200) — macro bull market",
            price > ema200,
            f"Required > ${ema200:,.2f} | Actual ${price:,.2f}",
        )

        # 3. Pullback to entry zone — within 0.6% of EMA21 or EMA50
        dist_ema21 = abs((price - ema21) / ema21) * 100
        dist_ema50 = abs((price - ema50) / ema50) * 100
        nearest_pct = min(dist_ema21, dist_ema50)
        check(
            "Price within 0.6% of EMA(21) or EMA(50) — entry confluence zone",
            nearest_pct < 0.6,
            f"EMA21: {dist_ema21:.2f}% away | EMA50: {dist_ema50:.2f}% away | Nearest: {nearest_pct:.2f}%",
        )

        # 4. RSI(14) between 40 and 65 — not overbought
        check(
            "RSI(14) between 40–65 — momentum present, not overbought",
            40 <= rsi14 <= 65,
            f"Required: 40–65 | Actual: {rsi14:.2f}",
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

        # All conditions met — calculate SL and TP
        sl = round(price * (1 - self._sl_pct / 100), 2)
        tp = round(price * (1 + self._tp_pct / 100), 2)

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

    @staticmethod
    def _calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema21"]  = EMAIndicator(close=df["close"], window=21).ema_indicator()
        df["ema50"]  = EMAIndicator(close=df["close"], window=50).ema_indicator()
        df["ema200"] = EMAIndicator(close=df["close"], window=200).ema_indicator()
        df["rsi14"]  = RSIIndicator(close=df["close"], window=14).rsi()
        return df.dropna()
