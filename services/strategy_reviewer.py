"""
StrategyReviewer — asks Claude to analyze all closed trades and suggest
concrete improvements to strategy parameters.

Called manually via: python review_strategies.py
Not wired into the bot loop — you run it when you want feedback.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from utils.logger import log


class StrategyReviewer:

    def __init__(self, log_dir: str, strategy_dir: str):
        self._log_dir      = log_dir
        self._strategy_dir = strategy_dir
        self._journal_dir  = os.path.join(log_dir, "journal")
        self._review_dir   = os.path.join(log_dir, "strategy_reviews")
        self._api_key      = os.getenv("ANTHROPIC_API_KEY", "")
        os.makedirs(self._review_dir, exist_ok=True)

    # ── Public interface ──────────────────────────────────────────────────────

    def run(self) -> str | None:
        """
        Run a full strategy review synchronously.
        Returns the path to the review file, or None on failure.
        """
        if not self._api_key:
            log.warning("ANTHROPIC_API_KEY not set — cannot run review.")
            return None

        journal_entries = self._load_journal_entries()
        if len(journal_entries) < 3:
            log.info(f"Only {len(journal_entries)} closed trade(s) in journal — need at least 3 for a meaningful review.")
            return None

        wins   = sum(1 for e in journal_entries if e["outcome"] == "WIN")
        losses = sum(1 for e in journal_entries if e["outcome"] == "LOSS")
        log.info(f"Running strategy review on {len(journal_entries)} trades ({wins}W / {losses}L)...")

        return self._run_review(journal_entries)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_journal_entries(self) -> list[dict]:
        """Read all WIN/LOSS journal markdown files. Skip BLOCKED."""
        entries = []
        journal_path = Path(self._journal_dir)
        if not journal_path.exists():
            return entries

        for f in sorted(journal_path.glob("*.md")):
            name = f.stem.upper()
            if "BLOCKED" in name:
                continue
            try:
                content = f.read_text(encoding="utf-8")
                outcome = "WIN" if "WIN" in name else "LOSS" if "LOSS" in name else "UNKNOWN"
                entries.append({"filename": f.name, "outcome": outcome, "content": content})
            except OSError:
                continue
        return entries

    def _load_trade_stats(self) -> str:
        """Aggregate stats from all trade CSVs — win rate, P&L, by strategy."""
        rows = []
        for csv_file in Path(self._log_dir).glob("trades_*.csv"):
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if row.get("Close Reason") in ("TAKE_PROFIT", "STOP_LOSS"):
                            rows.append(row)
            except OSError:
                continue

        if not rows:
            return "No closed WIN/LOSS trades yet."

        total    = len(rows)
        wins     = sum(1 for r in rows if r.get("Close Reason") == "TAKE_PROFIT")
        win_rate = wins / total * 100

        pnls     = []
        for r in rows:
            try:
                pnls.append(float(r.get("PnL USD", 0)))
            except (ValueError, TypeError):
                pass

        total_pnl = sum(pnls)
        avg_pnl   = total_pnl / len(pnls) if pnls else 0

        by_strategy: dict[str, dict] = {}
        for r in rows:
            s = r.get("Strategy", "Unknown")
            if s not in by_strategy:
                by_strategy[s] = {"wins": 0, "losses": 0, "pnl": 0.0}
            if r.get("Close Reason") == "TAKE_PROFIT":
                by_strategy[s]["wins"] += 1
            else:
                by_strategy[s]["losses"] += 1
            try:
                by_strategy[s]["pnl"] += float(r.get("PnL USD", 0))
            except (ValueError, TypeError):
                pass

        lines = [
            f"Total trades: {total}  (wins: {wins}, losses: {total - wins}, win rate: {win_rate:.1f}%)",
            f"Total P&L: ${total_pnl:.2f}  |  Avg per trade: ${avg_pnl:.2f}",
            "",
            "By strategy:",
        ]
        for strat, d in by_strategy.items():
            st = d["wins"] + d["losses"]
            wr = d["wins"] / st * 100 if st else 0
            lines.append(f"  {strat}: {st} trades, {wr:.0f}% win rate, ${d['pnl']:.2f} total P&L")

        return "\n".join(lines)

    def _load_strategy_source(self) -> str:
        """Read all strategy .py files so Claude sees the actual current parameters."""
        parts = []
        for f in sorted(Path(self._strategy_dir).glob("*_strategy.py")):
            if f.name == "base_strategy.py":
                continue
            try:
                source = f.read_text(encoding="utf-8")
                parts.append(f"### {f.name}\n```python\n{source}\n```")
            except OSError:
                continue
        return "\n\n".join(parts)

    def _run_review(self, journal_entries: list[dict]) -> str | None:
        """Call Claude API, write review file, return path."""
        try:
            import anthropic

            client   = anthropic.Anthropic(api_key=self._api_key)
            stats    = self._load_trade_stats()
            strategy_source = self._load_strategy_source()

            wins   = sum(1 for e in journal_entries if e["outcome"] == "WIN")
            losses = sum(1 for e in journal_entries if e["outcome"] == "LOSS")

            # Full content for last 20, filenames only for older entries
            recent = journal_entries[-20:]
            older  = journal_entries[:-20]
            journal_text = ""
            if older:
                journal_text += f"Older entries (filenames only — {len(older)} trades):\n"
                journal_text += "\n".join(f"  - {e['filename']}" for e in older)
                journal_text += "\n\n"
            journal_text += f"Recent {len(recent)} entries (full content):\n\n"
            for entry in recent:
                journal_text += f"---\n**{entry['filename']}**\n{entry['content']}\n\n"

            prompt = f"""You are reviewing a crypto trading bot's performance to suggest concrete strategy improvements.

AGGREGATE STATISTICS:
{stats}

JOURNAL ENTRIES ({wins} wins, {losses} losses):
{journal_text}

CURRENT STRATEGY SOURCE CODE:
{strategy_source}

---

Analyze the trades and write a strategy improvement report. Reference actual numbers from the trades — no generic advice.

Write these sections:

## Performance Summary
2-3 sentences. Is the bot profitable? Which strategy is performing better?

## Pattern Analysis
What patterns appear across the losses? Across the wins?
Look for:
- Losses clustering at specific indicator ranges (e.g. "8 of 11 losses had ADX 20–26")
- Underperforming symbols (e.g. "XRPUSDT: 70% loss rate vs 40% for BTCUSDT")
- Duration patterns (fast SL hits vs slow grind losses)
- Conditions that were technically met but led to losses anyway

## Concrete Parameter Changes
For each suggestion, give the exact current value and proposed new value with data-backed reasoning.
Format:

**[Strategy Name] — [Parameter]**
- Current: `value`
- Proposed: `value`
- Reason: [specific data from the journal that supports this]

Only suggest changes backed by actual trade data.

## What to Watch Next
1-2 things to monitor in the next batch to validate whether the suggested changes help.

## Verdict
One paragraph: is this a tuning problem or a structural problem with the strategy logic?
"""

            log.info("  Calling Claude API...")
            message = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            review_text = message.content[0].text

            ts          = datetime.now().strftime("%Y-%m-%d_%H%M")
            review_path = os.path.join(self._review_dir, f"{ts}_strategy_review.md")
            header = (
                f"# Strategy Review — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                f"_Based on {len(journal_entries)} closed trades ({wins}W / {losses}L)_\n\n"
                f"---\n\n"
            )
            with open(review_path, "w", encoding="utf-8") as f:
                f.write(header + review_text + "\n")

            log.info(f"  Review written → {review_path}")
            return review_path

        except Exception as e:
            log.error(f"Strategy review failed: {e}")
            return None
