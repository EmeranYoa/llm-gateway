"""Shared quota state in Redis: may a request go through, and can a target be called now.

Before routing, the API calls `TenantGate.acquire` once per request: one Lua
script checks the tenant's own quotas, counts the request and reserves its
token estimate in the tenant's daily budget. Once the request is over, the API
corrects or releases that reservation with `TenantGate.record_*`.

Before calling a target, the router calls `TargetGate.acquire`. One Lua script
checks, atomically, everything that can block the target: cooldown, circuit
breaker and quotas (ADR 0001). After the call, the router reports the outcome
with one of the `record_*` methods, which run another Lua script.

The state lives in Redis so that several gateway instances share it. When Redis
is unavailable, both gates let requests through without checks (ADR 0002).
"""

import datetime as dt
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import BreakerSection, CooldownSection, DailyReset, Target, TenantLimits
from app.routing.quotas import estimate_call_tokens, estimate_prompt_tokens, quota_day

logger = logging.getLogger(__name__)

_LUA_DIR = Path(__file__).parent / "lua"

_QUOTA_REASONS = ("rpm", "tpm", "rpd")

# The daily token budget of every tenant resets at 00:00 UTC.
_UTC_MIDNIGHT = DailyReset(time=dt.time(0, 0), timezone="UTC")


@dataclass(frozen=True)
class Reservation:
    """Quota reserved in Redis for one call to a target."""

    id: str
    tokens: int
    """Estimated tokens reserved in the TPM window."""
    is_trial: bool = False
    """True when this call is the single trial call of a half-open breaker."""
    degraded: bool = False
    """True when Redis was unavailable: nothing was checked or reserved (ADR 0002)."""

    @classmethod
    def without_redis(cls, tokens: int) -> "Reservation":
        """A reservation for a call made while Redis is unavailable."""
        return cls(id=uuid4().hex, tokens=tokens, degraded=True)


@dataclass(frozen=True)
class Refusal:
    """Why a target cannot be called now, and how long to wait before trying it again."""

    reason: str
    """"cooldown", "breaker", or the full quota: "rpm", "tpm" or "rpd"."""
    wait_seconds: float

    @property
    def is_quota(self) -> bool:
        return self.reason in _QUOTA_REASONS

    def __str__(self) -> str:
        label = f"{self.reason} quota full" if self.is_quota else self.reason
        return f"{label} ({self.wait_seconds:.1f} s left)"


