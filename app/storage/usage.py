"""Usage log: one PostgreSQL row per target examined for a request.

Rows are written after the response is sent, so logging never adds latency.
The prompt itself is never stored, only its length.

Costs are in USD, computed when a row is written from the real token usage and
the model price in `gateway.yaml` (USD per million tokens).
"""

import datetime as dt
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    false,
    insert,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.cache.store import CachedAnswer
from app.config import ModelPrice
from app.routing.router import Attempt
from app.storage.db import Base
from app.storage.tenants import KeyOwner

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX_CHARS = 500

REJECTED_TENANT_QUOTA = "rejected_tenant_quota"
"""Outcome of a request refused by its tenant quota, before any target is examined."""

CACHE_HIT = "cache_hit"
"""Outcome of a request answered from the response cache, without calling any target."""


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
    """Total duration of the attempt. For a stream, until its last chunk."""
    first_token_ms: Mapped[int | None]
    """Time to the first content of a streamed answer. NULL for any other row."""
    prompt_chars: Mapped[int]
    estimated_tokens: Mapped[int | None]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    degraded: Mapped[bool] = mapped_column(server_default=false())
    stream: Mapped[bool] = mapped_column(server_default=false())
    """True for every row of a request sent with `stream: true`."""
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_CHARS))
    cache: Mapped[str | None] = mapped_column(String(16))
    """`hit`, `miss`, `bypass` or `unavailable` when the alias uses the cache, else NULL."""
    cache_similarity: Mapped[float | None] = mapped_column(Float)
    """For a cache hit: 1.0 for an identical request, else the similarity of the questions."""
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    """What the row cost. 0 for a cache hit; NULL when the model has no price or no
    token counts are known (skipped targets, failed attempts, tenant quota refusals)."""
    saved_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    """For a cache hit: what the answer would cost from its original model. Else NULL."""


@dataclass(frozen=True)
class LoggedRequest:
    """What every usage row of a request records about the request itself."""

    request_id: str
    received_at: dt.datetime
    owner: KeyOwner
    """The tenant and the API key that made the request."""
    alias: str
    prompt_chars: int
    stream: bool
    """True when the client asked for a streamed answer."""


class UsageLog:
    """Writes the usage rows of each request to PostgreSQL."""

    def __init__(
        self, engine: AsyncEngine, prices: Mapping[tuple[str, str], ModelPrice] | None = None
    ) -> None:
        """`prices` holds the price of each model by (provider, model). It prices the
        answers of cache hits; attempts are priced by their target."""
        self._engine = engine
        self._prices = prices or {}

    async def write(
        self, request: LoggedRequest, attempts: Sequence[Attempt], *, cache: str | None = None
    ) -> None:
        """Insert one row per attempt, in a single multi-row INSERT.

        Every row records the `request` and what the response cache did (`cache`:
        NULL when the alias does not use it).

        Nothing is written when no target was examined (unknown alias, streaming refused).
        This runs after the response is sent, so a database error is logged and never
        raised: a usage log outage must not affect clients.
        """
        if not attempts:
            return
        request_columns = _request_columns(request)
        rows = [
            {
                **request_columns,
                "provider": attempt.target.provider.name,
                "model": attempt.target.model,
                "attempt_index": index,
                "outcome": attempt.outcome,
                "status_code": attempt.status_code,
                "latency_ms": attempt.latency_ms,
                "first_token_ms": attempt.first_token_ms,
                "estimated_tokens": attempt.estimated_tokens,
                "degraded": attempt.degraded,
                "prompt_tokens": attempt.prompt_tokens,
                "completion_tokens": attempt.completion_tokens,
                "error_message": _cut(attempt.error_message),
                "cache": cache,
                "cost_usd": _cost(
                    attempt.target.limits.price, attempt.prompt_tokens, attempt.completion_tokens
                ),
            }
            for index, attempt in enumerate(attempts)
        ]
        await self._insert(request.request_id, rows)

    async def write_cache_hit(
        self, request: LoggedRequest, answer: CachedAnswer, *, latency_ms: int
    ) -> None:
        """Insert the single row of a request answered from the cache.

        It names the target that generated the answer and the tokens it used: the
        tokens the cache saved. A hit costs nothing; `saved_cost_usd` is what those
        tokens cost at the current price of that model. `latency_ms` is the time of
        the cache lookup.
        Like `write`, a database error is logged and never raised.
        """
        usage = answer.body.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        prompt_tokens = _int_or_none(usage.get("prompt_tokens"))
        completion_tokens = _int_or_none(usage.get("completion_tokens"))
        price = self._prices.get((answer.provider, answer.model))
        row = {
            **_request_columns(request),
            "provider": answer.provider,
            "model": answer.model,
            "attempt_index": 0,
            "outcome": CACHE_HIT,
            "status_code": 200,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cache": "hit",
            "cache_similarity": answer.similarity,
            "cost_usd": Decimal(0),
            "saved_cost_usd": _cost(price, prompt_tokens, completion_tokens),
        }
        await self._insert(request.request_id, [row])

    async def write_tenant_rejection(self, request: LoggedRequest, reason: str) -> None:
        """Insert the single row of a request refused by its tenant quota.

        No provider was examined, so `provider`, `model` and `latency_ms` stay NULL.
        Like `write`, a database error is logged and never raised.
        """
        row = {
            **_request_columns(request),
            "attempt_index": 0,
            "outcome": REJECTED_TENANT_QUOTA,
            "status_code": 429,
            "error_message": _cut(reason),
        }
        await self._insert(request.request_id, [row])

    async def _insert(self, request_id: str, rows: list[dict[str, Any]]) -> None:
        """Insert the rows of one request in a single multi-row INSERT, never raising."""
        try:
            async with self._engine.begin() as connection:
                await connection.execute(insert(UsageLogRow).values(rows))
        except Exception:
            # Rows hold no prompt, so the error details are safe to log.
            logger.exception("could not write the usage log of request %s", request_id)


def _request_columns(request: LoggedRequest) -> dict[str, Any]:
    """The columns shared by every row of a request."""
    return {
        "request_id": request.request_id,
        "created_at": request.received_at,
        "tenant_id": request.owner.tenant_id,
        "api_key_id": request.owner.api_key_id,
        "alias": request.alias,
        "prompt_chars": request.prompt_chars,
        "stream": request.stream,
    }


def _cut(message: str | None) -> str | None:
    """Fit the column: details copied from upstream errors (code, param) have no length limit."""
    return None if message is None else message[:ERROR_MESSAGE_MAX_CHARS]


def _cost(
    price: ModelPrice | None, prompt_tokens: int | None, completion_tokens: int | None
) -> Decimal | None:
    """Cost in USD of the tokens, or None when the price or a token count is unknown."""
    if price is None or prompt_tokens is None or completion_tokens is None:
        return None
    return (prompt_tokens * price.input + completion_tokens * price.output) / 1_000_000


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
