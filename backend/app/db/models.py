"""
models.py — SQLAlchemy ORM models for every table in DATA_PIPELINE_PLAN.md §6.

Stage 0: Base and a placeholder (real table models added in Stage 2).
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """All ORM models inherit from this base.

    Alembic reads `Base.metadata` to detect which tables exist and
    which migrations need to be generated.
    """
    pass

# Stage 2 will import and define all table models here.

