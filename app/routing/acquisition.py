"""Shared target state in Redis: can a target be called now, and what happened after the call.

Before calling a target, the router calls `TargetGate.acquire`. One Lua script
checks, atomically, everything that can block the target (ADR 0001). After the
call, the router reports the outcome with one of the `record_*` methods, which
run another Lua script.

The state lives in Redis so that several gateway instances share it.
"""

from dataclasses import dataclass
from pathlib import Path

from redis.asyncio import Redis

from app.config import CooldownSection, Target

_LUA_DIR = Path(__file__).parent / "lua"


@dataclass(frozen=True)
class Refusal:
    """Why a target cannot be called now, and how long to wait before trying it again."""

    reason: str
    wait_seconds: float

    def __str__(self) -> str:
        return f"{self.reason} ({self.wait_seconds:.1f} s left)"


class TargetGate:
    def __init__(self, redis: Redis, cooldown: CooldownSection) -> None:
        self._cooldown = cooldown
        self._acquire_script = redis.register_script(_lua("acquire_target.lua"))
        self._record_script = redis.register_script(_lua("record_outcome.lua"))

    async def acquire(self, target: Target) -> Refusal | None:
        """Return None when `target` can be called now, otherwise why it cannot."""
        result = await self._acquire_script(keys=[_cooldown_key(target)])
        if result[0] == b"ok":
            return None
        return Refusal(reason=result[0].decode(), wait_seconds=int(result[1]) / 1000)

    async def record_success(self, target: Target) -> None:
        """Reset the consecutive-429 streak of `target`."""
        await self._record(target, "success")

    async def record_rate_limited(self, target: Target, retry_after: float | None) -> float:
        """Put `target` in cooldown after a 429. Return the cooldown in seconds.

        The cooldown is `retry_after` when the provider gave one. Otherwise it is
        progressive: it doubles with each consecutive 429, up to the configured max.
        """
        retry_ms = -1 if retry_after is None else _ms(retry_after)
        return await self._record(target, "rate_limited", retry_ms)

    async def record_misconfigured(self, target: Target) -> float:
        """Put `target` in the long misconfiguration cooldown. Return it in seconds."""
        return await self._record(target, "misconfigured")

    async def _record(self, target: Target, outcome: str, retry_ms: int = -1) -> float:
        cooldown_ms = await self._record_script(
            keys=[_cooldown_key(target), _rate_limit_streak_key(target)],
            args=[
                outcome,
                retry_ms,
                _ms(self._cooldown.initial),
                _ms(self._cooldown.max),
                _ms(self._cooldown.misconfigured),
            ],
        )
        return int(cooldown_ms) / 1000


def _cooldown_key(target: Target) -> str:
    return f"cooldown:{target.provider.name}:{target.model}"


def _rate_limit_streak_key(target: Target) -> str:
    return f"rate_limit_streak:{target.provider.name}:{target.model}"


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _lua(name: str) -> str:
    return (_LUA_DIR / name).read_text(encoding="utf-8")
