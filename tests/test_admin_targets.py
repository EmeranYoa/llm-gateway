"""Tests for the target report of the admin API: statistics per provider/model, and live state."""

import asyncio
import datetime as dt
import os
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from redis.asyncio import Redis
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import GatewayConfig, Settings, Target, load_config
from app.routing.acquisition import Reservation, TargetGate
from app.storage.usage import UsageLogRow
from tests.conftest import FetchUsageRows
from tests.test_admin_api import admin_client, new_admin_key

WriteConfig = Callable[[str], Settings]

GROQ = "llama-3.3-70b-versatile"
GEMINI = "gemini-2.5-flash"
OLLAMA = "llama3.2:3b"

# Groq appears in two routes: it is listed once, where it first appears.
# The breaker opens after 2 failures and stays open 30 s.
TARGETS_CONFIG = f"""
gateway:
  breaker: {{ failures: 2, window: 60, open: 30 }}
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: null
    models:
      {GROQ}: {{ rpm: 30, tpm: 8000, rpd: 1000 }}
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: null
    daily_reset: {{ time: "00:00", timezone: "America/Los_Angeles" }}
    models:
      {GEMINI}: {{ rpm: 10, rpd: 250 }}
  ollama:
    base_url: http://ollama.test/v1
    api_key_env: null
    models:
      "{OLLAMA}": {{}}
routes:
  chat-fast: [ groq/{GROQ}, gemini/{GEMINI} ]
  chat-local: [ ollama/{OLLAMA}, groq/{GROQ} ]
"""

# Nothing listens on port 1: connections are refused at once.
UNREACHABLE_REDIS = "redis://127.0.0.1:1/0"

NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
def settings(write_config: WriteConfig) -> Settings:
    return write_config(TARGETS_CONFIG)


@pytest.fixture
async def admin_key(database_url: str) -> str:
    return await new_admin_key(database_url)


@pytest.fixture
def config(settings: Settings) -> GatewayConfig:
    return load_config(settings.gateway_config_path, os.environ)


@pytest.fixture
async def gate(config: GatewayConfig, redis_url: str) -> AsyncIterator[TargetGate]:
    """The gate the router uses, to set the live state of targets as real calls would."""
    redis = Redis.from_url(redis_url)
    yield TargetGate(redis, config.cooldown, config.breaker)
    await redis.aclose()


def target(config: GatewayConfig, name: str) -> Target:
    return next(t for targets in config.routes.values() for t in targets if t.name == name)


async def seed(database_url: str, *rows: dict[str, Any]) -> None:
    """Insert usage rows: each one gets a request of its own unless it names one."""
    defaults = {"alias": "chat-fast", "attempt_index": 0, "prompt_chars": 10}
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UsageLogRow).values(
                    [{**defaults, "request_id": uuid4().hex, **row} for row in rows]
                )
            )
    finally:
        await engine.dispose()


def row(
    provider: str | None,
    model: str | None,
    outcome: str,
    *,
    latency_ms: int | None = None,
    age: dt.timedelta = dt.timedelta(hours=1),
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "created_at": NOW - age,
    }


async def get_targets(settings: Settings, admin_key: str, period: str = "24h") -> dict[str, Any]:
    async with admin_client(settings, admin_key) as client:
        response = await client.get("/admin/v1/targets", params={"period": period})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def by_name(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"{item['provider']}/{item['model']}": item for item in report["targets"]}


async def test_targets_lists_every_configured_target_once_in_route_order(
    settings: Settings, admin_key: str, usage_rows: FetchUsageRows
) -> None:
    report = await get_targets(settings, admin_key)

    assert report["period"] == "24h"
    assert [
        (item["provider"], item["model"], item["configured"]) for item in report["targets"]
    ] == [
        ("groq", GROQ, True),
        ("gemini", GEMINI, True),
        ("ollama", OLLAMA, True),
    ]
    gemini = by_name(report)[f"gemini/{GEMINI}"]
    assert gemini["statistics"] == {
        "calls": 0,
        "success": 0,
        "rate_limited": 0,
        "timeout": 0,
        "unavailable": 0,
        "misconfigured": 0,
        "invalid_request": 0,
        "context_too_large": 0,
        "interrupted": 0,
        "cancelled": 0,
        "skipped_cooldown": 0,
        "skipped_breaker": 0,
        "skipped_quota": 0,
        "success_rate": None,
        "latency_p50_ms": None,
        "latency_p95_ms": None,
    }


