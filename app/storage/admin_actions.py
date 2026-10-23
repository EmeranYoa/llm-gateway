"""History of admin actions: what operators changed, when, and with which admin key.

Every change made with the admin API or the admin CLI is recorded: keys created
or revoked, limits set, cached answers removed. A change to the database writes
its row in the same transaction as the change itself, so the history never
misses a change nor records one that was rolled back. Removing cached answers
acts on Redis, which has no shared transaction with PostgreSQL: its row is
written right after the removal succeeds.

A row never holds a key value, only its short display prefix.
"""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, Text, insert, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.db import Base


class Action(StrEnum):
    """What an operator did."""

    CREATE_KEY = "create-key"
    REVOKE_KEY = "revoke-key"
    SET_LIMITS = "set-limits"
    CLEAR_CACHE = "clear-cache"
    CREATE_ADMIN_KEY = "create-admin-key"
    REVOKE_ADMIN_KEY = "revoke-admin-key"
    PURGE_USAGE_LOG = "purge-usage-log"


class AdminActionRow(Base):
    """One change made by an operator."""

    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    admin_key_id: Mapped[int | None] = mapped_column(ForeignKey("admin_keys.id"))
    """The admin key of the operator; NULL when the action came from the admin CLI."""
    actor: Mapped[str] = mapped_column(Text)
    """The name of that admin key, or `cli`."""
    action: Mapped[str] = mapped_column(String(32))
    target: Mapped[str | None] = mapped_column(Text)
    """Tenant name or key id; NULL when the action concerns every tenant."""
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """What changed, for example the new limits or the number of answers removed."""


@dataclass(frozen=True)
class Actor:
    """Who makes a change: an operator through the admin API, or the admin CLI."""

    name: str
    admin_key_id: int | None = None


CLI = Actor("cli")
"""The admin CLI. It runs on the server with direct database access, so it has no admin key."""


@dataclass(frozen=True)
class AdminActionInfo:
    """A recorded action, as the admin API shows it."""

    id: int
    created_at: dt.datetime
    admin_key_id: int | None
    actor: str
    action: Action
    target: str | None
    details: dict[str, Any]


async def record_action(
    connection: AsyncConnection,
    actor: Actor,
    action: Action,
    target: str | None,
    details: dict[str, Any],
) -> None:
    """Record an action on `connection`, inside the transaction of the change it describes."""
    await connection.execute(
        insert(AdminActionRow).values(
            created_at=dt.datetime.now(dt.UTC),
            admin_key_id=actor.admin_key_id,
            actor=actor.name,
            action=action,
            target=target,
            details=details,
        )
    )


async def record_cache_clear(
    engine: AsyncEngine, actor: Actor, tenant_name: str | None, alias: str | None, removed: int
) -> None:
    """Record the removal of cached answers, after it succeeded.

    `tenant_name` is None when the answers of every tenant were removed.
    """
    async with engine.begin() as connection:
        await record_action(
            connection,
            actor,
            Action.CLEAR_CACHE,
            tenant_name,
            {"alias": alias, "removed": removed},
        )


async def list_actions(
    engine: AsyncEngine, *, limit: int, before: int | None = None
) -> list[AdminActionInfo]:
    """Return up to `limit` actions, newest first, older than the action `before` if given."""
    query = select(
        AdminActionRow.id,
        AdminActionRow.created_at,
        AdminActionRow.admin_key_id,
        AdminActionRow.actor,
        AdminActionRow.action,
        AdminActionRow.target,
        AdminActionRow.details,
    )
    if before is not None:
        query = query.where(AdminActionRow.id < before)
    query = query.order_by(AdminActionRow.id.desc()).limit(limit)
    async with engine.connect() as connection:
        rows = (await connection.execute(query)).all()
    return [
        AdminActionInfo(
            row.id,
            row.created_at,
            row.admin_key_id,
            row.actor,
            Action(row.action),
            row.target,
            row.details,
        )
        for row in rows
    ]
