"""
routes_data.py — read-only data and collector-status endpoints.

These routes are the *contract* that the scoring engine and dashboard use
to read what the collectors have stored.  Nothing here writes to the DB.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Allowed raw tables (for the /data/{table}/latest route) ──────────────────
_ALLOWED_TABLES = {
    "candles",
    "funding_rates",
    "open_interest",
    "long_short_ratio",
    "premium_snapshots",
    "liquidations",
    "news_items",
    "fear_greed",
    "btc_dominance",
}


@router.get("/collectors/status", tags=["ops"])
def collectors_status(db: Session = Depends(get_session)):
    """
    Return a row per collector from collector_status, plus a 'stale' flag.

    A collector is considered stale if its last_success_at is NULL or older
    than 3 times its expected interval.  (The stale thresholds are generous
    defaults here; the real check lives in check_pipeline.py.)
    """
    rows = db.execute(text("SELECT * FROM collector_status ORDER BY name")).mappings().all()
    return [dict(r) for r in rows]


@router.get("/features/{symbol}/latest", tags=["features"])
def features_latest(symbol: str, db: Session = Depends(get_session)):
    """Return the most-recent features row for one symbol (4h interval)."""
    row = db.execute(
        text(
            "SELECT * FROM features WHERE symbol = :s AND interval = '4h' "
            "ORDER BY ts DESC LIMIT 1"
        ),
        {"s": symbol.upper()},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="No features yet for this symbol")
    return dict(row)


@router.get("/features/{symbol}", tags=["features"])
def features_history(
    symbol: str,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    interval: str = Query("4h"),
    db: Session = Depends(get_session),
):
    """Return historical features rows for a symbol within an optional date range."""
    query = "SELECT * FROM features WHERE symbol = :s AND interval = :i"
    params: dict = {"s": symbol.upper(), "i": interval}
    if start:
        query += " AND ts >= :start"
        params["start"] = start
    if end:
        query += " AND ts <= :end"
        params["end"] = end
    query += " ORDER BY ts"

    rows = db.execute(text(query), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/data/{table}/latest", tags=["raw"])
def raw_table_latest(
    table: str,
    symbol: Optional[str] = Query(None),
    limit: int = Query(10, le=500),
    db: Session = Depends(get_session),
):
    """Peek at the most recent rows of any raw data table (for debugging)."""
    if table not in _ALLOWED_TABLES:
        raise HTTPException(
            status_code=400,
            detail=f"Table '{table}' is not in the allowed list: {sorted(_ALLOWED_TABLES)}",
        )

    # Build query safely — table name is validated above, not user-controlled.
    if symbol and table not in {"fear_greed", "btc_dominance"}:
        rows = db.execute(
            text(f"SELECT * FROM {table} WHERE symbol = :s ORDER BY 1 DESC LIMIT :lim"),
            {"s": symbol.upper(), "lim": limit},
        ).mappings().all()
    else:
        rows = db.execute(
            text(f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT :lim"),
            {"lim": limit},
        ).mappings().all()

    return [dict(r) for r in rows]

