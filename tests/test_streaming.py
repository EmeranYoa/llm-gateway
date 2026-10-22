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
from tests.conftest import live_gateway
from tests.upstream import (
    CHAT_CONFIG,
    CHAT_REQUEST,
    GROQ_KEY,
    GROQ_URL,
    chunk,
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
