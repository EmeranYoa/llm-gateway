"""Tests for streamed chat completions (`stream: true`, Server-Sent Events)."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.config import Settings
from tests.conftest import ClientFactory, live_gateway
from tests.upstream import (
    CHAT_CONFIG,
    CHAT_REQUEST,
    FAILOVER_CONFIG,
    GEMINI_KEY,
    GEMINI_URL,
    GROQ_KEY,
    GROQ_URL,
    OLLAMA_URL,
    chunk,
    completion_body,
    error_body,
    sse,
    stream_response,
)

STREAM_REQUEST = {**CHAT_REQUEST, "stream": True}


async def read_stream(
    client: AsyncClient, body: dict[str, Any]
) -> tuple[httpx.Response, list[str]]:
    """Send a streamed request and return the response and the `data:` payloads it carried."""
    async with client.stream("POST", "/v1/chat/completions", json=body) as response:
        payloads = [
            line.removeprefix("data: ")
            async for line in response.aiter_lines()
            if line.startswith("data: ")
        ]
    return response, payloads


async def test_stream_is_relayed_in_openai_format(
    chat_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(
        return_value=stream_response(
            ": keep-alive comment",
            chunk(role="assistant", content=""),
            chunk("Hel"),
            chunk("lo"),
            "[DONE]",
        )
    )

    response, payloads = await read_stream(chat_client, STREAM_REQUEST)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-Gateway-Provider"] == "groq"
    assert response.headers["X-Gateway-Model"] == "llama-3.3-70b-versatile"
    assert response.headers["X-Gateway-Fallbacks"] == "0"
    assert payloads[-1] == "[DONE]"
    chunks = [json.loads(payload) for payload in payloads[:-1]]
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "Hello"
    # Like normal responses, `model` is the real configured model; other fields are unchanged.
    assert {c["model"] for c in chunks} == {"llama-3.3-70b-versatile"}
    assert {c["id"] for c in chunks} == {"chatcmpl-123"}


async def test_reasoning_reaches_the_client_before_the_answer(
    write_config: Callable[[str], Settings],
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.route(host="127.0.0.1").pass_through()  # the client talks to the live gateway
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    client_got_reasoning = asyncio.Event()

    async def upstream_body() -> AsyncIterator[bytes]:
        yield sse(chunk(role="assistant", content=""), chunk(reasoning="Let me think."))
        # Like a reasoning model: the answer only comes after some thinking.
        await asyncio.wait_for(client_got_reasoning.wait(), timeout=5)
        yield sse(chunk("Hello"), "[DONE]")

    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=upstream_body()
        )
    )

    async with (
        live_gateway(write_config(CHAT_CONFIG)) as client,
        client.stream("POST", "/v1/chat/completions", json=STREAM_REQUEST) as response,
    ):
        lines = response.aiter_lines()
        # Reasoning is output for the client: it is sent at once, not held back.
        reasoning = await asyncio.wait_for(next_event_with(lines, "reasoning"), timeout=2)
        client_got_reasoning.set()
        answer = await asyncio.wait_for(next_event_with(lines, "Hello"), timeout=2)

    assert "Let me think." in reasoning
    assert "Hello" in answer


async def next_event_with(lines: AsyncIterator[str], text: str) -> str:
    """Read stream lines until a `data:` line that contains `text`."""
    async for line in lines:
        if line.startswith("data: ") and text in line:
            return line
    raise AssertionError(f"the stream ended without {text!r}")


GEMINI_STREAM = (chunk(role="assistant", content=""), chunk("From Gemini"), "[DONE]")


@pytest.mark.parametrize(
    "groq_answer",
    [
        httpx.Response(429),
        httpx.Response(503),
        httpx.ConnectError("connection refused"),
        # Some providers answer 200, then send an error as the first event.
        stream_response({"error": {"code": 429, "message": "rate-limited upstream"}}),
        stream_response({"error": {"code": 502, "message": "upstream failed"}}),
    ],
    ids=["http-429", "http-503", "network-error", "error-event-429", "error-event-502"],
)
async def test_stream_fails_over_before_the_first_content(
    failover_client: AsyncClient,
    respx_mock: respx.MockRouter,
    groq_answer: httpx.Response | Exception,
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=[groq_answer])
    respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))

    response, payloads = await read_stream(failover_client, STREAM_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "gemini"
    assert response.headers["X-Gateway-Fallbacks"] == "1"
    assert payloads[-1] == "[DONE]"
    assert all("error" not in json.loads(payload) for payload in payloads[:-1])


async def test_stream_fails_over_when_the_first_content_comes_too_late(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    config = FAILOVER_CONFIG.replace(
        "llama-3.3-70b-versatile: {}", "llama-3.3-70b-versatile: { timeout: 0.3 }"
    )

    async def slow_body() -> AsyncIterator[bytes]:
        yield sse(chunk(role="assistant", content=""))
        await asyncio.sleep(2)  # the first content comes after the model timeout
        yield sse(chunk("Too late"), "[DONE]")

    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=slow_body()
        )
    )
    respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))

    async with make_client(config) as client:
        response, _ = await read_stream(client, STREAM_REQUEST)

    assert response.headers["X-Gateway-Provider"] == "gemini"


async def test_stream_that_no_target_can_serve_gets_a_json_error(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    for url in (GROQ_URL, GEMINI_URL, OLLAMA_URL):
        respx_mock.post(url).respond(503)

    response = await failover_client.post("/v1/chat/completions", json=STREAM_REQUEST)

    # Nothing was streamed yet, so the client gets the usual error, not a stream.
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "all_targets_failed"


async def test_stream_with_an_invalid_request_is_not_failed_over(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(400, json=error_body("'temperature' must be <= 2"))
    gemini = respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))

    response = await failover_client.post("/v1/chat/completions", json=STREAM_REQUEST)

    assert response.status_code == 400
    assert not gemini.called


async def test_half_open_trial_ends_at_the_first_content_of_a_stream(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    # Breaker: open after 3 failures, half-open after 0.5 s. Trial slot TTL: 2 s.
    config = "gateway: { breaker: { failures: 3, window: 60, open: 0.5 } }\n" + (
        FAILOVER_CONFIG.replace(
            "llama-3.3-70b-versatile: {}", "llama-3.3-70b-versatile: { timeout: 2 }"
        )
    )
    trial_committed = asyncio.Event()
    other_request_done = asyncio.Event()

    async def long_trial_stream() -> AsyncIterator[bytes]:
        yield sse(chunk("Trial answer"))
        # The gateway asks for more only after its commit point, so it is recorded now.
        trial_committed.set()
        await asyncio.wait_for(other_request_done.wait(), timeout=5)
        yield sse("[DONE]")

    groq_answers = [
        *(httpx.Response(500) for _ in range(3)),
        httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=long_trial_stream()
        ),
        httpx.Response(200, json=completion_body("llama-3.3-70b-versatile")),
    ]
    respx_mock.post(GROQ_URL).mock(side_effect=groq_answers)
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    async with make_client(config) as client:
        for _ in range(3):  # three failures: the breaker opens
            await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await asyncio.sleep(0.6)  # half-open: the next call is the single trial
        trial = asyncio.create_task(read_stream(client, STREAM_REQUEST))
        await asyncio.wait_for(trial_committed.wait(), timeout=5)
        # The trial stream is still open, but it sent content: the breaker is closed,
        # so this request goes to Groq instead of being skipped by the breaker.
        other = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        other_request_done.set()
        await trial

    assert other.headers["X-Gateway-Provider"] == "groq"
