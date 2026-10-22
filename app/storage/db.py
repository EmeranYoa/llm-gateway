"""Shared SQLAlchemy base of the database tables."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class of the database tables. Alembic reads its metadata.

    The schema itself is created by the Alembic migrations in `migrations/versions/`.
    """