async def test_target_statistics_count_attempts_and_skips_of_the_period(
    settings: Settings, admin_key: str, database_url: str, usage_rows: FetchUsageRows
) -> None:
    await seed(
        database_url,
        *(row("groq", GROQ, "success", latency_ms=ms) for ms in (100, 200, 300, 400)),
        row("groq", GROQ, "rate_limited", latency_ms=50),
        row("groq", GROQ, "timeout", latency_ms=30000),
        row("groq", GROQ, "unavailable", latency_ms=20),
        row("groq", GROQ, "interrupted", latency_ms=900),
        row("groq", GROQ, "skipped_cooldown"),
        row("groq", GROQ, "skipped_cooldown"),
        row("groq", GROQ, "skipped_breaker"),
        row("groq", GROQ, "skipped_quota"),
        # Not calls: a cache hit names the target of the stored answer.
        row("groq", GROQ, "cache_hit", latency_ms=5),
        # Outside the 24 h period.
        row("groq", GROQ, "success", latency_ms=5000, age=dt.timedelta(days=2)),
        # Another target, and a request refused by its tenant quota (no target).
        row("gemini", GEMINI, "invalid_request", latency_ms=80),
        row(None, None, "rejected_tenant_quota"),
    )

    report = await get_targets(settings, admin_key)

    groq = by_name(report)[f"groq/{GROQ}"]["statistics"]
    assert groq == {
        "calls": 8,
        "success": 4,
        "rate_limited": 1,
        "timeout": 1,
        "unavailable": 1,
        "misconfigured": 0,
        "invalid_request": 0,
        "context_too_large": 0,
        "interrupted": 1,
        "cancelled": 0,
        "skipped_cooldown": 2,
        "skipped_breaker": 1,
        "skipped_quota": 1,
        "success_rate": 0.5,
        # Successful calls only: 100, 200, 300, 400 ms.
        "latency_p50_ms": 250.0,
        "latency_p95_ms": pytest.approx(385.0),
    }
    gemini = by_name(report)[f"gemini/{GEMINI}"]["statistics"]
    assert (gemini["calls"], gemini["invalid_request"], gemini["success_rate"]) == (1, 1, 0.0)
    assert gemini["latency_p50_ms"] is None


async def test_longer_period_includes_older_rows(
    settings: Settings, admin_key: str, database_url: str, usage_rows: FetchUsageRows
) -> None:
    await seed(
        database_url,
        row("groq", GROQ, "success", latency_ms=100),
        row("groq", GROQ, "success", latency_ms=300, age=dt.timedelta(days=2)),
        row("groq", GROQ, "success", latency_ms=900, age=dt.timedelta(days=8)),
    )

    week = by_name(await get_targets(settings, admin_key, "7d"))[f"groq/{GROQ}"]
    month = by_name(await get_targets(settings, admin_key, "30d"))[f"groq/{GROQ}"]

    assert week["statistics"]["success"] == 2
    assert week["statistics"]["latency_p50_ms"] == 200.0
    assert month["statistics"]["success"] == 3
    assert month["statistics"]["latency_p50_ms"] == 300.0


async def test_removed_model_is_still_listed_from_its_usage_rows(
    settings: Settings, admin_key: str, database_url: str, usage_rows: FetchUsageRows
) -> None:
    await seed(
        database_url,
        row("groq", "old-model", "success", latency_ms=120),
        row("groq", "old-model", "rate_limited", latency_ms=40),
        # Only cache hits in the period: no call, not listed.
        row("groq", "older-model", "cache_hit", latency_ms=5),
        # Before the period: not listed.
        row("groq", "oldest-model", "success", age=dt.timedelta(days=3)),
    )

    report = await get_targets(settings, admin_key)

    assert [f"{item['provider']}/{item['model']}" for item in report["targets"]] == [
        f"groq/{GROQ}",
        f"gemini/{GEMINI}",
        f"ollama/{OLLAMA}",
        "groq/old-model",
    ]
    removed = by_name(report)["groq/old-model"]
    assert removed["configured"] is False
    assert removed["live"] is None
    assert removed["statistics"]["calls"] == 2
    assert removed["statistics"]["success_rate"] == 0.5


