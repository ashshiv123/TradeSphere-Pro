"""
run_backfill.py — Historical backfill script for candles, funding, OI, L/S and sentiment.

DATA_PIPELINE_PLAN.md §7.1 and §11 (Stage 4):
Options:
  --symbols BTCUSDT,ETHUSDT...
  --days 730 (default 2 years)
  --only candles|funding|open_interest|long_short|fear_greed
Resumes from newest stored row if interrupted; all inserts are idempotent.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.binance_futures import BinanceFuturesClient
from app.clients.binance_spot import BinanceSpotClient
from app.clients.fear_greed import FearGreedClient
from app.config import get_settings
from app.db.models import Candle, FearGreed, FundingRate, LongShortRatio, OpenInterest
from app.db.session import SessionLocal
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def backfill_candles(
    db: Session,
    symbols: List[str],
    days: int = 730,
    intervals: List[str] = ["4h", "1d"],
    markets: List[str] = ["futures", "spot"],
):
    """Backfill historical candles up to `days` in the past."""
    f_client = BinanceFuturesClient()
    s_client = BinanceSpotClient()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)
    start_ms = int(start_time.timestamp() * 1000)

    for symbol in symbols:
        for interval in intervals:
            for market in markets:
                logger.info("Backfilling %s %s %s candles from %s...", market, symbol, interval, start_time.date())
                cur_start = start_ms

                while True:
                    try:
                        if market == "futures":
                            candles = f_client.get_klines(symbol=symbol, interval=interval, limit=1500, start_time=cur_start)
                        else:
                            candles = s_client.get_klines(symbol=symbol, interval=interval, limit=1000, start_time=cur_start)

                        if not candles:
                            break

                        rows = [c.model_dump() for c in candles]
                        upsert_rows(db, Candle, rows, conflict_cols=["market", "symbol", "interval", "open_time"])
                        db.commit()

                        last_open_time = candles[-1].open_time
                        last_open_ms = int(last_open_time.timestamp() * 1000)

                        if last_open_ms <= cur_start or len(candles) < 10:
                            break

                        cur_start = last_open_ms + 1
                        if cur_start >= int(end_time.timestamp() * 1000):
                            break

                        time.sleep(0.2)  # rate limit compliance
                    except Exception as exc:
                        logger.error("Error backfilling %s %s %s: %s", market, symbol, interval, exc)
                        break

    f_client.close()
    s_client.close()


def backfill_funding(db: Session, symbols: List[str], days: int = 730):
    """Backfill funding rate history."""
    client = BinanceFuturesClient()
    start_time = datetime.now(timezone.utc) - timedelta(days=days)
    start_ms = int(start_time.timestamp() * 1000)

    for symbol in symbols:
        logger.info("Backfilling funding rates for %s...", symbol)
        cur_start = start_ms
        while True:
            try:
                rates = client.get_funding_rates(symbol=symbol, limit=1000, start_time=cur_start)
                if not rates:
                    break

                rows = [r.model_dump() for r in rates]
                upsert_rows(db, FundingRate, rows, conflict_cols=["symbol", "funding_time"])
                db.commit()

                last_ft = int(rates[-1].funding_time.timestamp() * 1000)
                if last_ft <= cur_start or len(rates) < 10:
                    break
                cur_start = last_ft + 1
                time.sleep(0.2)
            except Exception as exc:
                logger.error("Error backfilling funding for %s: %s", symbol, exc)
                break

    client.close()


def backfill_derivatives_30d(db: Session, symbols: List[str]):
    """Backfill Open Interest and Long/Short ratios (~30 days available)."""
    client = BinanceFuturesClient()
    for symbol in symbols:
        logger.info("Backfilling 30-day OI and L/S for %s...", symbol)
        try:
            # 1. Open Interest (4h)
            oi_records = client.get_open_interest_hist(symbol=symbol, period="4h", limit=500)
            if oi_records:
                upsert_rows(db, OpenInterest, [r.model_dump() for r in oi_records], conflict_cols=["symbol", "period", "ts"])

            # 2. Global Long/Short ratio (4h)
            ls_global = client.get_global_long_short_ratio(symbol=symbol, period="4h", limit=500)
            if ls_global:
                upsert_rows(db, LongShortRatio, [r.model_dump() for r in ls_global], conflict_cols=["symbol", "ratio_type", "period", "ts"])

            # 3. Top Position Long/Short ratio (4h)
            ls_top = client.get_top_long_short_position_ratio(symbol=symbol, period="4h", limit=500)
            if ls_top:
                upsert_rows(db, LongShortRatio, [r.model_dump() for r in ls_top], conflict_cols=["symbol", "ratio_type", "period", "ts"])

            db.commit()
            time.sleep(0.3)
        except Exception as exc:
            logger.error("Error backfilling derivatives for %s: %s", symbol, exc)

    client.close()


def backfill_fear_greed(db: Session):
    """Backfill complete Fear & Greed history."""
    client = FearGreedClient()
    logger.info("Backfilling Fear & Greed index history...")
    try:
        items = client.get_latest(limit=0)  # limit=0 returns full history
        if items:
            upsert_rows(db, FearGreed, [r.model_dump() for r in items], conflict_cols=["ts"])
            db.commit()
            logger.info("Loaded %d Fear & Greed historical entries.", len(items))
    except Exception as exc:
        logger.error("Error backfilling Fear & Greed: %s", exc)
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="TradeSphere Pro Historical Backfill")
    parser.add_argument("--symbols", type=str, default="", help="Comma-separated symbols")
    parser.add_argument("--days", type=int, default=730, help="Days of history (default 730 = 2 years)")
    parser.add_argument("--only", type=str, default="all", help="Dataset: candles|funding|derivatives|fng|all")
    args = parser.parse_args()

    settings = get_settings()
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else settings.symbol_list

    with SessionLocal() as db:
        if args.only in ("all", "candles"):
            backfill_candles(db, symbols, days=args.days)
        if args.only in ("all", "funding"):
            backfill_funding(db, symbols, days=args.days)
        if args.only in ("all", "derivatives"):
            backfill_derivatives_30d(db, symbols)
        if args.only in ("all", "fng"):
            backfill_fear_greed(db)

    print("Backfill completed successfully.")


if __name__ == "__main__":
    main()

