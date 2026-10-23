"""Shared SQLAlchemy base of the database tables, and the database engine."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings


class Base(DeclarativeBase):
    """Base class of the database tables. Alembic reads its metadata.

    The schema itself is created by the Alembic migrations in `migrations/versions/`.
    """


def create_database_engine(settings: Settings) -> AsyncEngine:
    """The PostgreSQL engine of the gateway and of the admin API.

    It connects lazily: the application starts even when PostgreSQL is down.
    """
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.database_timeout,
            "command_timeout": settings.database_timeout,
        },
    )
