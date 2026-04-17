"""
TradeAnalyst — asks Claude to analyze every closed trade and enrich the journal.

Called by PositionMonitor after a trade closes (win or loss).
Uses the Anthropic Python SDK directly — no CLI subprocess, no browser required.
Works both locally and on Railway (just needs ANTHROPIC_API_KEY env var).

Claude receives the full trade data and the journal file path, reads it,
and appends a structured analysis section with specific improvement suggestions.
"""

import os
import threading

from models.trade import Trade, CloseReason
from utils.logger import log


class TradeAnalyst:

    def __init__(self, working_dir: str):
        self._working_dir = working_dir
        self._api_key     = os.getenv("ANTHROPIC_API_KEY", "")

    def analyze(self, trade: Trade, journal_path: str) -> None:
        """
        Ask Claude to analyze the closed trade and append analysis to the journal.
        Runs in a background thread — the bot loop continues immediately.
        """
        if not self._api_key:
            log.warning("  ANTHROPIC_API_KEY not set — skipping trade analysis.")
            return
        if not os.path.exists(journal_path):
            log.warning(f"  Journal file not found: {journal_path}")
            return

        log.info(f"  Spawning trade analysis thread: {trade.symbol} {trade.close_reason.value}")
        thread = threading.Thread(
            target=self._run_analysis,
            args=(trade, journal_path),
            daemon=True,   # dies with the main process if bot exits
            name=f"analyst-{trade.symbol}-{trade.id[:8]}",
        )
        thread.start()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _run_analysis(self, trade: Trade, journal_path: str) -> None:
        """Blocking Claude call — runs in background thread."""
        try:
            import anthropic  # lazy import — only needed when analysis fires

            client  = anthropic.Anthropic(api_key=self._api_key)
            prompt  = self._build_prompt(trade, journal_path)

            # Read the current journal so Claude sees the trade data it wrote
            try:
                with open(journal_path, "r", encoding="utf-8") as f:
                    journal_content = f.read()
            except OSError:
                journal_content = "(journal file could not be read)"

            full_prompt = f"{prompt}\n\nCURRENT JOURNAL CONTENT:\n```\n{journal_content}\n```"

            message = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=1024,
                messages=[{"role": "user", "content": full_prompt}],
            )
            analysis = message.content[0].text

            # Append the analysis to the journal file
            with open(journal_path, "a", encoding="utf-8") as f:
                f.write("\n\n---\n\n## Claude Analysis\n\n")
                f.write(analysis)
                f.write("\n")

            log.info(f"  Trade analysis written to journal: {os.path.basename(journal_path)}")

        except Exception as e:
            log.warning(f"  Trade analysis failed: {e}")

    def _build_prompt(self, trade: Trade, journal_path: str) -> str:
        outcome    = "WIN" if trade.is_winner else "LOSS"
        pnl_sign   = "+" if trade.pnl_usd >= 0 else ""
        conditions = "\n".join(f"  - {c}" for c in trade.entry_conditions) or "  - N/A"

        return f"""A trade just closed. Analyze it and return ONLY the analysis content — no preamble, no "Here is my analysis", just the sections below.

TRADE DATA:
  Symbol:       {trade.symbol}
  Strategy:     {trade.strategy_name}
  Side:         {trade.side}
  Outcome:      {outcome}
  Entry:        ${trade.entry_price:,.4f}
  Exit:         ${trade.exit_price:,.4f}
  Stop Loss:    ${trade.stop_loss:,.4f}
  Take Profit:  ${trade.take_profit:,.4f}
  P&L:          {pnl_sign}${trade.pnl_usd:.4f} ({pnl_sign}{trade.pnl_pct:.2f}%)
  Duration:     {trade.duration_hours}h
  Close Reason: {trade.close_reason.value}
  Mode:         {"PAPER" if trade.paper_trading else "LIVE"}

CONDITIONS THAT PASSED AT ENTRY:
{conditions}

Write these four sections (use these exact headers):

### What happened
Explain in plain English why this trade won or lost based on the data above.
Was the entry timing good? Did price respect the strategy logic?
If SL hit — was there a sign this would fail? If TP hit — was there more upside?

### What the numbers say
Comment on the specific values: RSI level, ADX, BB position, volume ratio, duration.
Were the conditions borderline or strong? A 34.1 RSI is very different from a 20 RSI.

### What to consider improving
Give 2-3 concrete, specific suggestions. Not generic advice.
Examples:
- "ADX was at 21 — just above the 20 filter. Consider raising threshold to 25 to avoid weak trends."
- "Duration was 0.3h before SL hit — price reversed immediately. Entry may have been mid-candle."
- "TP was hit in 45 minutes — consider a second TP target to capture extended moves."

### Verdict
One sentence: was this a good trade execution that just had bad luck, or was there a signal quality issue?

Keep it honest and specific. If you don't have enough data to say something meaningful, say so."""
