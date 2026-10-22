"""Usage log: one PostgreSQL row per target examined for a request.

Rows are written after the response is sent, so logging never adds latency.
The prompt itself is never stored, only its length.
"""

import datetime as dt
import logging
from collections.abc import Sequence

from sqlalchemy import BigInteger, DateTime, Identity, String, Text, false, insert
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.routing.router import Attempt
from app.storage.db import Base

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX_CHARS = 500


class UsageLogRow(Base):
    """One examined target. Rows of the same request share `request_id`.

    The schema is created by the Alembic migrations in `migrations/versions/`.
    """

    __tablename__ = "usage_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    alias: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
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
        alias: str,
        prompt_chars: int,
        attempts: Sequence[Attempt],
    ) -> None:
        """Insert one row per attempt, in a single multi-row INSERT.

        Nothing is written when no target was examined (unknown alias, streaming refused).
        This runs after the response is sent, so a database error is logged and never
        raised: a usage log outage must not affect clients.
        """
        if not attempts:
            return
        rows = [
            {
                "request_id": request_id,
                "created_at": received_at,
                "alias": alias,
                "provider": attempt.target.provider.name,
                "model": attempt.target.model,
                "attempt_index": index,
                "outcome": attempt.outcome,
                "status_code": attempt.status_code,
                "latency_ms": attempt.latency_ms,
                "prompt_chars": prompt_chars,
                "estimated_tokens": attempt.estimated_tokens,
                "degraded": attempt.degraded,
                "prompt_tokens": attempt.prompt_tokens,
                "completion_tokens": attempt.completion_tokens,
                "error_message": _cut(attempt.error_message),
            }
            for index, attempt in enumerate(attempts)
        ]
        try:
            async with self._engine.begin() as connection:
                await connection.execute(insert(UsageLogRow).values(rows))
        except Exception:
            # Rows hold no prompt, so the error details are safe to log.
            logger.exception("could not write the usage log of request %s", request_id)


def _cut(message: str | None) -> str | None:
    """Fit the column: details copied from upstream errors (code, param) have no length limit."""
    return None if message is None else message[:ERROR_MESSAGE_MAX_CHARS]
