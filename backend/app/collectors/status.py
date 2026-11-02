"""
status.py — Collector status and health tracking helpers.
"""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session
from app.db.upsert import update_collector_status

logger = logging.getLogger(__name__)


def record_collector_success(db: Session, name: str, rows_written: int = 0):
    try:
        update_collector_status(db, name, success=True, rows_written=rows_written)
    except Exception as exc:
        logger.warning("Failed to update status for %s: %s", name, exc)


def record_collector_error(db: Session, name: str, error_msg: str):
    try:
        update_collector_status(db, name, success=False, error_msg=error_msg)
    except Exception as exc:
        logger.warning("Failed to record error for %s: %s", name, exc)

