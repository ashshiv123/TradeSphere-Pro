"""
worker.py — entry point for the collector and feature-job process.

This file is intentionally minimal in Stage 0: it only starts up, logs,
and waits.  Stages 3–5 will add the real jobs.

Run with:   python -m app.worker
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.logging_setup import configure_logging
from app.config import get_settings

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("TradeSphere Pro Worker starting up (stage 0 stub)")
    logger.info("Symbols: %s | Intervals: %s", settings.symbols, settings.intervals)

    # Stage 5 will register APScheduler jobs and WebSocket tasks here.
    # For now, just keep the process alive so Docker shows it is running.
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Worker received shutdown signal, stopping.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals.
            pass

    logger.info("Worker is running. Press Ctrl-C to stop.")
    await stop_event.wait()
    logger.info("Worker shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())

