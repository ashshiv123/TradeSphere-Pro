"""
routes_health.py — /health endpoint.

Returns the overall status of the API and its dependencies (database and
Redis).  The scoring engine and dashboard use this route to decide whether
the backend is ready.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    """
    Check liveness of the API, the database and Redis.

    Returns HTTP 200 with status "ok" when all dependencies are reachable,
    or HTTP 503 when any dependency is down.
    """
    checks: dict[str, str] = {}
    ok = True

    # ── Database ──────────────────────────────────────────────────────────────
    try:
        from app.db.session import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("Health check — database error: %s", exc)
        checks["database"] = f"error: {exc}"
        ok = False

    # ── Redis ─────────────────────────────────────────────────────────────────
    try:
        import redis as redis_lib
        from app.config import get_settings

        settings = get_settings()
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("Health check — redis error: %s", exc)
        checks["redis"] = f"error: {exc}"
        ok = False

    status_code = 200 if ok else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if ok else "degraded", "checks": checks},
    )

