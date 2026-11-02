"""
session.py — SQLAlchemy engine and session factory.

Other modules import:
    from app.db.session import engine, get_session, SessionLocal
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# Detect if we're running against SQLite (unit tests) or PostgreSQL (real/Docker).
_is_sqlite = settings.database_url.startswith("sqlite")

# Build engine kwargs - pool_size and max_overflow are Postgres-only.
_engine_kwargs: dict = {"pool_pre_ping": True, "echo": False}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10

engine = create_engine(settings.database_url, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session():
    """
    FastAPI dependency: yield a database session and close it afterwards.

    Usage in a route:
        def my_route(db: Session = Depends(get_session)): ...
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

