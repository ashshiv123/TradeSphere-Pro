"""
news.py — Poller for crypto news and sentiment (Messari + VADER).
"""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.clients.messari import MessariClient
from app.collectors.status import record_collector_error, record_collector_success
from app.db.models import NewsItem
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def poll_news(db: Session, limit: int = 50):
    collector_name = "collector_news"
    client = MessariClient()
    total_written = 0

    try:
        items = client.get_news(limit=limit)
        if items:
            total_written = upsert_rows(
                db,
                NewsItem,
                [i.model_dump() for i in items],
                conflict_cols=["source", "external_id", "currency"],
            )
        db.commit()
        record_collector_success(db, collector_name, rows_written=total_written)
        logger.info("News collector completed: %d rows updated", total_written)
    except Exception as exc:
        db.rollback()
        record_collector_error(db, collector_name, error_msg=str(exc))
        logger.error("News collector failed: %s", exc)
    finally:
        client.close()
