"""
market.py — Symbol normalisation and trade-mode utilities.

Single source of truth for converting between raw symbol formats
(BTCUSDT) and ccxt-compatible formats (BTC/USDT or BTC/USDT:USDT).
"""

_KNOWN_QUOTES = ("USDT", "USDC", "BTC", "ETH", "BNB")


def normalise_symbol(symbol: str, trade_mode: str) -> str:
    """
    Return the ccxt symbol for the given trade mode.

    - spot / margin  → BTC/USDT
    - futures / swap → BTC/USDT:USDT  (linear perpetual swap)
    """
    base_quote = _to_slash(symbol)
    if trade_mode.lower() in ("futures", "swap"):
        quote = base_quote.split("/")[1]
        return f"{base_quote}:{quote}"   # e.g. BTC/USDT:USDT
    return base_quote


def _to_slash(symbol: str) -> str:
    """Convert BTCUSDT → BTC/USDT. Pass-through if already contains /."""
    if "/" in symbol:
        # Strip the settlement part if present (BTC/USDT:USDT → BTC/USDT)
        return symbol.split(":")[0]
    for quote in _KNOWN_QUOTES:
        if symbol.endswith(quote):
            return f"{symbol[:-len(quote)]}/{quote}"
    return symbol
