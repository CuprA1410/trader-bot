# Claude Trading Bot v2 — Python Architecture

Automated trading bot that monitors 4 crypto pairs across multiple strategies simultaneously.
Python calculates all indicators — Claude is only invoked to take a screenshot and analyze closed trades.

---

## How It Works

Every 5 minutes the bot:

1. **Checks open positions** — if SL or TP was hit, closes the position, writes to CSV, and asks Claude to analyze the trade and enrich the journal
2. **Fetches candles from Binance** (free public API, no auth needed)
3. **Runs all active strategies** across all 4 symbols
4. **No signal** → logs BLOCKED to that symbol's CSV. Claude is never called.
5. **Signal detected** → `place_order.py` runs immediately (no Claude delay), then Claude takes a screenshot for the journal

Visual confirmation was removed — Python already validated all conditions against real Binance data. TradingView is just a visual of the same numbers.

---

## Strategies

Multiple strategies run simultaneously. Configure in `.env`:

```
STRATEGIES=supertrend_rsi,bb_rsi_scalp
```

Each strategy runs independently per symbol. Only one position per symbol is allowed at a time — the first strategy that fires wins. Each strategy owns its own timeframe, SL, and TP — no need to set these in `.env`.

---

### BB + RSI + Stochastic Scalp *(5m, high-frequency)*

| Parameter | Value |
|-----------|-------|
| Timeframe | 5m |
| Bollinger Bands | 20-period, 3 std devs |
| RSI | Period 14, oversold < 34 (must be turning up) |
| Stochastic RSI | Period 14, oversold < 20 |
| ADX filter | > 20 (skip ranging/choppy markets) |
| Volume filter | Above 20-period average |
| Stop loss | 0.25% below entry |
| Take profit | 0.60% above entry (~2.4:1 R:R after fees) |

Mean-reversion: buy when price touches the lower Bollinger Band with RSI + Stochastic confirming oversold. Target the middle band. Generates 10–20 signals/day per coin.

Fee math: 0.20% round-trip, 0.22% break-even, 0.60% target → ~0.40% net per trade.

---

### Supertrend + RSI *(1H, intraday)*

| Parameter | Value |
|-----------|-------|
| Timeframe | 1H |
| Supertrend | ATR 10, Multiplier 3.0 |
| RSI | Period 14, range 50–70 |
| Volume filter | > 1.5× 20-period average |
| EMA bias | Price above EMA(200) |
| Stop loss | 1.5× ATR below entry |
| Take profit | 3.0× ATR above entry (2:1 R:R) |

Generates 2–5 signals per day per coin.

---

### Van de Poppe — Golden Pocket *(4H, swing trading)*

| Parameter | Value |
|-----------|-------|
| Timeframe | 4H |
| Condition 1 | Price above EMA(21) AND EMA(50) |
| Condition 2 | Price above EMA(200) — macro bull only |
| Condition 3 | Price within 0.6% of EMA21/50 — pullback zone |
| Condition 4 | RSI(14) between 40–65 |
| Stop loss | 2% below entry |
| Take profit | 4% above entry (2:1 R:R) |

Generates 1–2 signals per week.

---

## Project Structure

```
main.py                          ← entry point + loop runner
config.py                        ← all env vars in typed frozen dataclasses
requirements.txt                 ← ccxt, pandas, numpy, ta, python-dotenv, flask
place_order.py                   ← places a trade directly (price staleness check included)
check_positions.py               ← CLI — checks SL/TP on all open positions
test_signal.py                   ← sends a fake signal through the full pipeline for testing
│
├── models/
│   ├── signal.py                ← strategy output (direction, SL, TP, timeframe, strategy_name)
│   ├── position.py              ← open trade (includes sl_order_id, tp_order_id for OCO)
│   └── trade.py                 ← closed trade with full P&L
│
├── strategies/                  ← Strategy Pattern — each owns its timeframe, SL, TP
│   ├── base_strategy.py         ← abstract interface (name, timeframe, analyze)
│   ├── bb_rsi_scalp_strategy.py    ← BB + RSI + Stochastic, 5m
│   ├── supertrend_rsi_strategy.py  ← Supertrend + RSI, 1H
│   └── van_de_poppe_strategy.py    ← Van de Poppe, 4H
│
├── factories/
│   └── exchange_factory.py      ← creates ccxt BitGet + Binance instances
│
├── repositories/
│   ├── trade_repository.py      ← data/trades_BTCUSDT.csv etc. (per-symbol)
│   ├── position_repository.py   ← data/positions.json (survives restarts)
│   └── journal_repository.py    ← data/journal/DATE_SYMBOL_WIN|LOSS.md
│
├── services/
│   ├── market_data_service.py   ← fetches OHLCV from Binance via ccxt
│   ├── position_monitor.py      ← checks SL/TP each run, closes + journals
│   ├── signal_handler.py        ← places order directly + asks Claude for screenshot
│   ├── trade_analyst.py         ← Claude analyzes closed trades, enriches journal
│   └── trading_service.py       ← orchestrates full cycle across all symbols + strategies
│
├── utils/
│   ├── logger.py                ← shared logger (UTC timestamps)
│   └── time_utils.py            ← UTC helpers
│
├── dashboard/                   ← trade journal web dashboard
│   ├── app.py                   ← Flask app — run with: python dashboard/app.py
│   └── templates/index.html     ← dashboard UI
│
└── data/
    ├── trades_BTCUSDT.csv       ← closed trades + blocked signals per symbol
    ├── trades_ETHUSDT.csv
    ├── trades_SOLUSDT.csv
    ├── trades_XRPUSDT.csv
    ├── positions.json           ← open positions (sl_order_id + tp_order_id stored)
    ├── journal/                 ← one .md per closed trade, enriched by Claude
    └── screenshots/             ← chart screenshots taken at signal time
```

