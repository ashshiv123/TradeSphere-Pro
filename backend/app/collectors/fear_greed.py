"""
fear_greed.py — Daily Fear & Greed Index poller (runs every 6h).
"""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.clients.fear_greed import FearGreedClient
from app.collectors.status import record_collector_error, record_collector_success
from app.db.models import FearGreed
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def poll_fear_greed(db: Session, limit: int = 5):
    collector_name = "collector_fear_greed"
    client = FearGreedClient()
    total_written = 0

    try:
        items = client.get_latest(limit=limit)
        if items:
            total_written = upsert_rows(
                db,
                FearGreed,
                [i.model_dump() for i in items],
                conflict_cols=["ts"],
            )
        db.commit()
        record_collector_success(db, collector_name, rows_written=total_written)
        logger.info("Fear & Greed collector completed: %d rows updated", total_written)
    except Exception as exc:
        db.rollback()
        record_collector_error(db, collector_name, error_msg=str(exc))
        logger.error("Fear & Greed collector failed: %s", exc)
    finally:
        client.close()

