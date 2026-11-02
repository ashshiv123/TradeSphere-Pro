"""
btc_dominance.py — CoinGecko BTC dominance poller (runs every 30m).
"""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.clients.coingecko import CoinGeckoClient
from app.collectors.status import record_collector_error, record_collector_success
from app.db.models import BtcDominance
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def poll_btc_dominance(db: Session):
    collector_name = "collector_btc_dominance"
    client = CoinGeckoClient()
    total_written = 0

    try:
        dom = client.get_btc_dominance()
        if dom:
            total_written = upsert_rows(
                db,
                BtcDominance,
                [dom.model_dump()],
                conflict_cols=["ts"],
            )
        db.commit()
        record_collector_success(db, collector_name, rows_written=total_written)
        logger.info("BTC dominance collector completed: %d rows updated", total_written)
    except Exception as exc:
        db.rollback()
        record_collector_error(db, collector_name, error_msg=str(exc))
        logger.error("BTC dominance collector failed: %s", exc)
    finally:
        client.close()
