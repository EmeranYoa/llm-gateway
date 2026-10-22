"""Shared quota state in Redis: may a request go through, and can a target be called now.

Before routing, the API calls `TenantGate.acquire` once per request: one Lua
script checks and counts the tenant's own quota.

Before calling a target, the router calls `TargetGate.acquire`. One Lua script
checks, atomically, everything that can block the target: cooldown, circuit
breaker and quotas (ADR 0001). After the call, the router reports the outcome
with one of the `record_*` methods, which run another Lua script.

The state lives in Redis so that several gateway instances share it. When Redis
is unavailable, both gates let requests through without checks (ADR 0002).
"""

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import BreakerSection, CooldownSection, Target, TenantLimits
from app.routing.quotas import quota_day

logger = logging.getLogger(__name__)

_LUA_DIR = Path(__file__).parent / "lua"

_QUOTA_REASONS = ("rpm", "tpm", "rpd")


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
    """The tenant has used up its own quota. No provider is called."""

    def __init__(self, rpm: int, retry_after: float) -> None:
        super().__init__(f"tenant RPM limit of {rpm} reached ({retry_after:.1f} s left)")
        self.rpm = rpm
        self.retry_after = retry_after
        """Seconds until the tenant may send a request again."""


@dataclass(frozen=True)
class TenantAdmission:
    """A request the tenant quotas let through."""

    degraded: bool = False
    """True when Redis was unavailable: the quotas were not checked (ADR 0002)."""


class TenantGate:
    """Tenant quotas, checked once per request before routing."""

    def __init__(self, redis: Redis, default_limits: TenantLimits) -> None:
        self._default_limits = default_limits
        self._acquire_script = redis.register_script(_lua("acquire_tenant.lua"))

    async def acquire(self, tenant_id: int, own_limits: TenantLimits) -> TenantAdmission:
        """Count one request of the tenant, or raise `TenantQuotaExceeded`.

        `own_limits` are the tenant's own limits; a missing one falls back to
        the default limits of the config. The request stays counted even if
        routing then fails. When Redis is unavailable, the request is let
        through without any check (fail open, ADR 0002).
        """
        rpm = own_limits.rpm if own_limits.rpm is not None else self._default_limits.rpm
        try:
            result = await self._acquire_script(
                keys=[f"tenant_rpm:{tenant_id}"], args=[uuid4().hex, rpm or 0]
            )
        except RedisError as error:
            logger.warning(
                "Redis is unavailable (%s): tenant quotas are not checked", type(error).__name__
            )
            return TenantAdmission(degraded=True)
        if result[0] == b"ok":
            return TenantAdmission()
        assert rpm is not None, "the script only refuses a request when a limit is set"
        raise TenantQuotaExceeded(rpm, retry_after=int(result[1]) / 1000)


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
