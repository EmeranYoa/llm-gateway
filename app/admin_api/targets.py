"""Target report of the admin API: how each provider/model behaved, and its state right now.

The statistics come from the usage log: one row per examined target, so a
target's rows count its calls and the times it was skipped. Cache hits are left
out: they name the target of the stored answer, but call nothing.

The live state comes from Redis, read through `TargetGate.state`, so the Redis
key formats stay in `app/routing/acquisition.py`.
"""

import datetime as dt
import logging
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin_api.dependencies import Admin, Config, Database
from app.admin_api.periods import Period
from app.config import GatewayConfig, Target
from app.routing.acquisition import BreakerStatus, TargetGate, TargetState
from app.routing.quotas import quota_day
from app.routing.router import Outcome
from app.storage.usage import CACHE_HIT, UsageLogRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v1")

# --- Response bodies ---


class TargetStatistics(BaseModel):
    """What happened to the attempts on one target during the period.

    Each count is a number of usage rows with that outcome. Cache hits are not counted.
    """

    calls: int = Field(
        description="Real calls to the provider: attempts that were neither skipped nor refused"
        " by the gateway before the call (prompt larger than the target TPM)."
    )
    success: int
    rate_limited: int
    timeout: int
    unavailable: int = Field(description="5xx or network error.")
    misconfigured: int = Field(description="401, 403 or 404: a bad key or a removed model.")
    invalid_request: int = Field(description="Any other 4xx caused by the client request.")
    context_too_large: int = Field(
        description="The request did not fit the target (checked before the call, or refused "
        "by the provider)."
    )
    interrupted: int = Field(description="Streams that broke after their first content.")
    cancelled: int = Field(description="Calls the client left before they ended.")
    skipped_cooldown: int
    skipped_breaker: int
    skipped_quota: int
    success_rate: float | None = Field(description="success / calls. Null when there was no call.")
    latency_p50_ms: float | None = Field(
        description="Median duration of the successful calls. Null without a successful call."
    )
    latency_p95_ms: float | None = Field(
        description="95th percentile of the duration of the successful calls."
    )


_NO_ATTEMPT = TargetStatistics(
    calls=0,
    **{outcome.value: 0 for outcome in Outcome},
    success_rate=None,
    latency_p50_ms=None,
    latency_p95_ms=None,
)
"""Statistics of a configured target without any usage row in the period."""


class LiveStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    """Redis is unavailable: the cooldown, breaker and used quotas cannot be read."""


class CooldownState(BaseModel):
    """Cooldown after a 429 or a misconfiguration error: the target is skipped until it ends."""

    active: bool
    until: dt.datetime | None = Field(description="End of the cooldown. Null when not active.")


class CircuitBreakerState(BaseModel):
    state: BreakerStatus
    open_until: dt.datetime | None = Field(
        description="When the open breaker turns half-open. Null unless the breaker is open."
    )
    trial_running: bool = Field(
        description="True while the single trial call of a half-open breaker is running."
    )


class QuotaUsage(BaseModel):
    """One quota of the target: the configured limit, and how much of it is used."""

    used: int | None = Field(
        description="Used in the current window. Only counted when the limit is set. "
        "Null when the live state is unknown."
    )
    limit: int | None = Field(description="Configured limit. Null means no limit.")


class DailyQuotaUsage(QuotaUsage):
    resets_at: dt.datetime = Field(description="Next daily reset of the provider.")


class TargetLiveState(BaseModel):
    """State of the target in Redis right now, shared by every gateway instance."""

    status: LiveStatus
    cooldown: CooldownState | None = Field(description="Null when the status is unknown.")
    breaker: CircuitBreakerState | None = Field(description="Null when the status is unknown.")
    rpm: QuotaUsage = Field(description="Requests in the last 60 s.")
    tpm: QuotaUsage = Field(description="Tokens in the last 60 s.")
    rpd: DailyQuotaUsage = Field(description="Requests since the provider's last daily reset.")


class TargetReport(BaseModel):
    """One provider/model: its statistics over the period, and its state now."""

    provider: str
    model: str
    configured: bool = Field(
        description="False for a target that is in no route any more but has usage rows "
        "in the period."
    )
    statistics: TargetStatistics
    live: TargetLiveState | None = Field(description="Null when the target is not configured.")


class TargetsReport(BaseModel):
    """Every configured target, in the order of the routes, then the targets no longer
    configured that have usage rows in the period."""

    period: Period
    targets: list[TargetReport]


# --- Route ---


def get_gate(request: Request) -> TargetGate:
    """Return the reader of the target state in Redis, built at startup."""
    return cast(TargetGate, request.app.state.gate)


Gate = Annotated[TargetGate, Depends(get_gate)]


