"""Tests for the daily token budget of each tenant, reset at midnight UTC."""

import asyncio
import datetime as dt
import math
from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest
import respx

from app.config import Settings
from tests.conftest import gateway_client, new_api_key, run_admin, run_admin_command
from tests.test_tenant_quotas import created_key, tenant_config
from tests.upstream import (
    CHAT_CONFIG,
    CHAT_REQUEST,
    GROQ_KEY,
    GROQ_URL,
    completion_body,
    error_body,
)

WriteConfig = Callable[[str], Settings]

# Nothing listens on port 1: connections are refused at once.
UNREACHABLE_REDIS = "redis://127.0.0.1:1/0"


def chat_request(max_tokens: int) -> dict[str, object]:
    """The chat request with the given `max_tokens`.

    Its prompt is estimated at 2 tokens: "user" and "Hi" are 6 characters.
    """
    return {**CHAT_REQUEST, "max_tokens": max_tokens}


def seconds_until_midnight_utc() -> float:
    now = dt.datetime.now(dt.UTC)
    midnight = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(), tzinfo=dt.UTC)
    return (midnight - now).total_seconds()


@pytest.fixture(autouse=True)
def groq(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> respx.Route:
    """A fake Groq that answers every chat completion, reporting a usage of 7 tokens."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    return respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))


async def test_request_larger_than_the_remaining_budget_gets_429_until_midnight_utc(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    async with gateway_client(write_config(tenant_config("tokens_per_day: 100"))) as client:
        response = await client.post("/v1/chat/completions", json=chat_request(200))
    expected_wait = seconds_until_midnight_utc()

    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "tenant_quota_exceeded"
    assert error["type"] == "rate_limit_error"
    assert "daily token budget" in error["message"]
    assert "max_tokens" in error["message"]
    # The budget resets at the next midnight UTC: the client may come back then.
    assert abs(int(response.headers["Retry-After"]) - math.ceil(expected_wait)) <= 2
    assert groq.call_count == 0


async def test_a_request_refused_by_the_budget_does_not_count_in_the_rpm(
    write_config: WriteConfig,
) -> None:
    config = tenant_config("rpm: 1, tokens_per_day: 100")

    async with gateway_client(write_config(config)) as client:
        too_large = await client.post("/v1/chat/completions", json=chat_request(200))
        small = await client.post("/v1/chat/completions", json=chat_request(10))
        over_rpm = await client.post("/v1/chat/completions", json=chat_request(10))

    assert [too_large.status_code, small.status_code, over_rpm.status_code] == [429, 200, 429]
    assert "daily token budget" in too_large.json()["error"]["message"]
    assert "requests per minute" in over_rpm.json()["error"]["message"]


async def test_the_reservation_is_corrected_with_the_real_usage(write_config: WriteConfig) -> None:
    # Each request reserves 2 + 600 tokens; the provider reports a usage of 7 tokens.
    async with gateway_client(write_config(tenant_config("tokens_per_day: 1000"))) as client:
        statuses = [
            (await client.post("/v1/chat/completions", json=chat_request(600))).status_code
            for _ in range(3)
        ]

    assert statuses == [200, 200, 200]


async def test_the_estimate_stays_reserved_when_the_provider_reports_no_usage(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    body = completion_body("llama-3.3-70b-versatile")
    del body["usage"]
    groq.respond(json=body)

    async with gateway_client(write_config(tenant_config("tokens_per_day: 1000"))) as client:
        first = await client.post("/v1/chat/completions", json=chat_request(600))
        second = await client.post("/v1/chat/completions", json=chat_request(600))

    assert [first.status_code, second.status_code] == [200, 429]


@pytest.mark.parametrize(
    ("upstream_status", "gateway_status"),
    [(500, 503), (400, 400)],
)
async def test_the_reservation_is_released_when_the_request_fails(
    write_config: WriteConfig, groq: respx.Route, upstream_status: int, gateway_status: int
) -> None:
    groq.side_effect = [
        httpx.Response(upstream_status, json=error_body("failed")),
        httpx.Response(200, json=completion_body("llama-3.3-70b-versatile")),
    ]

    async with gateway_client(write_config(tenant_config("tokens_per_day: 1000"))) as client:
        failed = await client.post("/v1/chat/completions", json=chat_request(600))
        next_one = await client.post("/v1/chat/completions", json=chat_request(600))

    assert [failed.status_code, next_one.status_code] == [gateway_status, 200]


async def test_the_reservation_is_kept_when_the_last_attempt_timed_out(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    # The provider may have generated the tokens before the gateway stopped waiting.
    groq.side_effect = [
        httpx.ReadTimeout("read timed out"),
        httpx.Response(200, json=completion_body("llama-3.3-70b-versatile")),
    ]

    async with gateway_client(write_config(tenant_config("tokens_per_day: 1000"))) as client:
        timed_out = await client.post("/v1/chat/completions", json=chat_request(600))
        next_one = await client.post("/v1/chat/completions", json=chat_request(600))

    assert [timed_out.status_code, next_one.status_code] == [503, 429]


async def test_concurrent_requests_of_a_tenant_never_over_book_its_budget(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    body = completion_body("llama-3.3-70b-versatile")
    del body["usage"]  # every estimate stays reserved
    groq.respond(json=body)

    # Room for exactly three requests of 2 + 600 tokens.
    async with gateway_client(write_config(tenant_config("tokens_per_day: 1806"))) as client:
        responses = await asyncio.gather(
            *(client.post("/v1/chat/completions", json=chat_request(600)) for _ in range(10))
        )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200] * 3 + [429] * 7
    assert groq.call_count == 3


async def test_each_tenant_has_its_own_budget(write_config: WriteConfig, database_url: str) -> None:
    other_tenant = {"Authorization": f"Bearer {await new_api_key(database_url)}"}

    async with gateway_client(write_config(tenant_config("tokens_per_day: 1000"))) as client:
        first = await client.post("/v1/chat/completions", json=chat_request(998))
        second = await client.post("/v1/chat/completions", json=chat_request(998))
        other = await client.post(
            "/v1/chat/completions", json=chat_request(998), headers=other_tenant
        )

    # The first request uses 7 tokens: 993 are left, not enough for 2 + 998.
    assert [first.status_code, second.status_code, other.status_code] == [200, 429, 200]


async def test_the_budget_is_not_checked_when_redis_is_down(write_config: WriteConfig) -> None:
    settings = write_config(tenant_config("tokens_per_day: 100"))
    settings = settings.model_copy(update={"redis_url": UNREACHABLE_REDIS})

    async with gateway_client(settings) as client:
        response = await client.post("/v1/chat/completions", json=chat_request(200))

    assert response.status_code == 200


async def test_budget_set_at_key_creation_overrides_the_default(
    write_config: WriteConfig, database_url: str
) -> None:
    key = await created_key(database_url, "--tokens-per-day", "100")

    # No default limit in the config: only the tenant's own budget applies.
    async with gateway_client(write_config(CHAT_CONFIG), api_key=key) as client:
        small = await client.post("/v1/chat/completions", json=chat_request(10))
        too_large = await client.post("/v1/chat/completions", json=chat_request(200))

    assert [small.status_code, too_large.status_code] == [200, 429]


async def test_set_limits_changes_the_budget_and_keeps_the_other_limits(
    write_config: WriteConfig, database_url: str
) -> None:
    tenant = f"tenant-{uuid4().hex[:8]}"
    key = await created_key(database_url, "--rpm", "1", tenant=tenant)

    await run_admin(database_url, "set-limits", "--tenant", tenant, "--tokens-per-day", "1000")

    config = tenant_config("tokens_per_day: 100")
    async with gateway_client(write_config(config), api_key=key) as client:
        within_budget = await client.post("/v1/chat/completions", json=chat_request(200))
        over_rpm = await client.post("/v1/chat/completions", json=chat_request(10))

    assert [within_budget.status_code, over_rpm.status_code] == [200, 429]
    assert "requests per minute" in over_rpm.json()["error"]["message"]


async def test_set_limits_needs_at_least_one_limit(database_url: str) -> None:
    tenant = f"tenant-{uuid4().hex[:8]}"
    await created_key(database_url, tenant=tenant)

    run = await run_admin_command(database_url, "set-limits", "--tenant", tenant)

    assert run.exit_code == 2
    assert "--tokens-per-day" in run.stderr