class TargetGate:
    def __init__(self, redis: Redis, cooldown: CooldownSection, breaker: BreakerSection) -> None:
        self._redis = redis
        self._cooldown = cooldown
        self._breaker = breaker
        self._acquire_script = redis.register_script(_lua("acquire_target.lua"))
        self._record_script = redis.register_script(_lua("record_outcome.lua"))

    async def is_available(self) -> bool:
        """Tell whether Redis answers, for the health check."""
        try:
            return bool(await self._redis.ping())
        except RedisError:
            return False

    async def acquire(
        self, target: Target, estimated_tokens: int, attempt_timeout: float
    ) -> Reservation | Refusal:
        """Reserve the quota of one call to `target`, or explain why it cannot be called now.

        When the breaker is half-open, the reservation may be its single trial
        call. The trial slot is held at most `attempt_timeout` seconds, so it
        frees itself if this gateway instance dies during the call.

        When Redis is unavailable, the call is allowed without any check
        (fail open, ADR 0002) and the reservation is marked `degraded`.
        """
        try:
            return await self._acquire(target, estimated_tokens, attempt_timeout)
        except RedisError as error:
            logger.warning(
                "Redis is unavailable (%s): routing without cooldown, breaker or quota checks",
                type(error).__name__,
            )
            return Reservation.without_redis(estimated_tokens)

    async def _acquire(
        self, target: Target, estimated_tokens: int, attempt_timeout: float
    ) -> Reservation | Refusal:
        reservation_id = uuid4().hex
        limits = target.limits
        day, next_reset = quota_day(target.provider.daily_reset, dt.datetime.now(dt.UTC))
        result = await self._acquire_script(
            keys=[
                _key("cooldown", target),
                _key("rpm", target),
                _key("tpm", target),
                f"{_key('rpd', target)}:{day.isoformat()}",
                *_breaker_keys(target)[1:],
            ],
            args=[
                reservation_id,
                estimated_tokens,
                limits.rpm or 0,
                limits.tpm or 0,
                limits.rpd or 0,
                round(next_reset.timestamp() * 1000),
                _ms(attempt_timeout),
            ],
        )
        if result[0] == b"ok":
            return Reservation(reservation_id, estimated_tokens, is_trial=int(result[1]) == 1)
        return Refusal(reason=result[0].decode(), wait_seconds=int(result[1]) / 1000)

    async def record_success(
        self, target: Target, reservation: Reservation, used_tokens: int | None
    ) -> None:
        """Replace the token estimate with the real usage, and reset the 429 streak.

        When the provider did not report its usage, the estimate stays reserved.
        Counts as a breaker success.
        """
        await self._record(
            target,
            reservation,
            cooldown="success",
            tokens="correct",
            breaker="success",
            used_tokens=_or_unknown(used_tokens),
        )

    async def record_commit(self, target: Target, reservation: Reservation) -> None:
        """A stream reached its first content: the provider works.

        Counts as a breaker success and resets the 429 streak now, so a half-open
        trial ends within its slot TTL however long the stream lasts. The tokens
        stay reserved until the end of the stream (`record_stream_end`).
        """
        await self._record(
            target, reservation, cooldown="success", tokens="keep", breaker="success"
        )

    async def record_stream_end(
        self, target: Target, reservation: Reservation, used_tokens: int | None
    ) -> None:
        """Replace the token estimate of a finished stream with its real usage.

        The breaker result was already recorded at the commit point.
        """
        await self._record(
            target,
            replace(reservation, is_trial=False),
            cooldown="none",
            tokens="correct",
            breaker="neutral",
            used_tokens=_or_unknown(used_tokens),
        )

    async def record_stream_interrupted(self, target: Target, reservation: Reservation) -> None:
        """A stream broke after its first content: the provider failed mid-answer.

        Counts as a breaker failure. The tokens stay reserved: part of the answer
        was generated, and sent to the client.
        """
        await self._record(
            target,
            replace(reservation, is_trial=False),
            cooldown="none",
            tokens="keep",
            breaker="failure",
        )

    async def record_cancelled(self, target: Target, reservation: Reservation) -> None:
        """The client left before the call ended: not the provider's fault.

        Neutral for the breaker (a half-open trial slot is released). The tokens
        stay reserved: the provider may have generated them already.
        """
        await self._record(target, reservation, cooldown="none", tokens="keep", breaker="neutral")

    async def record_rate_limited(
        self, target: Target, reservation: Reservation, retry_after: float | None
    ) -> float | None:
        """Release the tokens and put `target` in cooldown after a 429.

        The cooldown is `retry_after` when the provider gave one. Otherwise it is
        progressive: it doubles with each consecutive 429, up to the configured max.
        Neutral for the breaker. Returns the cooldown in seconds, or None when
        Redis is unavailable.
        """
        return await self._record(
            target,
            reservation,
            cooldown="rate_limited",
            tokens="release",
            breaker="neutral",
            retry_ms=-1 if retry_after is None else _ms(retry_after),
        )

    async def record_misconfigured(self, target: Target, reservation: Reservation) -> float | None:
        """Release the tokens and put `target` in the long misconfiguration cooldown.

        Neutral for the breaker. Returns the cooldown in seconds, or None when
        Redis is unavailable.
        """
        return await self._record(
            target, reservation, cooldown="misconfigured", tokens="release", breaker="neutral"
        )

    async def record_failure(
        self, target: Target, reservation: Reservation, *, keep_tokens: bool, provider_failed: bool
    ) -> None:
        """Account for any other failed call.

        The tokens are released, unless `keep_tokens` is set: after a timeout,
        the provider may have generated them anyway. `provider_failed` counts a
        breaker failure (5xx, network error, timeout); otherwise the provider
        worked and refused the request itself, which counts as a breaker success.
        """
        await self._record(
            target,
            reservation,
            cooldown="none",
            tokens="keep" if keep_tokens else "release",
            breaker="failure" if provider_failed else "success",
        )

    async def _record(
        self,
        target: Target,
        reservation: Reservation,
        *,
        cooldown: str,
        tokens: str,
        breaker: str,
        retry_ms: int = -1,
        used_tokens: int = -1,
    ) -> float | None:
        """Run `record_outcome.lua`. Returns the cooldown in seconds, or None without Redis."""
        if reservation.degraded:
            return None
        try:
            cooldown_ms = await self._run_record_script(
                target,
                reservation,
                cooldown=cooldown,
                tokens=tokens,
                breaker=breaker,
                retry_ms=retry_ms,
                used_tokens=used_tokens,
            )
        except RedisError as error:
            logger.warning(
                "Redis is unavailable (%s): the outcome of a call to %s was not recorded",
                type(error).__name__,
                target.name,
            )
            return None
        return int(cooldown_ms) / 1000

    async def _run_record_script(
        self,
        target: Target,
        reservation: Reservation,
        *,
        cooldown: str,
        tokens: str,
        breaker: str,
        retry_ms: int,
        used_tokens: int,
    ) -> int:
        # The request itself always stays counted: the provider may have counted it too.
        cooldown_ms = await self._record_script(
            keys=[
                _key("cooldown", target),
                _key("rate_limit_streak", target),
                _key("tpm", target),
                *_breaker_keys(target),
            ],
            args=[
                cooldown,
                retry_ms,
                _ms(self._cooldown.initial),
                _ms(self._cooldown.max),
                _ms(self._cooldown.misconfigured),
                reservation.id,
                reservation.tokens,
                tokens,
                used_tokens,
                breaker,
                1 if reservation.is_trial else 0,
                self._breaker.failures,
                _ms(self._breaker.window),
                _ms(self._breaker.open),
            ],
        )
        return int(cooldown_ms)


