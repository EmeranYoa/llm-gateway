"""Tenants and their gateway API keys, stored in PostgreSQL."""

import datetime as dt
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    String,
    Text,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.keys import display_prefix, generate_key, hash_key
from app.storage.db import Base


class TenantRow(Base):
    """A client of the gateway: an application or a customer."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class ApiKeyRow(Base):
    """A gateway API key of a tenant. Only the hash of the key is stored."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class KeyOwner:
    """Who a valid API key belongs to."""

    api_key_id: int
    tenant_id: int
    tenant_name: str


@dataclass(frozen=True)
class NewApiKey:
    """A key just created. `key` is the only time the full key is available."""

    key: str
    owner: KeyOwner


async def create_api_key(engine: AsyncEngine, tenant_name: str) -> NewApiKey:
    """Create a key for `tenant_name`, creating the tenant first if it does not exist."""
    key = generate_key()
    now = dt.datetime.now(dt.UTC)
    async with engine.begin() as connection:
        tenant_id = await connection.scalar(
            select(TenantRow.id).where(TenantRow.name == tenant_name)
        )
        if tenant_id is None:
            tenant_id = await connection.scalar(
                insert(TenantRow).values(name=tenant_name, created_at=now).returning(TenantRow.id)
            )
        api_key_id = await connection.scalar(
            insert(ApiKeyRow)
            .values(
                tenant_id=tenant_id,
                key_hash=hash_key(key),
                prefix=display_prefix(key),
                created_at=now,
            )
            .returning(ApiKeyRow.id)
        )
    assert tenant_id is not None and api_key_id is not None
    return NewApiKey(key=key, owner=KeyOwner(api_key_id, tenant_id, tenant_name))


@dataclass(frozen=True)
class ApiKeyInfo:
    """What an operator may see about a key: never the key itself, only its prefix."""

    id: int
    tenant_name: str
    prefix: str
    created_at: dt.datetime
    last_used_at: dt.datetime | None
    revoked_at: dt.datetime | None


async def list_api_keys(engine: AsyncEngine, tenant_name: str | None = None) -> list[ApiKeyInfo]:
    """Return the keys of every tenant, or of `tenant_name` only, oldest first."""
    query = (
        select(
            ApiKeyRow.id,
            TenantRow.name,
            ApiKeyRow.prefix,
            ApiKeyRow.created_at,
            ApiKeyRow.last_used_at,
            ApiKeyRow.revoked_at,
        )
        .join(TenantRow, ApiKeyRow.tenant_id == TenantRow.id)
        .order_by(ApiKeyRow.id)
    )
    if tenant_name is not None:
        query = query.where(TenantRow.name == tenant_name)
    async with engine.connect() as connection:
        rows = (await connection.execute(query)).all()
    return [ApiKeyInfo(*row) for row in rows]


class Revocation(Enum):
    """Result of a request to revoke a key."""

    REVOKED = "revoked"
    NOT_FOUND = "not_found"
    ALREADY_REVOKED = "already_revoked"


async def revoke_api_key(engine: AsyncEngine, api_key_id: int) -> Revocation:
    """Revoke a key: requests that use it are refused from now on.

    An already revoked key keeps its first revocation date.
    """
    async with engine.begin() as connection:
        revoked_id = await connection.scalar(
            update(ApiKeyRow)
            .where(ApiKeyRow.id == api_key_id, ApiKeyRow.revoked_at.is_(None))
            .values(revoked_at=dt.datetime.now(dt.UTC))
            .returning(ApiKeyRow.id)
        )
        if revoked_id is not None:
            return Revocation.REVOKED
        existing_id = await connection.scalar(
            select(ApiKeyRow.id).where(ApiKeyRow.id == api_key_id)
        )
    return Revocation.NOT_FOUND if existing_id is None else Revocation.ALREADY_REVOKED


async def find_key_owner(engine: AsyncEngine, key: str) -> KeyOwner | None:
    """Return who owns `key`, or None when the key is unknown or revoked."""
    query = (
        select(ApiKeyRow.id, TenantRow.id, TenantRow.name)
        .join(TenantRow, ApiKeyRow.tenant_id == TenantRow.id)
        .where(ApiKeyRow.key_hash == hash_key(key), ApiKeyRow.revoked_at.is_(None))
    )
    async with engine.connect() as connection:
        row = (await connection.execute(query)).first()
    if row is None:
        return None
    api_key_id, tenant_id, tenant_name = row
    return KeyOwner(api_key_id, tenant_id, tenant_name)
