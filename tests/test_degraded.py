"""Tests for degraded mode: the gateway keeps routing when Redis is unavailable."""

import asyncio
import logging
import time
from collections.abc import Callable

import pytest
import respx
from redis.asyncio import Redis

from app.config import Settings
from tests.conftest import FetchUsageRows, gateway_client
from tests.upstream import (
    CHAT_REQUEST,
    FAILOVER_CONFIG,
    GEMINI_KEY,
    GEMINI_URL,
    GROQ_KEY,
    GROQ_URL,
    completion_body,
)

WriteConfig = Callable[[str], Settings]

# Nothing listens on port 1: connections are refused at once.
UNREACHABLE_REDIS = "redis://127.0.0.1:1/0"


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)


def settings_with_redis(write_config: WriteConfig, redis_url: str) -> Settings:
    return write_config(FAILOVER_CONFIG).model_copy(update={"redis_url": redis_url})


async def test_requests_are_served_with_failover_when_redis_is_down(
    write_config: WriteConfig,
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx_mock.post(GROQ_URL).respond(500)
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    with caplog.at_level(logging.WARNING):
        async with gateway_client(settings_with_redis(write_config, UNREACHABLE_REDIS)) as client:
            response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "gemini"
    rows = await usage_rows()
    assert [(row["outcome"], row["degraded"]) for row in rows] == [
        ("unavailable", True),
        ("success", True),
    ]
    assert any("Redis is unavailable" in message for message in caplog.messages)


async def test_a_redis_that_does_not_answer_is_detected_quickly(
    write_config: WriteConfig, respx_mock: respx.MockRouter, silent_server: int
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    settings = settings_with_redis(write_config, f"redis://127.0.0.1:{silent_server}/0")

    async with gateway_client(settings) as client:
        started = time.perf_counter()
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        elapsed = time.perf_counter() - started

    # The Redis timeout is 250 ms by default; Redis is not tried again for the same request.
    assert response.status_code == 200
    assert elapsed < 1.0


async def test_health_reports_degraded_when_redis_is_down(write_config: WriteConfig) -> None:
    async with gateway_client(settings_with_redis(write_config, UNREACHABLE_REDIS)) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["redis"] == "down"


async def test_health_reports_ok_when_redis_is_up(
    write_config: WriteConfig, redis_url: str
) -> None:
    async with gateway_client(settings_with_redis(write_config, redis_url)) as client:
        response = await client.get("/health")

    assert response.json()["status"] == "ok"
    assert response.json()["redis"] == "up"


async def test_normal_routing_comes_back_when_redis_answers_again(
    write_config: WriteConfig,
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
    redis_url: str,
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    admin = Redis.from_url(redis_url)

    async with gateway_client(settings_with_redis(write_config, redis_url)) as client:
        await admin.execute_command("CLIENT", "PAUSE", 700, "ALL")  # Redis hangs for 0.7 s
        during = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await asyncio.sleep(0.8)
        after = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        health = await client.get("/health")
    await admin.aclose()

    assert during.status_code == after.status_code == 200
    assert [row["degraded"] for row in await usage_rows()] == [True, False]
    assert health.json()["status"] == "ok"
