"""
funding.py — Funding rate poller (fetches last 20 records every hour).
"""
from __future__ import annotations

import logging
from typing import List
from sqlalchemy.orm import Session

from app.clients.binance_futures import BinanceFuturesClient
from app.collectors.status import record_collector_error, record_collector_success
from app.db.models import FundingRate
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def poll_funding(db: Session, symbols: List[str]):
    collector_name = "collector_funding"
    client = BinanceFuturesClient()
    total_written = 0

    try:
        for sym in symbols:
            rates = client.get_funding_rates(sym, limit=20)
            if rates:
                total_written += upsert_rows(
                    db, FundingRate, [r.model_dump() for r in rates],
                    conflict_cols=["symbol", "funding_time"]
                )
        db.commit()
        record_collector_success(db, collector_name, rows_written=total_written)
        logger.info("Funding collector completed: %d rows updated", total_written)
    except Exception as exc:
        db.rollback()
        record_collector_error(db, collector_name, error_msg=str(exc))
        logger.error("Funding collector failed: %s", exc)
    finally:
        client.close()

