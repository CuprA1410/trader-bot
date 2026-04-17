"""
JournalRepository — writes a markdown trade journal entry for every closed trade.

Each file is saved as: data/journal/YYYY-MM-DD_SYMBOL_SIDE_OUTCOME.md
When /schedule is connected, a Claude agent will enrich these files with
deeper analysis. For now, the bot fills in a structured template automatically.
"""

import os
from datetime import datetime
from models.trade import Trade, CloseReason
from utils.logger import log


class JournalRepository:

    def __init__(self, log_dir: str):
        self._journal_dir = os.path.join(log_dir, "journal")
        os.makedirs(self._journal_dir, exist_ok=True)

    def write(self, trade: Trade) -> str:
        """Create a journal entry markdown file. Returns the file path."""
        outcome = self._outcome_label(trade)
        market = trade.trade_mode.upper()   # SPOT | FUTURES | MARGIN
        filename = (
            f"{trade.closed_at.strftime('%Y-%m-%d_%H%M')}"
            f"_{trade.symbol}_{market}_{trade.side}_{outcome}.md"
        )
        path = os.path.join(self._journal_dir, filename)
        content = self._render(trade, outcome)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        log.info(f"  Journal entry → {path}")
        return path

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _outcome_label(trade: Trade) -> str:
        if trade.close_reason == CloseReason.TAKE_PROFIT:
            return "WIN"
        if trade.close_reason == CloseReason.STOP_LOSS:
            return "LOSS"
        if trade.close_reason == CloseReason.BLOCKED:
            return "BLOCKED"
        return "MANUAL"

    @staticmethod
    def _render(trade: Trade, outcome: str) -> str:
        pnl_sign = "+" if trade.pnl_usd >= 0 else ""
        entry_list = "\n".join(f"- {c}" for c in trade.entry_conditions) or "- N/A"
        failed_list = "\n".join(f"- {c}" for c in trade.failed_conditions) or "- None"

        # Auto-generated analysis based on close reason
        what_happened = _describe_outcome(trade)
        adjustment_hints = _suggest_adjustments(trade)

        entry_iso = trade.opened_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        close_iso = trade.closed_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        market = trade.trade_mode.upper()
        return f"""# Trade Journal — {trade.symbol} {market} {trade.side} | {outcome}

**Opened:** {trade.opened_at.strftime("%Y-%m-%d %H:%M UTC")}
**Closed:** {trade.closed_at.strftime("%Y-%m-%d %H:%M UTC")}
**Strategy:** {trade.strategy_name}
**Market:** {market}
**Mode:** {"📋 PAPER" if trade.paper_trading else "🔴 LIVE"}

---

## Trade Details

| Field          | Value                        |
|----------------|------------------------------|
| Symbol         | {trade.symbol}               |
| Side           | {trade.side}                 |
| Entry Time     | {entry_iso}                  |
| Close Time     | {close_iso}                  |
| Entry Price    | ${trade.entry_price:,.2f}    |
| Exit Price     | ${trade.exit_price:,.2f}     |
| Stop Loss      | ${trade.stop_loss:,.2f}      |
| Take Profit    | ${trade.take_profit:,.2f}    |
| Size           | ${trade.size_usd:.2f}        |
| P&L            | {pnl_sign}${trade.pnl_usd:.4f} ({pnl_sign}{trade.pnl_pct:.2f}%) |
| Duration       | {trade.duration_hours}h      |
| Close Reason   | {trade.close_reason.value}   |
| Order ID       | {trade.order_id or "PAPER"}  |

---

## Conditions at Entry

### ✅ Passed
{entry_list}

### 🚫 Failed
{failed_list}

---

## What Happened

{what_happened}

---

## Strategy Adjustments to Consider

{adjustment_hints}

---

## Notes

{trade.notes or "_No additional notes._"}

---

## TradingView Screenshot

To capture a chart screenshot of this trade, ask Claude:

> Switch TradingView to **{trade.symbol}** on the **{_strategy_timeframe(trade.strategy_name)}** timeframe,
> scroll to **{entry_iso}** (entry time), and take a screenshot.

Or paste this directly:
```
chart_set_symbol: {trade.symbol}
chart_set_timeframe: {_strategy_timeframe(trade.strategy_name)}
chart_scroll_to_date: {entry_iso}
capture_screenshot: chart
```

---
*Generated automatically by the trading bot. Enriched analysis added by Claude when available.*
"""

def _strategy_timeframe(strategy_name: str) -> str:
    """Infer the chart timeframe from the strategy name for TradingView navigation."""
    name = strategy_name.lower()
    if "scalp" in name or "5m" in name:
        return "5m"
    if "supertrend" in name or "1h" in name:
        return "1h"
    if "van de poppe" in name or "4h" in name or "golden" in name:
        return "4h"
    return "1h"   # sensible default


def _describe_outcome(trade: Trade) -> str:
    """Generate a plain-English description of how the trade closed."""
    if trade.close_reason == CloseReason.TAKE_PROFIT:
        return (
            f"Price reached the take profit target of ${trade.take_profit:,.2f}, "
            f"closing the trade with a gain of ${trade.pnl_usd:.4f} "
            f"({trade.pnl_pct:.2f}%) after {trade.duration_hours}h."
        )
    if trade.close_reason == CloseReason.STOP_LOSS:
        return (
            f"Price hit the stop loss at ${trade.stop_loss:,.2f}, "
            f"closing the trade with a loss of ${abs(trade.pnl_usd):.4f} "
            f"({trade.pnl_pct:.2f}%) after {trade.duration_hours}h. "
            f"Price moved against the position from entry ${trade.entry_price:,.2f}."
        )
    if trade.close_reason == CloseReason.BLOCKED:
        return "The signal was generated but one or more safety conditions were not met. No order was placed."
    return f"Trade closed manually after {trade.duration_hours}h."


def _suggest_adjustments(trade: Trade) -> str:
    """Generate basic strategy adjustment hints based on the trade outcome."""
    hints = []

    if trade.close_reason == CloseReason.STOP_LOSS:
        hints.append(
            "- **SL placement**: Price hit the stop quickly — consider whether the entry "
            "was too early (price not close enough to EMA21/50) or if the SL % needs widening."
        )
        hints.append(
            "- **Entry timing**: Was price truly pulling back to the EMA confluence zone, "
            "or was it still extended? Check the 0.6% threshold — may need tightening."
        )
        if trade.duration_hours < 4:
            hints.append(
                "- **Fast SL hit** (under 4h): Could indicate entry against a stronger trend. "
                "Check if EMA200 slope was clearly upward and if market structure showed HH/HL."
            )

    elif trade.close_reason == CloseReason.TAKE_PROFIT:
        hints.append(
            "- **TP extension**: Price hit TP cleanly — consider whether a trailing stop "
            f"or a second TP target at {trade.take_profit * 1.02:,.2f} "
            "could have captured more of the move."
        )
        if trade.duration_hours > 24:
            hints.append(
                "- **Long duration win**: Trade took over 24h — the 4H strategy is working "
                "as intended for swing-style entries."
            )

    if not hints:
        hints.append("- No specific adjustments flagged for this trade outcome.")

    return "\n".join(hints)
