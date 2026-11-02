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

# Create the engine once at import time.
# pool_pre_ping=True: test the connection before using it (handles DB restarts).
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,  # set True to log every SQL statement (noisy, dev only)
)

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

