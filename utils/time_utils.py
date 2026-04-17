"""
Time helpers used across services and repositories.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def utcnow_naive() -> datetime:
    """Return current UTC datetime without tzinfo (for JSON serialisation)."""
    return datetime.utcnow()


def today_utc() -> str:
    """Return today's date string in UTC — used for daily trade counting."""
    return datetime.utcnow().strftime("%Y-%m-%d")


def format_duration(hours: float) -> str:
    """Convert decimal hours to a human-readable string."""
    if hours < 1:
        return f"{int(hours * 60)}m"
    return f"{hours:.1f}h"
