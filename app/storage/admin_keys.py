"""Admin keys of operators, stored in PostgreSQL.

They open the admin API, never the gateway. They are created and revoked with
the admin CLI only: an operator session in the dashboard can never create more
admin access.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.keys import ADMIN_KEY_PREFIX, display_prefix, generate_key, hash_key
from app.storage.db import Base
from app.storage.tenants import Revocation


class AdminKeyRow(Base):
    """An admin key of an operator. Only the hash of the key is stored."""

    __tablename__ = "admin_keys"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    """Who the key is for, for example the operator's name. Several keys may share it."""
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class AdminIdentity:
    """Who a valid admin key belongs to."""

    admin_key_id: int
    name: str


@dataclass(frozen=True)
class NewAdminKey:
    """An admin key just created. `key` is the only time the full key is available."""

    key: str
    identity: AdminIdentity


@dataclass(frozen=True)
class AdminKeyInfo:
    """What may be shown about an admin key: never the key itself, only its prefix."""

    id: int
    name: str
    prefix: str
    created_at: dt.datetime
    last_used_at: dt.datetime | None
    revoked_at: dt.datetime | None


async def create_admin_key(engine: AsyncEngine, name: str) -> NewAdminKey:
    """Create an admin key for `name`."""
    key = generate_key(ADMIN_KEY_PREFIX)
    async with engine.begin() as connection:
        admin_key_id = await connection.scalar(
            insert(AdminKeyRow)
            .values(
                name=name,
                key_hash=hash_key(key),
                prefix=display_prefix(key),
                created_at=dt.datetime.now(dt.UTC),
            )
            .returning(AdminKeyRow.id)
        )
    assert admin_key_id is not None
    return NewAdminKey(key=key, identity=AdminIdentity(admin_key_id, name))


async def list_admin_keys(engine: AsyncEngine) -> list[AdminKeyInfo]:
    """Return every admin key, oldest first."""
    query = select(
        AdminKeyRow.id,
        AdminKeyRow.name,
        AdminKeyRow.prefix,
        AdminKeyRow.created_at,
        AdminKeyRow.last_used_at,
        AdminKeyRow.revoked_at,
    ).order_by(AdminKeyRow.id)
    async with engine.connect() as connection:
        rows = (await connection.execute(query)).all()
    return [AdminKeyInfo(*row) for row in rows]


async def revoke_admin_key(engine: AsyncEngine, admin_key_id: int) -> Revocation:
    """Revoke an admin key: the admin API refuses it once its key caches expire."""
    async with engine.begin() as connection:
        revoked_id = await connection.scalar(
            update(AdminKeyRow)
            .where(AdminKeyRow.id == admin_key_id, AdminKeyRow.revoked_at.is_(None))
            .values(revoked_at=dt.datetime.now(dt.UTC))
            .returning(AdminKeyRow.id)
        )
        if revoked_id is not None:
            return Revocation.REVOKED
        existing_id = await connection.scalar(
            select(AdminKeyRow.id).where(AdminKeyRow.id == admin_key_id)
        )
    return Revocation.NOT_FOUND if existing_id is None else Revocation.ALREADY_REVOKED


async def find_admin(engine: AsyncEngine, key: str) -> AdminIdentity | None:
    """Return who owns the admin `key`, or None when it is unknown or revoked.

    A valid key is also marked as used now, in the same query (see `find_key_owner`).
    """
    query = (
        update(AdminKeyRow)
        .where(AdminKeyRow.key_hash == hash_key(key), AdminKeyRow.revoked_at.is_(None))
        .values(last_used_at=dt.datetime.now(dt.UTC))
        .returning(AdminKeyRow.id, AdminKeyRow.name)
    )
    async with engine.begin() as connection:
        row = (await connection.execute(query)).first()
    return None if row is None else AdminIdentity(*row)