@router.get("/targets")
async def targets(
    _: Admin, database: Database, config: Config, gate: Gate, period: Period = Period.DAY
) -> TargetsReport:
    """Report the statistics of every target over the period, and its live state."""
    statistics = await _statistics(database, period.start(dt.datetime.now(dt.UTC)))
    configured = _configured_targets(config)
    live = await _live_states(gate, configured)
    reports = [
        TargetReport(
            provider=target.provider.name,
            model=target.model,
            configured=True,
            statistics=statistics.pop((target.provider.name, target.model), _NO_ATTEMPT),
            live=live_state,
        )
        for target, live_state in zip(configured, live, strict=True)
    ]
    # What is left are targets removed from the configuration since their rows were written.
    reports += [
        TargetReport(provider=provider, model=model, configured=False, statistics=stats, live=None)
        for (provider, model), stats in sorted(statistics.items())
    ]
    return TargetsReport(period=period, targets=reports)


# --- Statistics ---


async def _statistics(
    database: AsyncEngine, since: dt.datetime
) -> dict[tuple[str, str], TargetStatistics]:
    """Statistics of every provider/model that has usage rows since `since`, cache hits aside."""
    row = UsageLogRow
    succeeded = row.outcome == Outcome.SUCCESS
    query = (
        select(
            row.provider,
            row.model,
            # A call has a duration. Skips have none, nor a request the router found
            # too large for the target before calling it (`context_too_large`).
            func.count().filter(row.latency_ms.is_not(None)).label("calls"),
            *(func.count().filter(row.outcome == outcome).label(outcome) for outcome in Outcome),
            # Continuous percentiles: interpolated between the two nearest latencies.
            func.percentile_cont(0.5)
            .within_group(row.latency_ms)
            .filter(succeeded)
            .label("latency_p50_ms"),
            func.percentile_cont(0.95)
            .within_group(row.latency_ms)
            .filter(succeeded)
            .label("latency_p95_ms"),
        )
        .where(
            row.created_at >= since,
            row.provider.is_not(None),
            row.outcome != CACHE_HIT,
        )
        .group_by(row.provider, row.model)
    )
    async with database.connect() as connection:
        result = await connection.execute(query)
    statistics = {}
    for values in result.mappings():
        calls = values["calls"]
        statistics[(values["provider"], values["model"])] = TargetStatistics(
            calls=calls,
            **{outcome.value: values[outcome] for outcome in Outcome},
            success_rate=values[Outcome.SUCCESS] / calls if calls else None,
            latency_p50_ms=values["latency_p50_ms"],
            latency_p95_ms=values["latency_p95_ms"],
        )
    return statistics


# --- Live state ---


def _configured_targets(config: GatewayConfig) -> list[Target]:
    """Every distinct target of the routes, in the order of first appearance."""
    unique: dict[str, Target] = {}
    for targets in config.routes.values():
        for target in targets:
            unique.setdefault(target.name, target)
    return list(unique.values())


async def _live_states(gate: TargetGate, targets: Sequence[Target]) -> list[TargetLiveState]:
    """Read the state of each target in Redis.

    When Redis is unavailable, every state is `unknown`: the first error stops
    the reads, instead of waiting for a timeout once per target.
    """
    try:
        states = [await gate.state(target) for target in targets]
    except RedisError as error:
        logger.warning(
            "Redis is unavailable (%s): the live state of the targets is unknown",
            type(error).__name__,
        )
        return [_unknown_state(target) for target in targets]
    return [_known_state(target, state) for target, state in zip(targets, states, strict=True)]


def _known_state(target: Target, state: TargetState) -> TargetLiveState:
    limits = target.limits
    return TargetLiveState(
        status=LiveStatus.KNOWN,
        cooldown=CooldownState(active=state.cooldown_until is not None, until=state.cooldown_until),
        breaker=CircuitBreakerState(
            state=state.breaker,
            open_until=state.breaker_open_until,
            trial_running=state.trial_running,
        ),
        rpm=QuotaUsage(used=state.rpm_used, limit=limits.rpm),
        tpm=QuotaUsage(used=state.tpm_used, limit=limits.tpm),
        rpd=DailyQuotaUsage(used=state.rpd_used, limit=limits.rpd, resets_at=state.rpd_resets_at),
    )


def _unknown_state(target: Target) -> TargetLiveState:
    """The live state without Redis: only the configured limits are known."""
    limits = target.limits
    _, next_reset = quota_day(target.provider.daily_reset, dt.datetime.now(dt.UTC))
    return TargetLiveState(
        status=LiveStatus.UNKNOWN,
        cooldown=None,
        breaker=None,
        rpm=QuotaUsage(used=None, limit=limits.rpm),
        tpm=QuotaUsage(used=None, limit=limits.tpm),
        rpd=DailyQuotaUsage(used=None, limit=limits.rpd, resets_at=next_reset.astimezone(dt.UTC)),
    )
