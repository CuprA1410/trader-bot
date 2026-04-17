"""
review_strategies.py — manually trigger a Claude strategy review.

Reads all closed trade journals, all trade CSVs, and the strategy source
code, then asks Claude for concrete parameter improvement suggestions.

Usage:
  python review_strategies.py

Output:
  Writes a markdown review to data/strategy_reviews/YYYY-MM-DD_HHMM_strategy_review.md
  Also prints the path so you can open it.

Run this whenever you want feedback — after 10 trades, after a bad streak,
or whenever you want to revisit the strategy parameters.
"""
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
import sys

from config import load_config
from services.strategy_reviewer import StrategyReviewer
from utils.logger import log


def main():
    config   = load_config()
    log_dir  = config.trading.log_dir
    strat_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "strategies")

    reviewer = StrategyReviewer(log_dir=log_dir, strategy_dir=strat_dir)
    path     = reviewer.run()

    if path:
        print(f"\n✅ Review saved to: {path}")
        print("   Open it in any markdown viewer, or check the dashboard under Strategy Reviews.")
    else:
        print("\n❌ Review could not be generated. Check logs above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
