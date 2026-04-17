"""
SignalHandler — executes a validated signal.

When a signal fires, this service:
  1. Runs place_order.py directly (no Claude delay — order placed immediately)
  2. Asks Claude to switch TradingView to the signal chart and take a screenshot
     for the journal (purely for record-keeping, not confirmation)

Visual confirmation was removed — Python already validated all conditions
against real Binance data. TradingView is just a visual of the same numbers.
"""

import os
import subprocess
import sys
from pathlib import Path

from models.signal import Signal
from utils.logger import log


class SignalHandler:

    def __init__(self, working_dir: str):
        self._working_dir = working_dir
        self._claude_cmd  = self._find_claude()
        self._python_cmd  = sys.executable   # same Python that's running the bot

    def execute(self, signal: Signal) -> bool:
        """
        Execute a validated signal:
          1. Place the order immediately via place_order.py
          2. Ask Claude to take a screenshot for the journal
        Returns True if the order was placed successfully.
        """
        order_placed = self._place_order(signal)

        if order_placed:
            self._take_screenshot(signal)

        return order_placed

    # ── Private helpers ───────────────────────────────────────────────────────

    def _place_order(self, signal: Signal) -> bool:
        """Run place_order.py directly — no Claude involved, no delay."""
        import json as _json

        args = self._build_order_args(signal)
        cmd  = [self._python_cmd, "scripts/place_order.py"] + args

        log.info(f"  Placing order: {signal.direction.value} {signal.symbol} @ ${signal.entry_price:,.4f}")
        try:
            result = subprocess.run(
                cmd,
                cwd=self._working_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Echo stdout so it appears in logs
            if result.stdout:
                for line in result.stdout.strip().splitlines():
                    log.info(f"    {line}")
            if result.stderr:
                for line in result.stderr.strip().splitlines():
                    log.warning(f"    {line}")

            if result.returncode != 0:
                log.warning(f"  place_order.py exited with code {result.returncode}")
                return False

            # Parse the JSON result printed by place_order.py.
            # stdout may contain log lines mixed with a multi-line JSON block —
            # find the last top-level { ... } by scanning for balanced braces.
            try:
                text = result.stdout
                last_start = text.rfind("\n{")
                last_start = last_start + 1 if last_start != -1 else text.find("{")
                depth, end = 0, -1
                for idx, ch in enumerate(text[last_start:], start=last_start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = idx + 1
                            break
                json_str = text[last_start:end] if end != -1 else text
                data = _json.loads(json_str)
                if not data.get("ok", False):
                    reason = data.get("reason", data.get("error", "unknown"))
                    log.warning(f"  Order rejected: {reason} — {data.get('message', '')}")
                    return False
                log.info(
                    f"  Order placed ✅  id={data.get('order_id', '?')} | "
                    f"mode={data.get('mode', '?')} | "
                    f"R:R={data.get('rr_ratio', 0):.2f}"
                )
                return True
            except _json.JSONDecodeError:
                # place_order.py printed something but not valid JSON — treat as failure
                log.warning("  place_order.py returned non-JSON output — order status unknown")
                return False

        except subprocess.TimeoutExpired:
            log.error("  place_order.py timed out after 30s")
            return False
        except Exception as e:
            log.error(f"  Failed to run place_order.py: {e}")
            return False

    def _take_screenshot(self, signal: Signal) -> None:
        """Ask Claude to switch TradingView to the signal chart and screenshot it."""
        if not self._claude_cmd:
            log.warning("  Claude CLI not found — skipping screenshot.")
            return

        screenshot_path = (
            f"data/screenshots/"
            f"{signal.symbol}_{signal.direction.value}_{int(signal.entry_price)}.png"
        )

        prompt = f"""Switch TradingView to {signal.symbol} on the {signal.timeframe} timeframe and take a chart screenshot for the trade journal.

Steps:
1. Switch chart to {signal.symbol} on {signal.timeframe} timeframe
2. Take a screenshot using capture_screenshot with region="chart"
3. Save it as: {screenshot_path}
4. Print "Screenshot saved: {screenshot_path}"

Do not analyse anything. Just switch and screenshot.
"""
        try:
            subprocess.run(
                [self._claude_cmd, "-p", "--dangerously-skip-permissions"],
                input=prompt,
                cwd=self._working_dir,
                capture_output=False,
                text=True,
                timeout=60,
            )
        except Exception as e:
            log.warning(f"  Screenshot failed: {e}")

    @staticmethod
    def _build_order_args(signal: Signal) -> list[str]:
        """Build place_order.py args as a proper list — no shell escaping needed."""
        args = [
            "--symbol",    signal.symbol,
            "--side",      signal.direction.value,
            "--entry",     str(signal.entry_price),
            "--sl",        str(signal.stop_loss),
            "--tp",        str(signal.take_profit),
            "--strategy",  signal.strategy_name,
        ]
        # nargs="+" in place_order.py expects all values after one --conditions flag
        if signal.passed_conditions:
            args += ["--conditions"] + list(signal.passed_conditions)
        return args

    @staticmethod
    def _find_claude() -> str | None:
        """Find the Claude CLI executable on this system."""
        candidates = [
            "claude",
            "claude.cmd",
            os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
            os.path.expandvars(r"%APPDATA%\npm\claude"),
            "/usr/local/bin/claude",
            "/opt/homebrew/bin/claude",
        ]
        for cmd in candidates:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    log.info(f"  Claude CLI found: {cmd}")
                    return cmd
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue

        log.warning("  Claude CLI not found — screenshots disabled.")
        return None
