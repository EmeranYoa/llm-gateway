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
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.keys import display_prefix, generate_key, hash_key
from app.config import TenantLimits
from app.storage.db import Base


class TenantRow(Base):
    """A client of the gateway: an application or a customer."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    rpm: Mapped[int | None]
    """Requests per minute of the tenant, or NULL to use the default of `gateway.yaml`."""
    tokens_per_day: Mapped[int | None] = mapped_column(BigInteger)
    """Daily token budget of the tenant, or NULL to use the default of `gateway.yaml`."""
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
    """Who a valid API key belongs to, with the tenant's limits.

    Each gateway instance caches it for `AUTH_CACHE_TTL` seconds, so a revoked key
    or a limit changed by the admin CLI takes effect within that time.
    """

    api_key_id: int
    tenant_id: int
    tenant_name: str
    limits: TenantLimits
    """The tenant's own limits. A missing limit means "use the default of `gateway.yaml`"."""


@dataclass(frozen=True)
class NewApiKey:
    """A key just created. `key` is the only time the full key is available."""

    key: str
    owner: KeyOwner


async def create_api_key(
    engine: AsyncEngine,
    tenant_name: str,
    *,
    rpm: int | None = None,
    tokens_per_day: int | None = None,
) -> NewApiKey:
    """Create a key for `tenant_name`, creating the tenant first if it does not exist.

    `rpm` and `tokens_per_day`, when given, become the tenant's own limits.
    """
    key = generate_key()
    now = dt.datetime.now(dt.UTC)
    # Insert the tenant, or, if it exists already, update only the limits given.
    new_tenant = postgresql.insert(TenantRow).values(
        name=tenant_name, rpm=rpm, tokens_per_day=tokens_per_day, created_at=now
    )
    upsert_tenant = new_tenant.on_conflict_do_update(
        index_elements=[TenantRow.name],
        set_={
            "rpm": func.coalesce(new_tenant.excluded.rpm, TenantRow.rpm),
            "tokens_per_day": func.coalesce(
                new_tenant.excluded.tokens_per_day, TenantRow.tokens_per_day
            ),
        },
    ).returning(TenantRow.id, TenantRow.rpm, TenantRow.tokens_per_day)
    async with engine.begin() as connection:
        tenant_id, own_rpm, own_tokens_per_day = (await connection.execute(upsert_tenant)).one()
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
    assert api_key_id is not None
    limits = TenantLimits(rpm=own_rpm, tokens_per_day=own_tokens_per_day)
    owner = KeyOwner(api_key_id, tenant_id, tenant_name, limits)
    return NewApiKey(key=key, owner=owner)


async def set_tenant_limits(
    engine: AsyncEngine,
    tenant_name: str,
    *,
    rpm: int | None = None,
    tokens_per_day: int | None = None,
) -> bool:
    """Set the tenant's own limits. Returns False for an unknown tenant.

    Only the limits given are changed; at least one must be given. Gateways see
    the new limits when their key cache expires (`AUTH_CACHE_TTL`).
    """
    new_limits = {
        column: value
        for column, value in {"rpm": rpm, "tokens_per_day": tokens_per_day}.items()
        if value is not None
    }
    if not new_limits:
        raise ValueError("no limit to set")
    statement = (
        update(TenantRow)
        .where(TenantRow.name == tenant_name)
        .values(**new_limits)
        .returning(TenantRow.id)
    )
    async with engine.begin() as connection:
        tenant_id = await connection.scalar(statement)
    return tenant_id is not None


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
    """Revoke a key: requests that use it are refused once gateways' key caches expire.

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
    """Return who owns `key`, or None when the key is unknown or revoked.

    A valid key is also marked as used now (`last_used_at`), in the same query.
    The gateway calls this only when its verification cache is out of date, so
    `last_used_at` is written about once per cache TTL, not on every request.
    """
    query = (
        update(ApiKeyRow)
        .where(
            ApiKeyRow.tenant_id == TenantRow.id,
            ApiKeyRow.key_hash == hash_key(key),
            ApiKeyRow.revoked_at.is_(None),
        )
        .values(last_used_at=dt.datetime.now(dt.UTC))
        .returning(
            ApiKeyRow.id, TenantRow.id, TenantRow.name, TenantRow.rpm, TenantRow.tokens_per_day
        )
    )
    async with engine.begin() as connection:
        row = (await connection.execute(query)).first()
    if row is None:
        return None
    api_key_id, tenant_id, tenant_name, rpm, tokens_per_day = row
    limits = TenantLimits(rpm=rpm, tokens_per_day=tokens_per_day)
    return KeyOwner(api_key_id, tenant_id, tenant_name, limits)
