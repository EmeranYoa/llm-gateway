"""Usage log: one PostgreSQL row per target examined for a request.

Rows are written after the response is sent, so logging never adds latency.
The prompt itself is never stored, only its length.
"""

import datetime as dt
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    false,
    insert,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.routing.router import Attempt
from app.storage.db import Base
from app.storage.tenants import KeyOwner

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX_CHARS = 500

REJECTED_TENANT_QUOTA = "rejected_tenant_quota"
"""Outcome of a request refused by its tenant quota, before any target is examined."""


class UsageLogRow(Base):
    """One examined target, or one request refused by its tenant quota.

    Rows of the same request share `request_id`.

    The schema is created by the Alembic migrations in `migrations/versions/`.
    """

    __tablename__ = "usage_log"
    __table_args__ = (
        # Per-tenant reports filter on the tenant and a time range.
        Index("ix_usage_log_tenant_id_created_at", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"))
    """NULL only for rows written before v0.2.0."""
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id"), index=True)
    """NULL only for rows written before v0.2.0."""
    alias: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    """NULL when no provider was examined: the request was refused by a tenant quota."""
    model: Mapped[str | None] = mapped_column(Text)
    attempt_index: Mapped[int]
    outcome: Mapped[str] = mapped_column(String(32))
    status_code: Mapped[int | None]
    latency_ms: Mapped[int | None]
    prompt_chars: Mapped[int]
    estimated_tokens: Mapped[int | None]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    degraded: Mapped[bool] = mapped_column(server_default=false())
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_CHARS))


class UsageLog:
    """Writes the usage rows of each request to PostgreSQL."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write(
        self,
        *,
        request_id: str,
        received_at: dt.datetime,
        owner: KeyOwner,
        alias: str,
        prompt_chars: int,
        attempts: Sequence[Attempt],
    ) -> None:
        """Insert one row per attempt, in a single multi-row INSERT.

        Every row records the tenant and the API key (`owner`) that made the request.

        Nothing is written when no target was examined (unknown alias, streaming refused).
        This runs after the response is sent, so a database error is logged and never
        raised: a usage log outage must not affect clients.
        """
        if not attempts:
            return
        request_columns = _request_columns(request_id, received_at, owner, alias, prompt_chars)
        rows = [
            {
                **request_columns,
                "provider": attempt.target.provider.name,
                "model": attempt.target.model,
                "attempt_index": index,
                "outcome": attempt.outcome,
                "status_code": attempt.status_code,
                "latency_ms": attempt.latency_ms,
                "estimated_tokens": attempt.estimated_tokens,
                "degraded": attempt.degraded,
                "prompt_tokens": attempt.prompt_tokens,
                "completion_tokens": attempt.completion_tokens,
                "error_message": _cut(attempt.error_message),
            }
            for index, attempt in enumerate(attempts)
        ]
        await self._insert(request_id, rows)

    async def write_tenant_rejection(
        self,
        *,
        request_id: str,
        received_at: dt.datetime,
        owner: KeyOwner,
        alias: str,
        prompt_chars: int,
        reason: str,
    ) -> None:
        """Insert the single row of a request refused by its tenant quota.

        No provider was examined, so `provider`, `model` and `latency_ms` stay NULL.
        Like `write`, a database error is logged and never raised.
        """
        row = {
            **_request_columns(request_id, received_at, owner, alias, prompt_chars),
            "attempt_index": 0,
            "outcome": REJECTED_TENANT_QUOTA,
            "status_code": 429,
            "error_message": _cut(reason),
        }
        await self._insert(request_id, [row])

    async def _insert(self, request_id: str, rows: list[dict[str, Any]]) -> None:
        """Insert the rows of one request in a single multi-row INSERT, never raising."""
        try:
            async with self._engine.begin() as connection:
                await connection.execute(insert(UsageLogRow).values(rows))
        except Exception:
            # Rows hold no prompt, so the error details are safe to log.
            logger.exception("could not write the usage log of request %s", request_id)


def _request_columns(
    request_id: str, received_at: dt.datetime, owner: KeyOwner, alias: str, prompt_chars: int
) -> dict[str, Any]:
    """The columns shared by every row of a request."""
    return {
        "request_id": request_id,
        "created_at": received_at,
        "tenant_id": owner.tenant_id,
        "api_key_id": owner.api_key_id,
        "alias": alias,
        "prompt_chars": prompt_chars,
    }


def _cut(message: str | None) -> str | None:
    """Fit the column: details copied from upstream errors (code, param) have no length limit."""
    return None if message is None else message[:ERROR_MESSAGE_MAX_CHARS]
