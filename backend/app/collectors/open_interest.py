"""
open_interest.py — Open Interest history poller (fetches limit=30 every 30 min).
"""
from __future__ import annotations

import logging
from typing import List
from sqlalchemy.orm import Session

from app.clients.binance_futures import BinanceFuturesClient
from app.collectors.status import record_collector_error, record_collector_success
from app.db.models import OpenInterest
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def poll_open_interest(db: Session, symbols: List[str], period: str = "4h"):
    collector_name = "collector_open_interest"
    client = BinanceFuturesClient()
    total_written = 0

    try:
        for sym in symbols:
            records = client.get_open_interest_hist(sym, period=period, limit=30)
            if records:
                total_written += upsert_rows(
                    db, OpenInterest, [r.model_dump() for r in records],
                    conflict_cols=["symbol", "period", "ts"]
                )
        db.commit()
        record_collector_success(db, collector_name, rows_written=total_written)
        logger.info("OI collector completed: %d rows updated", total_written)
    except Exception as exc:
        db.rollback()
        record_collector_error(db, collector_name, error_msg=str(exc))
        logger.error("OI collector failed: %s", exc)
    finally:
        client.close()