class TenantQuotaExceeded(Exception):
    """The tenant has used up one of its own quotas. No provider is called."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(f"{message} ({retry_after:.1f} s left)")
        self.retry_after = retry_after
        """Seconds until the tenant may send this request again."""


class TenantRpmExceeded(TenantQuotaExceeded):
    """The tenant has sent its requests-per-minute limit within the last 60 s."""

    def __init__(self, rpm: int, retry_after: float) -> None:
        super().__init__(f"tenant RPM limit of {rpm} reached", retry_after)
        self.rpm = rpm


class TenantBudgetExceeded(TenantQuotaExceeded):
    """The token estimate of the request is larger than what is left of the daily budget."""

    def __init__(self, budget: int, remaining: int, needed: int, retry_after: float) -> None:
        super().__init__(
            f"tenant daily token budget of {budget} too low: {needed} tokens needed, "
            f"{remaining} left",
            retry_after,
        )
        self.budget = budget
        self.remaining = remaining
        """Tokens left in today's budget."""
        self.needed = needed
        """Token estimate of the refused request."""


@dataclass(frozen=True)
class TenantAdmission:
    """A request the tenant quotas let through, and the tokens reserved for it."""

    budget_key: str | None = None
    """Daily budget counter holding the reservation, or None when nothing was reserved."""
    reserved_tokens: int = 0
    degraded: bool = False
    """True when Redis was unavailable: the quotas were not checked (ADR 0002)."""


