"""
logging_setup.py — configure structured logging for the whole application.

Call configure_logging() once at startup (in main.py and worker.py).
After that, every module just does:

    import logging
    logger = logging.getLogger(__name__)
"""
from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Set up root logger to write structured lines to stdout.

    Format: ISO timestamp | level | logger name | message
    Everything goes to stdout so Docker can capture it with
    `docker compose logs`.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%SZ"

    logging.basicConfig(
        level=numeric_level,
        format=fmt,
        datefmt=datefmt,
        stream=sys.stdout,
        force=True,   # override any earlier basicConfig call
    )

    # Quieten noisy third-party loggers
    for noisy in ("httpx", "httpcore", "uvicorn.access", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

