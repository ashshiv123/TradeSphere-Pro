"""base.py - DeclarativeBase for SQLAlchemy models."""
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """All ORM models inherit from this base."""
    pass

