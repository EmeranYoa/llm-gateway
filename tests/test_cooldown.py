"""Tests for the cooldown of rate-limited and misconfigured targets."""

import asyncio
import datetime as dt
import email.utils
from collections.abc import Callable

import httpx
import pytest
import respx
from httpx import AsyncClient

from tests.conftest import ClientFactory, FetchUsageRows
from tests.upstream import (
    CHAT_REQUEST,
    GEMINI_KEY,
    GEMINI_URL,
    GROQ_KEY,
    GROQ_URL,
    OLLAMA_URL,
    completion_body,
    error_body,
)


async def test_rate_limited_target_is_skipped_while_in_cooldown(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(429, headers={"Retry-After": "30"})
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)
    second = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert groq.call_count == 1
    assert second.status_code == 200
    assert second.headers["X-Gateway-Provider"] == "gemini"
    assert second.headers["X-Gateway-Fallbacks"] == "1"


async def test_503_retry_after_is_the_smallest_wait_among_blocked_targets(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(429, headers={"Retry-After": "30"})
    respx_mock.post(GEMINI_URL).mock(
        side_effect=[
            httpx.Response(200, json=completion_body("gemini-2.5-flash")),
            httpx.Response(429, headers={"Retry-After": "10"}),
        ]
    )
    respx_mock.post(OLLAMA_URL).respond(503)

    await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)
    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    # Groq is still in cooldown (about 30 s), Gemini asks for 10 s, Ollama gives no delay.
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "10"
    assert "groq/llama-3.3-70b-versatile: cooldown" in response.json()["error"]["message"]


async def test_503_has_no_retry_after_when_no_wait_is_known(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    for url in (GROQ_URL, GEMINI_URL, OLLAMA_URL):
        respx_mock.post(url).respond(503)

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 503
    assert "Retry-After" not in response.headers


def cooldown_config(*, initial: float, maximum: float, misconfigured: float = 600) -> str:
    """A config routing `chat-fast` to Groq, then Gemini, with the given cooldowns."""
    return f"""
gateway:
  cooldown: {{ initial: {initial}, max: {maximum}, misconfigured: {misconfigured} }}
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      llama-3.3-70b-versatile: {{}}
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: GEMINI_API_KEY
    models:
      gemini-2.5-flash: {{}}
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile, gemini/gemini-2.5-flash ]
"""


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)


@pytest.mark.usefixtures("keys")
async def test_cooldown_without_retry_delay_doubles_and_is_capped(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(429)
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    async with make_client(cooldown_config(initial=0.5, maximum=0.8)) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)  # cooldown 0.5 s
        await asyncio.sleep(0.6)
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)  # cooldown min(1.0, 0.8)
        assert groq.call_count == 2

        await asyncio.sleep(0.65)
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        assert groq.call_count == 2, "the second cooldown must be longer than the first"

        await asyncio.sleep(0.25)
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        assert groq.call_count == 3, "the second cooldown must be capped at 0.8 s"


@pytest.mark.usefixtures("keys")
async def test_success_resets_the_progressive_cooldown(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json=completion_body("llama-3.3-70b-versatile")),
            httpx.Response(429),
            httpx.Response(200, json=completion_body("llama-3.3-70b-versatile")),
        ]
    )
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    async with make_client(cooldown_config(initial=0.5, maximum=10)) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)  # 429, cooldown 0.5 s
        await asyncio.sleep(0.6)
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)  # success
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)  # 429, cooldown 0.5 s again
        await asyncio.sleep(0.6)
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert groq.call_count == 4
    assert response.headers["X-Gateway-Provider"] == "groq"


@pytest.mark.usefixtures("keys")
async def test_misconfigured_target_gets_its_own_cooldown(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(401, json=error_body("Invalid API Key"))
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))
    config = cooldown_config(initial=60, maximum=3600, misconfigured=0.5)

    async with make_client(config) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        skipped = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        assert groq.call_count == 1
        await asyncio.sleep(0.6)
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert skipped.headers["X-Gateway-Provider"] == "gemini"
    assert groq.call_count == 2


SINGLE_TARGET_CONFIG = """
gateway:
  cooldown: { initial: 45 }
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      llama-3.3-70b-versatile: {}
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile ]
"""


def http_date_in(seconds: float) -> str:
    return email.utils.format_datetime(
        dt.datetime.now(dt.UTC) + dt.timedelta(seconds=seconds), usegmt=True
    )


@pytest.mark.parametrize(
    ("headers", "expected_retry_after"),
    [
        ({"Retry-After": "7"}, {7}),
        # Built when the test runs, not when tests are collected.
        (lambda: {"Retry-After": http_date_in(20)}, {19, 20, 21}),
        (
            {
                "x-ratelimit-remaining-requests": "0",
                "x-ratelimit-reset-requests": "2m59.56s",
                "x-ratelimit-remaining-tokens": "5000",
                "x-ratelimit-reset-tokens": "7.66s",
            },
            {180},
        ),
        (
            {
                "x-ratelimit-remaining-requests": "10",
                "x-ratelimit-reset-requests": "1h",
                "x-ratelimit-remaining-tokens": "0",
                "x-ratelimit-reset-tokens": "7.66s",
            },
            {8},
        ),
        ({"x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "250ms"}, {1}),
        ({}, {45}),
    ],
    ids=[
        "retry-after-seconds",
        "retry-after-http-date",
        "requests-exhausted",
        "tokens-exhausted",
        "milliseconds",
        "no-retry-information",
    ],
)
@pytest.mark.usefixtures("keys")
async def test_cooldown_follows_the_retry_information_of_the_provider(
    make_client: ClientFactory,
    respx_mock: respx.MockRouter,
    headers: dict[str, str] | Callable[[], dict[str, str]],
    expected_retry_after: set[int],
) -> None:
    respx_mock.post(GROQ_URL).respond(429, headers=headers() if callable(headers) else headers)

    async with make_client(SINGLE_TARGET_CONFIG) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 503
    assert int(response.headers["Retry-After"]) in expected_retry_after


async def test_skipped_target_is_logged_as_skipped_cooldown(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).respond(429, headers={"Retry-After": "30"})
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))
    await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    request_id = response.headers["X-Gateway-Request-Id"]
    rows = [row for row in await usage_rows() if row["request_id"] == request_id]
    assert [(row["provider"], row["attempt_index"], row["outcome"]) for row in rows] == [
        ("groq", 0, "skipped_cooldown"),
        ("gemini", 1, "success"),
    ]
    skipped = rows[0]
    assert skipped["latency_ms"] is None
    assert skipped["status_code"] is None
    assert skipped["error_message"].startswith("cooldown (")