class TenantGate:
    """Tenant quotas, checked once per request before routing."""

    def __init__(
        self, redis: Redis, default_limits: TenantLimits, default_completion_tokens: int
    ) -> None:
        self._default_limits = default_limits
        self._default_completion_tokens = default_completion_tokens
        self._acquire_script = redis.register_script(_lua("acquire_tenant.lua"))
        self._record_script = redis.register_script(_lua("record_tenant_outcome.lua"))

    async def acquire(
        self, tenant_id: int, own_limits: TenantLimits, body: Mapping[str, Any]
    ) -> TenantAdmission:
        """Count one request of the tenant and reserve its tokens, or raise `TenantQuotaExceeded`.

        `own_limits` are the tenant's own limits; a missing one falls back to
        the default limits of the config. The request stays counted in the RPM
        even if routing then fails. The token estimate of `body` (prompt plus
        `max_tokens` or the default completion size) is reserved in the daily
        budget until `record_success` or `record_failure`. When Redis is
        unavailable, the request is let through without any check (fail open,
        ADR 0002).
        """
        rpm = _own_or_default(own_limits.rpm, self._default_limits.rpm)
        budget = _own_or_default(own_limits.tokens_per_day, self._default_limits.tokens_per_day)
        # Not capped by a target TPM: the budget counts what the request may really use.
        tokens = estimate_call_tokens(
            estimate_prompt_tokens(body), body, self._default_completion_tokens, tpm=None
        )
        day, next_midnight = quota_day(_UTC_MIDNIGHT, dt.datetime.now(dt.UTC))
        budget_key = f"tenant_tokens:{tenant_id}:{day.isoformat()}"
        try:
            result = await self._acquire_script(
                keys=[f"tenant_rpm:{tenant_id}", budget_key],
                args=[
                    uuid4().hex,
                    rpm or 0,
                    tokens,
                    budget or 0,
                    round(next_midnight.timestamp() * 1000),
                ],
            )
        except RedisError as error:
            logger.warning(
                "Redis is unavailable (%s): tenant quotas are not checked", type(error).__name__
            )
            return TenantAdmission(degraded=True)
        if result[0] == b"ok":
            if budget is None:
                return TenantAdmission()
            return TenantAdmission(budget_key=budget_key, reserved_tokens=tokens)
        retry_after = int(result[1]) / 1000
        if result[0] == b"rpm":
            assert rpm is not None, "the script only refuses a request when a limit is set"
            raise TenantRpmExceeded(rpm, retry_after)
        assert budget is not None, "the script only refuses a request when a limit is set"
        raise TenantBudgetExceeded(budget, int(result[2]), tokens, retry_after)

    async def record_success(self, admission: TenantAdmission, used_tokens: int | None) -> None:
        """Replace the reserved token estimate with the real usage of the request.

        When the provider did not report its usage, the estimate stays reserved.
        """
        if used_tokens is not None:
            await self._record(admission, "correct", used_tokens)

    async def record_failure(self, admission: TenantAdmission, *, keep_tokens: bool) -> None:
        """Give the reserved tokens back after a request that failed as a whole.

        With `keep_tokens` they stay reserved: after a timeout, the provider may
        have generated them anyway.
        """
        if not keep_tokens:
            await self.release(admission)

    async def release(self, admission: TenantAdmission) -> None:
        """Give the reserved tokens back: the request used none (a cache hit, for example)."""
        await self._record(admission, "release", 0)

    async def _record(self, admission: TenantAdmission, action: str, used_tokens: int) -> None:
        """Run `record_tenant_outcome.lua`, when tokens were reserved for the request."""
        if admission.budget_key is None:
            return
        try:
            await self._record_script(
                keys=[admission.budget_key],
                args=[admission.reserved_tokens, action, used_tokens],
            )
        except RedisError as error:
            logger.warning(
                "Redis is unavailable (%s): the token budget of a tenant was not updated",
                type(error).__name__,
            )


def _own_or_default(own: int | None, default: int | None) -> int | None:
    return own if own is not None else default


def _key(kind: str, target: Target) -> str:
    return f"{kind}:{target.provider.name}:{target.model}"


def _breaker_keys(target: Target) -> list[str]:
    """Failure window, "open" key, "half-open" marker and trial slot of the breaker."""
    return [
        _key("breaker_failures", target),
        _key("breaker_open", target),
        _key("breaker_half_open", target),
        _key("breaker_trial", target),
    ]


def _or_unknown(value: int | None) -> int:
    return -1 if value is None else value


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _lua(name: str) -> str:
    return (_LUA_DIR / name).read_text(encoding="utf-8")