---

## Getting Started

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure `.env`

```
BITGET_API_KEY=your_key
BITGET_SECRET_KEY=your_secret
BITGET_PASSPHRASE=your_passphrase
BITGET_BASE_URL=https://api.bitget.com
TRADE_MODE=spot

STRATEGIES=supertrend_rsi,bb_rsi_scalp
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT

PORTFOLIO_VALUE_USD=1000
MAX_TRADE_SIZE_USD=20
MAX_TRADES_PER_DAY=50
PAPER_TRADING=true
LOOP_INTERVAL_SECONDS=300
LOG_DIR=data
```

### 3. Log in to Claude CLI (one time only)

```bash
claude /login
```

### 4. Run

```bash
# Loop forever (Ctrl+C to stop)
python main.py

# Single test run
python main.py --once

# Test signal pipeline without placing a trade
python test_signal.py
```

### 5. Open the dashboard

```bash
python dashboard/app.py
```

Then open **http://localhost:5050** in your browser.

---

## Signal Flow

```
Every 5 minutes:
  ├── position_monitor.check_all()
  │     └── SL or TP hit?
  │           ├── close position
  │           ├── write to trades_SYMBOL.csv
  │           ├── write journal entry (entry/exit data)
  │           └── Claude analyzes trade → appends analysis to journal
  │
  └── for each symbol × strategy:
        ├── fetch candles (at strategy's timeframe)
        ├── run strategy indicators
        ├── all conditions pass? → SIGNAL
        │     ├── place_order.py runs immediately
        │     │     └── price staleness check (reject if moved > 0.5%)
        │     └── Claude takes screenshot → saved to data/screenshots/
        └── conditions fail? → BLOCKED → logged to CSV (zero Claude tokens)
```

---

## Order Execution (Live Mode)

When `PAPER_TRADING=false`, every trade places three things on BitGet:

1. **Entry** — market order (fills immediately)
2. **OCO** — One Cancels the Other order containing both:
   - Take profit limit order at TP price
   - Stop loss stop-market order at SL price

When one of the OCO legs fills, BitGet automatically cancels the other. The exchange manages SL/TP 24/7 — the bot doesn't need to be running.

---

## Trade Journal

Every closed position generates a markdown file:

```
data/journal/2026-04-16_1430_XRPUSDT_LONG_WIN.md
```

The file contains:
- Entry/exit prices, P&L, duration, conditions at entry
- **Claude Analysis** section appended automatically:
  - What happened and why
  - What the indicator values say
  - Specific improvement suggestions for the strategy
  - Overall verdict

---

## Dashboard

Run `python dashboard/app.py` and open **http://localhost:5050**.

Shows:
- Summary cards: total trades, win rate, total P&L, best/worst trade
- Breakdown by strategy and by symbol
- Full trade log with filters (symbol, strategy, outcome)
- Open positions
- Journal file list with one-click view

Reads CSV files and `positions.json` directly — no database, no sync needed.

---

## Adding a New Strategy

1. Create `strategies/my_strategy.py` — subclass `BaseStrategy`
2. Implement `name`, `timeframe`, and `analyze()` — return a `Signal`
3. Set SL/TP inside the strategy (not in `.env`)
4. Register in `main.py` `_build_strategies()` dict
5. Add to `STRATEGIES=...,my_strategy` in `.env`

No other file needs to change.

---

## Running Multiple Strategies

```
# Run all three simultaneously
STRATEGIES=supertrend_rsi,bb_rsi_scalp,van_de_poppe

# Scalper only
STRATEGIES=bb_rsi_scalp

# Single strategy (old format still works)
STRATEGY=supertrend_rsi
```

Loop interval should match the shortest active timeframe:
- BB Scalp only → `LOOP_INTERVAL_SECONDS=300` (5 min)
- Supertrend only → `LOOP_INTERVAL_SECONDS=3600` (1 hour)
- Both running → `LOOP_INTERVAL_SECONDS=300`

---

## Going Live

1. Set `PAPER_TRADING=false` in `.env`
2. Ensure BitGet API key has **spot trading** enabled
3. Ensure **withdrawals are OFF** on the API key
4. Run `python main.py --once` first to verify one clean cycle

---

**Not financial advice. Paper trade before going live. Never risk more than you can afford to lose.**
