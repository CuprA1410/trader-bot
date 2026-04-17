"""
dashboard/app.py — Trade Journal Web Dashboard

Reads all trades_SYMBOL.csv files and positions.json and presents
them as a live web dashboard at http://localhost:5050

Run with:
    python dashboard/app.py

No database needed — reads your existing CSV files directly.
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, abort

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

DATA_DIR  = os.path.join(Path(__file__).parent.parent, os.getenv("LOG_DIR", "data"))
SYMBOLS   = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_all_trades() -> list[dict]:
    """Load and merge all trades_SYMBOL.csv files into one list, newest first."""
    trades = []
    for symbol in SYMBOLS:
        path = os.path.join(DATA_DIR, f"trades_{symbol}.csv")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    row["_symbol"] = symbol
                    trades.append(row)
        except Exception:
            continue

    # Sort newest first
    def sort_key(r):
        try:
            return datetime.strptime(f"{r['Date']} {r['Time (UTC)']}", "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.min

    trades.sort(key=sort_key, reverse=True)
    return trades


def load_open_positions() -> list[dict]:
    """Load open positions from positions.json."""
    path = os.path.join(DATA_DIR, "positions.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [p for p in data if p.get("status") == "OPEN"]
    except Exception:
        return []


def load_journal_entries() -> list[dict]:
    """Load all journal markdown files as metadata."""
    journal_dir = os.path.join(DATA_DIR, "journal")
    entries = []
    if not os.path.exists(journal_dir):
        return entries
    for fname in sorted(os.listdir(journal_dir), reverse=True):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(journal_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            entries.append({"filename": fname, "content": content})
        except Exception:
            continue
    return entries


def load_strategy_reviews() -> list[dict]:
    """Load all strategy review markdown files, newest first."""
    review_dir = os.path.join(DATA_DIR, "strategy_reviews")
    reviews = []
    if not os.path.exists(review_dir):
        return reviews
    for fname in sorted(os.listdir(review_dir), reverse=True):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(review_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            reviews.append({"filename": fname, "content": content})
        except Exception:
            continue
    return reviews


# ── Stats calculator ──────────────────────────────────────────────────────────

def calc_stats(trades: list[dict]) -> dict:
    """Calculate summary stats from a list of trade rows."""
    closed = [t for t in trades if t.get("Close Reason") not in ("BLOCKED", "")]
    blocked = [t for t in trades if t.get("Close Reason") == "BLOCKED"]

    wins   = [t for t in closed if _pnl(t) > 0]
    losses = [t for t in closed if _pnl(t) <= 0]

    total_pnl   = sum(_pnl(t) for t in closed)
    win_rate    = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_win     = round(sum(_pnl(t) for t in wins)   / len(wins),   4) if wins   else 0
    avg_loss    = round(sum(_pnl(t) for t in losses) / len(losses), 4) if losses else 0
    best_trade  = max((_pnl(t) for t in closed), default=0)
    worst_trade = min((_pnl(t) for t in closed), default=0)

    # Per-strategy breakdown
    strategies = {}
    for t in closed:
        name = t.get("Strategy") or "Unknown"
        if name not in strategies:
            strategies[name] = {"trades": 0, "wins": 0, "pnl": 0.0}
        strategies[name]["trades"] += 1
        strategies[name]["pnl"]    += _pnl(t)
        if _pnl(t) > 0:
            strategies[name]["wins"] += 1
    for s in strategies.values():
        s["win_rate"] = round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0
        s["pnl"]      = round(s["pnl"], 4)

    # Per-symbol breakdown
    symbols = {}
    for t in closed:
        sym = t.get("Symbol") or t.get("_symbol", "?")
        if sym not in symbols:
            symbols[sym] = {"trades": 0, "wins": 0, "pnl": 0.0}
        symbols[sym]["trades"] += 1
        symbols[sym]["pnl"]    += _pnl(t)
        if _pnl(t) > 0:
            symbols[sym]["wins"] += 1
    for s in symbols.values():
        s["win_rate"] = round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0
        s["pnl"]      = round(s["pnl"], 4)

    return {
        "total_closed":  len(closed),
        "total_blocked": len(blocked),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      win_rate,
        "total_pnl":     round(total_pnl, 4),
        "avg_win":       avg_win,
        "avg_loss":      avg_loss,
        "best_trade":    round(best_trade, 4),
        "worst_trade":   round(worst_trade, 4),
        "by_strategy":   strategies,
        "by_symbol":     symbols,
    }


def _pnl(row: dict) -> float:
    try:
        return float(row.get("PnL USD", 0))
    except (ValueError, TypeError):
        return 0.0


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    all_trades = load_all_trades()
    positions  = load_open_positions()
    journal    = load_journal_entries()
    reviews    = load_strategy_reviews()

    # Filters from query string
    f_symbol   = request.args.get("symbol", "ALL")
    f_strategy = request.args.get("strategy", "ALL")
    f_outcome  = request.args.get("outcome", "ALL")

    filtered = all_trades
    if f_symbol != "ALL":
        filtered = [t for t in filtered if t.get("Symbol") == f_symbol]
    if f_strategy != "ALL":
        filtered = [t for t in filtered if t.get("Strategy") == f_strategy]
    if f_outcome == "WIN":
        filtered = [t for t in filtered if _pnl(t) > 0 and t.get("Close Reason") != "BLOCKED"]
    elif f_outcome == "LOSS":
        filtered = [t for t in filtered if _pnl(t) <= 0 and t.get("Close Reason") != "BLOCKED"]
    elif f_outcome == "BLOCKED":
        filtered = [t for t in filtered if t.get("Close Reason") == "BLOCKED"]

    stats = calc_stats(all_trades)

    # Unique values for filter dropdowns
    all_strategies = sorted({t.get("Strategy", "") for t in all_trades if t.get("Strategy")})
    all_symbols    = sorted({t.get("Symbol", "") for t in all_trades if t.get("Symbol")})

    return render_template(
        "index.html",
        trades=filtered,
        positions=positions,
        journal=journal,
        reviews=reviews,
        stats=stats,
        all_strategies=all_strategies,
        all_symbols=all_symbols,
        f_symbol=f_symbol,
        f_strategy=f_strategy,
        f_outcome=f_outcome,
        now=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )


@app.route("/journal/<filename>")
def journal_entry(filename):
    """Serve a single journal entry as plain text."""
    path = os.path.join(DATA_DIR, "journal", filename)
    if not os.path.exists(path):
        return "Not found", 404
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return f"<pre style='font-family:monospace;padding:2rem;max-width:800px;margin:auto'>{content}</pre>"


@app.route("/review/<filename>")
def strategy_review(filename):
    """Serve a single strategy review as plain text."""
    path = os.path.join(DATA_DIR, "strategy_reviews", filename)
    if not os.path.exists(path):
        return "Not found", 404
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return f"<pre style='font-family:monospace;padding:2rem;max-width:900px;margin:auto;white-space:pre-wrap'>{content}</pre>"


# ── JSON API ──────────────────────────────────────────────────────────────────
# All endpoints are read-only. Useful for external tools, scripts, or just
# pulling data without opening the browser.
# Base URL on Railway: https://your-service.up.railway.app/api/...

@app.route("/api/trades")
def api_trades():
    """
    GET /api/trades
    GET /api/trades?symbol=BTCUSDT
    GET /api/trades?outcome=WIN        (WIN | LOSS | BLOCKED)
    GET /api/trades?strategy=Supertrend+RSI
    Returns all matching trades as JSON, newest first.
    """
    trades = load_all_trades()
    symbol   = request.args.get("symbol")
    outcome  = request.args.get("outcome", "").upper()
    strategy = request.args.get("strategy")

    if symbol:
        trades = [t for t in trades if t.get("Symbol") == symbol]
    if strategy:
        trades = [t for t in trades if strategy.lower() in (t.get("Strategy") or "").lower()]
    if outcome == "WIN":
        trades = [t for t in trades if _pnl(t) > 0 and t.get("Close Reason") != "BLOCKED"]
    elif outcome == "LOSS":
        trades = [t for t in trades if _pnl(t) <= 0 and t.get("Close Reason") not in ("BLOCKED", "")]
    elif outcome == "BLOCKED":
        trades = [t for t in trades if t.get("Close Reason") == "BLOCKED"]

    return jsonify({"count": len(trades), "trades": trades})


@app.route("/api/stats")
def api_stats():
    """
    GET /api/stats
    Returns aggregate performance stats (win rate, P&L, by strategy, by symbol).
    """
    trades = load_all_trades()
    return jsonify(calc_stats(trades))


@app.route("/api/positions")
def api_positions():
    """
    GET /api/positions
    Returns all currently open positions.
    """
    return jsonify(load_open_positions())


@app.route("/api/journal")
def api_journal():
    """
    GET /api/journal
    Returns list of journal entry filenames and their full markdown content.
    """
    entries = load_journal_entries()
    return jsonify({"count": len(entries), "entries": entries})


@app.route("/api/journal/<filename>")
def api_journal_entry(filename):
    """
    GET /api/journal/<filename>
    Returns a single journal entry as { filename, content }.
    """
    path = os.path.join(DATA_DIR, "journal", filename)
    if not os.path.exists(path):
        return jsonify({"error": "not found"}), 404
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"filename": filename, "content": content})


@app.route("/api/reviews")
def api_reviews():
    """
    GET /api/reviews
    Returns list of strategy review files and their full markdown content.
    """
    reviews = load_strategy_reviews()
    return jsonify({"count": len(reviews), "reviews": reviews})


@app.route("/api/reviews/latest")
def api_reviews_latest():
    """
    GET /api/reviews/latest
    Returns just the most recent strategy review.
    """
    reviews = load_strategy_reviews()
    if not reviews:
        return jsonify({"error": "no reviews yet"}), 404
    return jsonify(reviews[0])


if __name__ == "__main__":
    port     = int(os.getenv("PORT", 5050))   # Railway injects PORT automatically
    on_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None
    print(f"Dashboard running at http://localhost:{port}")
    app.run(debug=not on_railway, host="0.0.0.0", port=port)
