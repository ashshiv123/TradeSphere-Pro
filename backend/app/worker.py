"""
worker.py — Background worker process for live collectors and 4h feature jobs.

DATA_PIPELINE_PLAN.md §7:
- APScheduler jobs for REST polling (candles, funding, OI, L/S, news, fear & greed, BTC dominance, macro events).
- Binance WebSocket runner for markPrice and forceOrder real-time streams.
- 4h feature job triggered at candle boundary (00:01, 04:01, 08:01, 12:01, 16:01, 20:01 UTC).
- Publishes features:updated to Redis.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.clients.binance_ws import BinanceWebSocketRunner
from app.collectors.btc_dominance import poll_btc_dominance
from app.collectors.candles import poll_candles
from app.collectors.events import load_scheduled_events
from app.collectors.fear_greed import poll_fear_greed
from app.collectors.funding import poll_funding
from app.collectors.long_short import poll_long_short
from app.collectors.news import poll_news
from app.collectors.open_interest import poll_open_interest
from app.collectors.ws_handler import handle_ws_message
from app.config import get_settings
from app.db.session import SessionLocal
from app.features.pipeline import compute_features_for_candle
from app.logging_setup import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def run_candle_collector():
    logger.info("Executing scheduled candle collector...")
    with SessionLocal() as db:
        poll_candles(db, settings.symbol_list, settings.interval_list)


def run_funding_collector():
    logger.info("Executing scheduled funding collector...")
    with SessionLocal() as db:
        poll_funding(db, settings.symbol_list)


def run_open_interest_collector():
    logger.info("Executing scheduled open interest collector...")
    with SessionLocal() as db:
        poll_open_interest(db, settings.symbol_list, period="4h")


def run_long_short_collector():
    logger.info("Executing scheduled long/short ratio collector...")
    with SessionLocal() as db:
        poll_long_short(db, settings.symbol_list, period="4h")


def run_news_collector():
    logger.info("Executing scheduled news collector...")
    with SessionLocal() as db:
        poll_news(db, limit=30)


def run_fear_greed_collector():
    logger.info("Executing scheduled fear & greed collector...")
    with SessionLocal() as db:
        poll_fear_greed(db, limit=5)


def run_btc_dominance_collector():
    logger.info("Executing scheduled BTC dominance collector...")
    with SessionLocal() as db:
        poll_btc_dominance(db)


def run_events_loader():
    logger.info("Executing scheduled events loader...")
    with SessionLocal() as db:
        load_scheduled_events(db)


def run_feature_pipeline_job():
    """
    4h feature job: runs at candle boundaries + 60s (00:01, 04:01, 08:01, 12:01, 16:01, 20:01 UTC).
    Computes all 13 features for newest closed 4h candle for each configured symbol.
    """
    logger.info(">>> 4H FEATURE JOB TRIGGERED AT CANDLE BOUNDARY <<<")
    with SessionLocal() as db:
        for sym in settings.symbol_list:
            try:
                fv = compute_features_for_candle(db, sym, interval="4h", candle_close_time=None)
                logger.info(
                    "Computed 4h features for %s at %s (close=%.2f, missing=%s)",
                    sym, fv.ts, fv.close, fv.missing
                )
            except Exception as exc:
                logger.warning("Error running feature job for %s: %s", sym, exc)


async def ws_message_dispatcher(msg: dict):
    """Callback for Binance WebSocket runner; processes markPrice and forceOrder."""
    with SessionLocal() as db:
        handle_ws_message(db, msg)


def create_scheduler() -> AsyncIOScheduler:
    """Configure APScheduler with exact intervals and candle boundary cron."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    # REST Collectors
    scheduler.add_job(run_candle_collector, IntervalTrigger(minutes=5), id="job_candles", name="Candles (5m)")
    scheduler.add_job(run_funding_collector, IntervalTrigger(hours=1), id="job_funding", name="Funding (1h)")
    scheduler.add_job(run_open_interest_collector, IntervalTrigger(minutes=30), id="job_oi", name="Open Interest (30m)")
    scheduler.add_job(run_long_short_collector, IntervalTrigger(minutes=30), id="job_ls", name="Long/Short (30m)")
    scheduler.add_job(run_news_collector, IntervalTrigger(minutes=15), id="job_news", name="News (15m)")
    scheduler.add_job(run_fear_greed_collector, IntervalTrigger(hours=6), id="job_fng", name="Fear & Greed (6h)")
    scheduler.add_job(run_btc_dominance_collector, IntervalTrigger(minutes=30), id="job_btcdom", name="BTC Dominance (30m)")
    scheduler.add_job(run_events_loader, IntervalTrigger(hours=6), id="job_events", name="Scheduled Events (6h)")

    # 4H Feature Job: 1 minute past every 4h candle boundary UTC (00:01, 04:01, 08:01, 12:01, 16:01, 20:01)
    scheduler.add_job(
        run_feature_pipeline_job,
        CronTrigger(hour="0,4,8,12,16,20", minute="1", second="0", timezone="UTC"),
        id="job_4h_features",
        name="4H Feature Pipeline (Boundary + 60s)",
    )

    return scheduler


async def main() -> None:
    logger.info("TradeSphere Pro Worker initializing...")
    logger.info("Monitored Symbols: %s | Intervals: %s", settings.symbols, settings.intervals)

    # Run initial startup sync for events and status
    try:
        run_events_loader()
    except Exception as exc:
        logger.warning("Startup events load error: %s", exc)

    # Initialize scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("APScheduler started with %d registered jobs.", len(scheduler.get_jobs()))

    # Initialize WebSocket runner
    ws_runner = BinanceWebSocketRunner(
        symbols=settings.symbol_list,
        on_message_callback=ws_message_dispatcher,
    )
    ws_task = asyncio.create_task(ws_runner.start())

    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Worker received shutdown signal, initiating teardown...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    logger.info("Worker is fully operational. Awaiting jobs...")
    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down scheduler and WebSocket...")
        scheduler.shutdown(wait=False)
        ws_runner.stop()
        ws_task.cancel()
        logger.info("Worker shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
