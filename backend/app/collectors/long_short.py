"""
long_short.py — Poller for Binance Futures Long/Short account and position ratios.
"""
from __future__ import annotations

import logging
from typing import List
from sqlalchemy.orm import Session

from app.clients.binance_futures import BinanceFuturesClient
from app.collectors.status import record_collector_error, record_collector_success
from app.db.models import LongShortRatio
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def poll_long_short(db: Session, symbols: List[str], period: str = "4h"):
    collector_name = "collector_long_short"
    client = BinanceFuturesClient()
    total_written = 0

    try:
        for sym in symbols:
            # 1. Global long/short account ratio
            ls_global = client.get_global_long_short_ratio(sym, period=period, limit=30)
            if ls_global:
                total_written += upsert_rows(
                    db,
                    LongShortRatio,
                    [r.model_dump() for r in ls_global],
                    conflict_cols=["symbol", "ratio_type", "period", "ts"],
                )

            # 2. Top trader long/short position ratio
            ls_top = client.get_top_long_short_position_ratio(sym, period=period, limit=30)
            if ls_top:
                total_written += upsert_rows(
                    db,
                    LongShortRatio,
                    [r.model_dump() for r in ls_top],
                    conflict_cols=["symbol", "ratio_type", "period", "ts"],
                )

        db.commit()
        record_collector_success(db, collector_name, rows_written=total_written)
        logger.info("Long/Short collector completed: %d rows updated", total_written)
    except Exception as exc:
        db.rollback()
        record_collector_error(db, collector_name, error_msg=str(exc))
        logger.error("Long/Short collector failed: %s", exc)
    finally:
        client.close()
