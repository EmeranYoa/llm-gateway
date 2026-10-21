"""Shared target state in Redis: can a target be called now, and what happened after the call.

Before calling a target, the router calls `TargetGate.acquire`. One Lua script
checks, atomically, everything that can block the target (ADR 0001). After the
call, the router reports the outcome with one of the `record_*` methods, which
run another Lua script.

The state lives in Redis so that several gateway instances share it.
"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from redis.asyncio import Redis

from app.config import CooldownSection, Target
from app.routing.quotas import quota_day

_LUA_DIR = Path(__file__).parent / "lua"


@dataclass(frozen=True)
class Reservation:
    """Quota reserved in Redis for one call to a target."""

    id: str
    tokens: int
    """Estimated tokens reserved in the TPM window."""


@dataclass(frozen=True)
class Refusal:
    """Why a target cannot be called now, and how long to wait before trying it again."""

    reason: str
    """"cooldown", or the full quota: "rpm", "tpm" or "rpd"."""
    wait_seconds: float

    @property
    def is_quota(self) -> bool:
        return self.reason != "cooldown"

    def __str__(self) -> str:
        label = f"{self.reason} quota full" if self.is_quota else self.reason
        return f"{label} ({self.wait_seconds:.1f} s left)"


class TargetGate:
    def __init__(self, redis: Redis, cooldown: CooldownSection) -> None:
        self._cooldown = cooldown
        self._acquire_script = redis.register_script(_lua("acquire_target.lua"))
        self._record_script = redis.register_script(_lua("record_outcome.lua"))

    async def acquire(self, target: Target, estimated_tokens: int) -> Reservation | Refusal:
        """Reserve the quota of one call to `target`, or explain why it cannot be called now."""
        reservation = Reservation(id=uuid4().hex, tokens=estimated_tokens)
        limits = target.limits
        day, next_reset = quota_day(target.provider.daily_reset, dt.datetime.now(dt.UTC))
        result = await self._acquire_script(
            keys=[
                _key("cooldown", target),
                _key("rpm", target),
                _key("tpm", target),
                f"{_key('rpd', target)}:{day.isoformat()}",
            ],
            args=[
                reservation.id,
                reservation.tokens,
                limits.rpm or 0,
                limits.tpm or 0,
                limits.rpd or 0,
                round(next_reset.timestamp() * 1000),
            ],
        )
        if result[0] == b"ok":
            return reservation
        return Refusal(reason=result[0].decode(), wait_seconds=int(result[1]) / 1000)

    async def record_success(
        self, target: Target, reservation: Reservation, used_tokens: int | None
    ) -> None:
        """Replace the token estimate with the real usage, and reset the 429 streak.

        When the provider did not report its usage, the estimate stays reserved.
        """
        await self._record(
            target, reservation, "success", "correct", used_tokens=_or_unknown(used_tokens)
        )

    async def record_rate_limited(
        self, target: Target, reservation: Reservation, retry_after: float | None
    ) -> float:
        """Release the tokens and put `target` in cooldown after a 429.

        The cooldown is `retry_after` when the provider gave one. Otherwise it is
        progressive: it doubles with each consecutive 429, up to the configured max.
        Returns the cooldown in seconds.
        """
        retry_ms = -1 if retry_after is None else _ms(retry_after)
        return await self._record(target, reservation, "rate_limited", "release", retry_ms)

    async def record_misconfigured(self, target: Target, reservation: Reservation) -> float:
        """Release the tokens and put `target` in the long misconfiguration cooldown.

        Returns the cooldown in seconds.
        """
        return await self._record(target, reservation, "misconfigured", "release")

    async def record_failure(
        self, target: Target, reservation: Reservation, *, keep_tokens: bool
    ) -> None:
        """Account for any other failed call.

        The tokens are released, unless `keep_tokens` is set: after a timeout,
        the provider may have generated them anyway.
        """
        await self._record(target, reservation, "failure", "keep" if keep_tokens else "release")

    async def _record(
        self,
        target: Target,
        reservation: Reservation,
        outcome: str,
        token_action: str,
        retry_ms: int = -1,
        used_tokens: int = -1,
    ) -> float:
        # The request itself always stays counted: the provider may have counted it too.
        cooldown_ms = await self._record_script(
            keys=[
                _key("cooldown", target),
                _key("rate_limit_streak", target),
                _key("tpm", target),
            ],
            args=[
                outcome,
                retry_ms,
                _ms(self._cooldown.initial),
                _ms(self._cooldown.max),
                _ms(self._cooldown.misconfigured),
                reservation.id,
                reservation.tokens,
                token_action,
                used_tokens,
            ],
        )
        return int(cooldown_ms) / 1000


def _key(kind: str, target: Target) -> str:
    return f"{kind}:{target.provider.name}:{target.model}"


def _or_unknown(value: int | None) -> int:
    return -1 if value is None else value


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _lua(name: str) -> str:
    return (_LUA_DIR / name).read_text(encoding="utf-8")
