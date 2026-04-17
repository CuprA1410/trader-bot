"""
Centralised logger configuration.
All modules import `log` from here — consistent format across Railway logs.
"""

import logging
import sys
import time


def setup_logger(name: str = "trading-bot") -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Already configured — avoid duplicate handlers

    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(
        open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
        if hasattr(sys.stdout, "fileno") else sys.stdout
    )
    handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    formatter.converter = time.gmtime  # force UTC instead of local time
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


log = setup_logger()