async def test_a_request_refused_before_the_call_is_not_a_call(
    settings: Settings, admin_key: str, database_url: str, usage_rows: FetchUsageRows
) -> None:
    await seed(
        database_url,
        # The router found the prompt larger than the target TPM: no call was made.
        row("groq", GROQ, "context_too_large"),
        # The provider itself answered that the request is too large: a real call.
        row("groq", GROQ, "context_too_large", latency_ms=70),
        row("groq", GROQ, "skipped_quota"),
    )

    statistics = by_name(await get_targets(settings, admin_key))[f"groq/{GROQ}"]["statistics"]

    assert statistics["calls"] == 1
    assert statistics["context_too_large"] == 2
    assert statistics["skipped_quota"] == 1


async def test_live_state_of_an_idle_target(
    settings: Settings, admin_key: str, usage_rows: FetchUsageRows
) -> None:
    report = await get_targets(settings, admin_key)

    groq = by_name(report)[f"groq/{GROQ}"]["live"]
    resets_at = dt.datetime.fromisoformat(groq["rpd"].pop("resets_at"))
    assert groq == {
        "status": "known",
        "cooldown": {"active": False, "until": None},
        "breaker": {"state": "closed", "open_until": None, "trial_running": False},
        "rpm": {"used": 0, "limit": 30},
        "tpm": {"used": 0, "limit": 8000},
        "rpd": {"used": 0, "limit": 1000},
    }
    # Groq resets its daily quota at 00:00 UTC (the default).
    tomorrow = (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).date()
    assert resets_at == dt.datetime.combine(tomorrow, dt.time(0, 0), tzinfo=dt.UTC)
    ollama = by_name(report)[f"ollama/{OLLAMA}"]["live"]
    assert ollama["rpm"]["limit"] is None
    assert ollama["tpm"]["limit"] is None
    assert ollama["rpd"]["limit"] is None


async def test_live_state_shows_the_quotas_used_now(
    settings: Settings,
    admin_key: str,
    config: GatewayConfig,
    gate: TargetGate,
    usage_rows: FetchUsageRows,
) -> None:
    groq = target(config, f"groq/{GROQ}")
    first = await gate.acquire(groq, estimated_tokens=100, attempt_timeout=30)
    second = await gate.acquire(groq, estimated_tokens=250, attempt_timeout=30)
    assert isinstance(first, Reservation) and isinstance(second, Reservation)
    await gate.record_success(groq, first, used_tokens=40)  # 100 reserved, 40 used
    await gate.record_failure(groq, second, keep_tokens=False, provider_failed=True)  # released
    gemini = target(config, f"gemini/{GEMINI}")
    assert isinstance(
        await gate.acquire(gemini, estimated_tokens=10, attempt_timeout=30), Reservation
    )

    report = await get_targets(settings, admin_key)

    groq_live = by_name(report)[f"groq/{GROQ}"]["live"]
    assert groq_live["rpm"] == {"used": 2, "limit": 30}
    assert groq_live["tpm"] == {"used": 40, "limit": 8000}
    assert groq_live["rpd"]["used"] == 2
    gemini_live = by_name(report)[f"gemini/{GEMINI}"]["live"]
    assert gemini_live["rpm"] == {"used": 1, "limit": 10}
    assert gemini_live["rpd"]["used"] == 1
    # Gemini resets its daily quota at midnight in Los Angeles.
    resets_at = dt.datetime.fromisoformat(gemini_live["rpd"]["resets_at"])
    assert resets_at.astimezone(ZoneInfo("America/Los_Angeles")).time() == dt.time(0, 0)


async def test_live_state_shows_a_cooldown_after_a_429(
    settings: Settings,
    admin_key: str,
    config: GatewayConfig,
    gate: TargetGate,
    usage_rows: FetchUsageRows,
) -> None:
    gemini = target(config, f"gemini/{GEMINI}")
    reservation = await gate.acquire(gemini, estimated_tokens=10, attempt_timeout=30)
    assert isinstance(reservation, Reservation)
    await gate.record_rate_limited(gemini, reservation, retry_after=120)

    report = await get_targets(settings, admin_key)

    cooldown = by_name(report)[f"gemini/{GEMINI}"]["live"]["cooldown"]
    assert cooldown["active"] is True
    until = dt.datetime.fromisoformat(cooldown["until"])
    assert until.utcoffset() == dt.timedelta(0)
    assert 115 < (until - dt.datetime.now(dt.UTC)).total_seconds() <= 120
    assert by_name(report)[f"groq/{GROQ}"]["live"]["cooldown"]["active"] is False


