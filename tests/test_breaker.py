"""Tests for the circuit breaker: closed -> open -> half-open -> closed or open."""

import asyncio
from collections.abc import AsyncIterator

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
    completion_body,
)

# The breaker opens after 3 failures within 60 s, and stays open 0.5 s.
BREAKER_CONFIG = """
gateway:
  breaker: { failures: 3, window: 60, open: 0.5 }
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      llama-3.3-70b-versatile: { timeout: 0.5 }
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: GEMINI_API_KEY
    models:
      gemini-2.5-flash: {}
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile, gemini/gemini-2.5-flash ]
"""


@pytest.fixture
async def client(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> AsyncIterator[AsyncClient]:
    """A gateway routing to Groq, then Gemini. Gemini always answers."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))
    async with make_client(BREAKER_CONFIG) as http_client:
        yield http_client


async def send(client: AsyncClient, times: int = 1) -> None:
    for _ in range(times):
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)


async def test_breaker_opens_after_too_many_failures(
    client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(500)

    await send(client, times=3)  # 3 failures: the breaker opens
    await send(client)

    assert groq.call_count == 3
    rows = await usage_rows()
    assert [row["outcome"] for row in rows if row["provider"] == "groq"][-1] == "skipped_breaker"


def responses(*statuses: int) -> list[httpx.Response]:
    """Groq answers, in order: an HTTP status, or 200 with a completion."""
    return [
        httpx.Response(200, json=completion_body("llama-3.3-70b-versatile"))
        if status == 200
        else httpx.Response(status, headers={"Retry-After": "0"} if status == 429 else {})
        for status in statuses
    ]


async def open_breaker(client: AsyncClient) -> None:
    """Send the 3 failing requests that open the breaker, then wait until it is half-open."""
    await send(client, times=3)
    await asyncio.sleep(0.6)


async def test_successful_trial_closes_the_breaker(
    client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=responses(500, 500, 500, 200, 200))

    await open_breaker(client)
    await send(client)  # the trial succeeds: closed
    await send(client)

    assert groq.call_count == 5


async def test_failed_trial_opens_the_breaker_again(
    client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=responses(500, 500, 500, 500, 200))

    await open_breaker(client)
    await send(client)  # the trial fails: open again
    await send(client)
    assert groq.call_count == 4

    await asyncio.sleep(0.6)
    await send(client)  # half-open again: a new trial
    assert groq.call_count == 5


async def test_half_open_breaker_lets_exactly_one_trial_through(
    client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    async def slow_success(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, json=completion_body("llama-3.3-70b-versatile"))

    groq = respx_mock.post(GROQ_URL).mock(side_effect=responses(500, 500, 500))
    await open_breaker(client)
    groq.mock(side_effect=slow_success)
    groq.reset()

    responses_ = await asyncio.gather(
        *(client.post("/v1/chat/completions", json=CHAT_REQUEST) for _ in range(10))
    )

    assert groq.call_count == 1
    providers = sorted(response.headers["X-Gateway-Provider"] for response in responses_)
    assert providers == ["gemini"] * 9 + ["groq"]


async def test_neutral_trial_frees_the_slot_and_keeps_the_breaker_half_open(
    client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=responses(500, 500, 500, 429, 500, 200))

    await open_breaker(client)
    await send(client)  # the trial gets a 429 (with a near-zero cooldown): neutral
    await asyncio.sleep(0.05)
    await send(client)  # the slot is free: a new trial, which fails and opens the breaker
    assert groq.call_count == 5, "a neutral trial must free the trial slot"

    await send(client)
    assert groq.call_count == 5, "one failed trial must open the breaker: it was half-open"


async def test_client_error_on_trial_counts_as_success(
    client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=responses(500, 500, 500, 400, 500, 200))

    await open_breaker(client)
    await send(client)  # the provider answered a client error: it works, closed
    await send(client)  # one failure: not enough to open a closed breaker
    await send(client)

    assert groq.call_count == 6


async def test_trial_slot_frees_itself_when_the_trial_never_reports_back(
    client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    trial_started = asyncio.Event()

    async def hanging_call(_: httpx.Request) -> httpx.Response:
        trial_started.set()
        await asyncio.sleep(10)
        raise AssertionError("the trial call is cancelled before it ends")

    groq = respx_mock.post(GROQ_URL).mock(side_effect=responses(500, 500, 500))
    await open_breaker(client)
    groq.mock(side_effect=[hanging_call, *responses(200)])

    # The trial starts, then its gateway instance "dies": it never reports an outcome.
    trial = asyncio.create_task(client.post("/v1/chat/completions", json=CHAT_REQUEST))
    await asyncio.wait_for(trial_started.wait(), timeout=1)
    trial.cancel()
    await asyncio.gather(trial, return_exceptions=True)
    # respx only counts calls that got a response: the cancelled trial is not counted.
    assert groq.call_count == 3

    await send(client)
    assert groq.call_count == 3, "the trial slot is still held"
    await asyncio.sleep(0.5)  # the slot TTL is the attempt timeout: 0.5 s
    await send(client)
    assert groq.call_count == 4, "the trial slot must free itself"
