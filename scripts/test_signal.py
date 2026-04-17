"""
test_signal.py — tests that the signal prompt reaches Claude correctly.

Builds a fake signal and sends it through the same subprocess path
as the real bot, but tells Claude to just print back what it received
instead of placing any order.

Usage:
    python test_signal.py
"""
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import subprocess
import sys
import os
from services.signal_handler import SignalHandler
from models.signal import Signal, Direction


def main():
    # Fake signal — same structure as a real one
    signal = Signal(
        direction=Direction.LONG,
        symbol="XRPUSDT",
        entry_price=1.41,
        stop_loss=1.407,
        take_profit=1.419,
        timeframe="5m",
        strategy_name="BB + RSI + Stochastic Scalp (BB 20/3.0, RSI 14)",
        passed_conditions=[
            "ADX > 20.0 — market is trending",
            "Price at or below lower Bollinger Band",
            "RSI < 34.0 and turning upward",
            "Stochastic RSI < 20.0 — extreme oversold",
            "Volume above average",
        ],
        failed_conditions=[],
    )

    # Build the prompt exactly as the real bot does
    handler = SignalHandler(working_dir=os.path.dirname(os.path.abspath(__file__)))
    prompt = handler._build_prompt(signal)

    # Replace the place_order command with a harmless echo
    # so Claude confirms it got everything but places nothing
    test_prompt = prompt.replace(
        "4. If the chart confirms the signal, run this command:",
        "4. DO NOT run any commands or place any orders — this is a TEST.",
    ).replace(
        "5. If the chart does NOT confirm, print \"Visual confirmation REJECTED — no trade placed\" and stop.",
        "5. Just print back all the signal details you received so we can verify the prompt arrived correctly.",
    )

    print("=" * 60)
    print("TEST PROMPT BEING SENT TO CLAUDE:")
    print("=" * 60)
    print(test_prompt)
    print("=" * 60)
    print("CLAUDE RESPONSE:")
    print("=" * 60)

    claude_cmd = handler._claude_cmd
    if not claude_cmd:
        print("ERROR: Claude CLI not found")
        sys.exit(1)

    result = subprocess.run(
        [claude_cmd, "-p", "--dangerously-skip-permissions"],
        input=test_prompt,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=False,
        text=True,
        timeout=120,
    )

    print("=" * 60)
    print(f"Exit code: {result.returncode}")


if __name__ == "__main__":
    main()
