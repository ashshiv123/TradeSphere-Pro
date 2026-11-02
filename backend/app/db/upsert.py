"""
upsert.py - Idempotent INSERT ... ON CONFLICT DO UPDATE helper.

An idempotent insert means: run the same insert twice, get one row.
This is critical for our collectors - if a job runs twice (e.g. after a crash),
it must not create duplicate rows.

Usage:
    from app.db.upsert import upsert_row, upsert_rows
    from app.db.models import Candle

    # Single row
    upsert_row(db, Candle, row_dict, conflict_cols=["market","symbol","interval","open_time"])

    # Batch (more efficient for backfill)
    upsert_rows(db, Candle, list_of_dicts, conflict_cols=[...])
"""
from __future__ import annotations

import logging
from typing import Any, Type

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Base

logger = logging.getLogger(__name__)


def _get_update_dict(model: Type[Base], row: dict, conflict_cols: list[str]) -> dict:
    """
    Build the SET clause for ON CONFLICT DO UPDATE.
    We update every column that is NOT part of the primary-key / conflict set.
    This means re-running the same insert refreshes any mutable fields
    (e.g. is_closed becoming True once a candle finalises).
    """
    return {k: v for k, v in row.items() if k not in conflict_cols}


def upsert_row(
    db: Session,
    model: Type[Base],
    row: dict[str, Any],
    conflict_cols: list[str],
) -> None:
    """
    INSERT one row, UPDATE on conflict.

    Args:
        db:            Open SQLAlchemy session.
        model:         ORM model class (e.g. Candle).
        row:           Dict of column_name -> value.
        conflict_cols: Column names that form the unique key to conflict on.
    """
    stmt = pg_insert(model.__table__).values(**row)
    update_dict = _get_update_dict(model, row, conflict_cols)

    if update_dict:
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_cols,
            set_=update_dict,
        )
    else:
        # All columns are conflict columns - nothing to update, just ignore
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)

    db.execute(stmt)


def upsert_rows(
    db: Session,
    model: Type[Base],
    rows: list[dict[str, Any]],
    conflict_cols: list[str],
    batch_size: int = 500,
) -> int:
    """
    Batch-upsert a list of rows.

    Processes in chunks of batch_size to avoid huge single statements.
    Commits nothing - the caller must call db.commit().

    Returns the number of rows processed.
    """
    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        stmt = pg_insert(model.__table__).values(chunk)
        # Build update from first row (all rows have the same keys)
        update_dict = _get_update_dict(model, chunk[0], conflict_cols)

        if update_dict:
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_cols,
                set_=update_dict,
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=conflict_cols)

        db.execute(stmt)
        total += len(chunk)

    logger.debug("upsert_rows: %d rows -> %s", total, model.__tablename__)
    return total


def update_collector_status(
    db: Session,
    name: str,
    *,
    success: bool,
    rows_written: int = 0,
    error_msg: str | None = None,
) -> None:
    """
    Record the outcome of a collector run in collector_status.

    Called by every collector on success OR failure so the /collectors/status
    route always shows up-to-date health information.
    """
    from datetime import datetime, timezone
    from app.db.models import CollectorStatus

    now = datetime.now(timezone.utc)

    if success:
        row = {
            "name": name,
            "last_success_at": now,
            "last_error_at": None,
            "last_error": None,
            # rows_written_total increments; we use a SQL expression for atomicity
        }
        # Upsert the status row
        stmt = pg_insert(CollectorStatus.__table__).values(
            name=name,
            last_success_at=now,
            rows_written_total=rows_written,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["name"],
            set_={
                "last_success_at": now,
                "last_error": None,
                "rows_written_total": CollectorStatus.__table__.c.rows_written_total + rows_written,
            },
        )
    else:
        stmt = pg_insert(CollectorStatus.__table__).values(
            name=name,
            last_error_at=now,
            last_error=error_msg,
            rows_written_total=0,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["name"],
            set_={
                "last_error_at": now,
                "last_error": error_msg,
            },
        )

    db.execute(stmt)
    db.commit()

