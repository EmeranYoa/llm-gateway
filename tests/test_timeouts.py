"""Tests for attempt timeouts and the request deadline.

Durations are kept small (well under a second) so the tests stay fast.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest
import respx
from httpx import AsyncClient

from tests.conftest import ClientFactory
from tests.upstream import (
    CHAT_REQUEST,
    GEMINI_KEY,
    GEMINI_URL,
    GROQ_KEY,
    GROQ_URL,
    completion_body,
)

TimeoutClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


def timeout_config(
    *, deadline: float, min_attempt_time: float, groq_timeout: float, gemini_timeout: float
) -> str:
    """A config routing `chat-fast` to Groq, then Gemini, with the given durations."""
    return f"""
gateway:
  deadline: {deadline}
  min_attempt_time: {min_attempt_time}
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      llama-3.3-70b-versatile: {{ timeout: {groq_timeout} }}
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: GEMINI_API_KEY
    models:
      gemini-2.5-flash: {{ timeout: {gemini_timeout} }}
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile, gemini/gemini-2.5-flash ]
"""


@pytest.fixture
def timeout_client(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> TimeoutClientFactory:
    """Build a client for a gateway started with `timeout_config(**durations)`."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)

    @asynccontextmanager
    async def _make(**durations: float) -> AsyncIterator[AsyncClient]:
        async with make_client(timeout_config(**durations)) as http_client:
            yield http_client

    return _make


def slow_upstream(delay: float, model: str) -> Callable[[httpx.Request], Awaitable[httpx.Response]]:
    """A respx side effect that answers successfully, but only after `delay` seconds."""

    async def _answer(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delay)
        return httpx.Response(200, json=completion_body(model))

    return _answer


async def test_upstream_slower_than_model_timeout_fails_over(
    timeout_client: TimeoutClientFactory, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=slow_upstream(1.0, "llama-3.3-70b-versatile"))
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    async with timeout_client(
        deadline=5, min_attempt_time=0.01, groq_timeout=0.05, gemini_timeout=5
    ) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "gemini"
    assert response.headers["X-Gateway-Fallbacks"] == "1"


async def test_targets_that_time_out_are_reported_as_timeouts(
    timeout_client: TimeoutClientFactory, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=slow_upstream(1.0, "llama-3.3-70b-versatile"))
    respx_mock.post(GEMINI_URL).mock(side_effect=httpx.ReadTimeout("read timed out"))

    async with timeout_client(
        deadline=5, min_attempt_time=0.01, groq_timeout=0.05, gemini_timeout=1
    ) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 503
    assert response.json()["error"]["message"] == (
        "All targets of alias 'chat-fast' failed: "
        "groq/llama-3.3-70b-versatile: timeout; "
        "gemini/gemini-2.5-flash: timeout"
    )


async def test_each_attempt_gets_the_smaller_of_model_timeout_and_remaining_deadline(
    timeout_client: TimeoutClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(503)
    gemini = respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    async with timeout_client(
        deadline=0.5, min_attempt_time=0.01, groq_timeout=30, gemini_timeout=0.2
    ) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    groq_timeout = groq.calls.last.request.extensions["timeout"]
    gemini_timeout = gemini.calls.last.request.extensions["timeout"]
    # Groq is limited by the remaining deadline, Gemini by its own model timeout.
    assert 0.3 < groq_timeout["read"] <= 0.5
    assert gemini_timeout["read"] == 0.2
    # The timeout applies to every phase of the HTTP call, not only to reads.
    assert set(groq_timeout.values()) == {groq_timeout["read"]}


async def test_deadline_exceeded_returns_504_in_openai_format(
    timeout_client: TimeoutClientFactory, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(429)
    respx_mock.post(GEMINI_URL).mock(side_effect=slow_upstream(1.0, "gemini-2.5-flash"))

    async with timeout_client(
        deadline=0.1, min_attempt_time=0.01, groq_timeout=30, gemini_timeout=30
    ) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 504
    assert response.json() == {
        "error": {
            "message": "Alias 'chat-fast' could not be served within the gateway deadline "
            "of 0.1 s: "
            "groq/llama-3.3-70b-versatile: rate limited; "
            "gemini/gemini-2.5-flash: timeout",
            "type": "api_error",
            "param": None,
            "code": "deadline_exceeded",
        }
    }


async def test_no_new_attempt_starts_when_too_little_time_remains(
    timeout_client: TimeoutClientFactory, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=slow_upstream(1.0, "llama-3.3-70b-versatile"))
    gemini = respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    # Groq times out after 0.15 s, which leaves less than `min_attempt_time` for Gemini.
    async with timeout_client(
        deadline=0.3, min_attempt_time=0.2, groq_timeout=0.15, gemini_timeout=30
    ) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 504
    assert response.json()["error"]["message"] == (
        "Alias 'chat-fast' could not be served within the gateway deadline of 0.3 s: "
        "groq/llama-3.3-70b-versatile: timeout"
    )
    assert not gemini.called
