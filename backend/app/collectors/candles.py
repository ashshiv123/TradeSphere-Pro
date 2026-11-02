"""
candles.py — Live candle poller (fetches last 3 candles for futures & spot every 5 min).
"""
from __future__ import annotations

import logging
from typing import List
from sqlalchemy.orm import Session

from app.clients.binance_futures import BinanceFuturesClient
from app.clients.binance_spot import BinanceSpotClient
from app.collectors.status import record_collector_error, record_collector_success
from app.db.models import Candle
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def poll_candles(db: Session, symbols: List[str], intervals: List[str] = ["4h", "1d"]):
    """Poll newest candles for all active symbols and intervals."""
    collector_name = "collector_candles"
    f_client = BinanceFuturesClient()
    s_client = BinanceSpotClient()
    total_written = 0

    try:
        for sym in symbols:
            for interval in intervals:
                # 1. Futures candles
                f_candles = f_client.get_klines(sym, interval=interval, limit=3)
                if f_candles:
                    total_written += upsert_rows(
                        db, Candle, [c.model_dump() for c in f_candles],
                        conflict_cols=["market", "symbol", "interval", "open_time"]
                    )

                # 2. Spot candles
                s_candles = s_client.get_klines(sym, interval=interval, limit=3)
                if s_candles:
                    total_written += upsert_rows(
                        db, Candle, [c.model_dump() for c in s_candles],
                        conflict_cols=["market", "symbol", "interval", "open_time"]
                    )

        db.commit()
        record_collector_success(db, collector_name, rows_written=total_written)
        logger.info("Candle collector completed: %d rows updated", total_written)
    except Exception as exc:
        db.rollback()
        record_collector_error(db, collector_name, error_msg=str(exc))
        logger.error("Candle collector failed: %s", exc)
    finally:
        f_client.close()
        s_client.close()
