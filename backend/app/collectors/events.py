"""
events.py — Loader for data/scheduled_events.json macro calendar events into database.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session

from app.collectors.status import record_collector_error, record_collector_success
from app.db.models import ScheduledEvent
from app.db.upsert import upsert_rows

logger = logging.getLogger(__name__)


def load_scheduled_events(db: Session, filepath: str = "data/scheduled_events.json"):
    collector_name = "collector_events"
    path = Path(filepath)
    if not path.is_file():
        # Also try relative to project root
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        path = project_root / filepath

    if not path.is_file():
        logger.warning("Scheduled events file %s not found; skipping load.", filepath)
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        rows = []
        for item in data:
            dt_str = item.get("event_time", "")
            if not dt_str:
                continue
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            rows.append({
                "name": item.get("name", "Unknown"),
                "event_time": dt,
                "impact": item.get("impact", "medium"),
            })

        total_written = 0
        if rows:
            total_written = upsert_rows(
                db,
                ScheduledEvent,
                rows,
                conflict_cols=["name", "event_time"],
            )
        db.commit()
        record_collector_success(db, collector_name, rows_written=total_written)
        logger.info("Loaded %d scheduled events.", total_written)
    except Exception as exc:
        db.rollback()
        record_collector_error(db, collector_name, error_msg=str(exc))
        logger.error("Failed to load scheduled events: %s", exc)