async def test_live_state_shows_an_open_breaker(
    settings: Settings,
    admin_key: str,
    config: GatewayConfig,
    gate: TargetGate,
    usage_rows: FetchUsageRows,
) -> None:
    ollama = target(config, f"ollama/{OLLAMA}")
    for _ in range(2):  # 2 failures within the window open the breaker
        reservation = await gate.acquire(ollama, estimated_tokens=10, attempt_timeout=30)
        assert isinstance(reservation, Reservation)
        await gate.record_failure(ollama, reservation, keep_tokens=False, provider_failed=True)

    report = await get_targets(settings, admin_key)

    breaker = by_name(report)[f"ollama/{OLLAMA}"]["live"]["breaker"]
    assert breaker["state"] == "open"
    assert breaker["trial_running"] is False
    open_until = dt.datetime.fromisoformat(breaker["open_until"])
    assert 25 < (open_until - dt.datetime.now(dt.UTC)).total_seconds() <= 30


async def test_live_state_shows_a_half_open_breaker_and_its_trial(
    write_config: WriteConfig, admin_key: str, redis_url: str, usage_rows: FetchUsageRows
) -> None:
    # The breaker opens after 1 failure and stays open 0.1 s only.
    settings = write_config(
        TARGETS_CONFIG.replace("open: 30", "open: 0.1").replace("failures: 2", "failures: 1")
    )
    config = load_config(settings.gateway_config_path, os.environ)
    redis = Redis.from_url(redis_url)
    gate = TargetGate(redis, config.cooldown, config.breaker)
    groq = target(config, f"groq/{GROQ}")
    reservation = await gate.acquire(groq, estimated_tokens=10, attempt_timeout=30)
    assert isinstance(reservation, Reservation)
    await gate.record_failure(groq, reservation, keep_tokens=False, provider_failed=True)
    await asyncio.sleep(0.2)  # the breaker is now half-open

    waiting = by_name(await get_targets(settings, admin_key))[f"groq/{GROQ}"]["live"]["breaker"]
    trial = await gate.acquire(groq, estimated_tokens=10, attempt_timeout=30)
    assert isinstance(trial, Reservation) and trial.is_trial
    testing = by_name(await get_targets(settings, admin_key))[f"groq/{GROQ}"]["live"]["breaker"]
    await redis.aclose()

    assert waiting == {"state": "half_open", "open_until": None, "trial_running": False}
    assert testing == {"state": "half_open", "open_until": None, "trial_running": True}


async def test_reading_the_live_state_writes_nothing_to_redis(
    settings: Settings,
    admin_key: str,
    config: GatewayConfig,
    gate: TargetGate,
    redis_url: str,
    usage_rows: FetchUsageRows,
) -> None:
    groq = target(config, f"groq/{GROQ}")
    assert isinstance(
        await gate.acquire(groq, estimated_tokens=10, attempt_timeout=30), Reservation
    )
    redis = Redis.from_url(redis_url)
    before = {key: await redis.dump(key) for key in await redis.keys("*")}

    await get_targets(settings, admin_key)

    after = {key: await redis.dump(key) for key in await redis.keys("*")}
    await redis.aclose()
    assert after == before


async def test_live_state_is_unknown_when_redis_is_down(
    settings: Settings, admin_key: str, database_url: str, usage_rows: FetchUsageRows
) -> None:
    await seed(database_url, row("groq", GROQ, "success", latency_ms=100))
    redis_down = settings.model_copy(update={"redis_url": UNREACHABLE_REDIS})

    report = await get_targets(redis_down, admin_key)

    groq = by_name(report)[f"groq/{GROQ}"]
    assert groq["statistics"]["success"] == 1
    live = groq["live"]
    assert live["status"] == "unknown"
    assert live["cooldown"] is None
    assert live["breaker"] is None
    assert live["rpm"] == {"used": None, "limit": 30}
    assert live["tpm"] == {"used": None, "limit": 8000}
    assert live["rpd"]["used"] is None
    assert live["rpd"]["limit"] == 1000
    assert all(item["live"]["status"] == "unknown" for item in report["targets"])


@pytest.mark.parametrize("period", ["1y", "", "24H"])
async def test_targets_refuses_an_unknown_period(
    settings: Settings, admin_key: str, period: str
) -> None:
    async with admin_client(settings, admin_key) as client:
        response = await client.get("/admin/v1/targets", params={"period": period})

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "period"


async def test_targets_needs_an_admin_key(settings: Settings) -> None:
    async with admin_client(settings, None) as client:
        response = await client.get("/admin/v1/targets")

    assert response.status_code == 401
