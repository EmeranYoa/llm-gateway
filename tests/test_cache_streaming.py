"""Tests for the response cache with streamed requests: replayed hits and stored streams."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from tests.conftest import gateway_client, live_gateway
from tests.test_cache import GROQ_MODEL, cache_config
from tests.test_streaming import (
    STREAM_REQUEST,
    failing_stream,
    held_open_stream,
    next_event_with,
    read_stream,
)
from tests.upstream import CHAT_REQUEST, GROQ_KEY, GROQ_URL, chunk, completion_body, sse

WriteConfig = Callable[[str], Settings]


@pytest.fixture(autouse=True)
def groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)


def finished(reason: str) -> dict[str, Any]:
    """The last chunk of a stream: no content, only why the answer ended."""
    return {**chunk(), "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


def usage_chunk() -> dict[str, Any]:
    usage = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    return {**chunk(), "choices": [], "usage": usage}


def complete_stream(reason: str = "stop") -> httpx.Response:
    """Groq streaming "Hello!" in two chunks, then its usage, as asked by the gateway."""
    body = sse(
        chunk(role="assistant", content=""),
        chunk("Hel"),
        chunk("lo!"),
        finished(reason),
        usage_chunk(),
        "[DONE]",
    )
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def chunks_of(payloads: list[str]) -> list[dict[str, Any]]:
    assert payloads[-1] == "[DONE]"
    return [json.loads(payload) for payload in payloads[:-1]]


def content_of(chunks: list[dict[str, Any]]) -> str:
    return "".join(choice["delta"].get("content") or "" for c in chunks for choice in c["choices"])


async def test_hit_on_a_streamed_request_is_replayed_as_a_stream(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(json=completion_body(GROQ_MODEL))

    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        response, payloads = await read_stream(client, STREAM_REQUEST)

    assert groq.call_count == 1
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-Gateway-Cache"] == "hit"
    assert response.headers["X-Gateway-Provider"] == "groq"
    assert response.headers["X-Gateway-Fallbacks"] == "0"
    chunks = chunks_of(payloads)
    assert content_of(chunks) == "Hello!"
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert {c["object"] for c in chunks} == {"chat.completion.chunk"}
    assert {c["model"] for c in chunks} == {GROQ_MODEL}
    assert len({c["id"] for c in chunks}) == 1
    # The client did not ask for the usage: like a real stream, it gets none.
    assert all("usage" not in c for c in chunks)


async def test_replayed_stream_ends_with_the_usage_when_the_client_asks_for_it(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body(GROQ_MODEL))
    request = {**STREAM_REQUEST, "stream_options": {"include_usage": True}}

    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        _, payloads = await read_stream(client, request)

    last = chunks_of(payloads)[-1]
    assert last["choices"] == []
    assert last["usage"] == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}


async def test_complete_stream_is_stored_for_normal_and_streamed_requests(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=lambda _: complete_stream())

    async with gateway_client(write_config(cache_config())) as client:
        streamed, _ = await read_stream(client, STREAM_REQUEST)
        normal = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        _, replayed = await read_stream(client, STREAM_REQUEST)

    assert groq.call_count == 1
    assert streamed.headers["X-Gateway-Cache"] == "miss"
    assert normal.headers["X-Gateway-Cache"] == "hit"
    answer = normal.json()
    assert answer["object"] == "chat.completion"
    assert answer["model"] == GROQ_MODEL
    assert answer["choices"] == [
        {"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}
    ]
    assert answer["usage"] == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    assert content_of(chunks_of(replayed)) == "Hello!"


async def test_reasoning_of_a_stream_is_stored_with_its_answer(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    body = sse(
        chunk(role="assistant", content=""),
        chunk(reasoning="Let me "),
        chunk(reasoning="think."),
        chunk("Hello!"),
        finished("stop"),
        "[DONE]",
    )
    respx_mock.post(GROQ_URL).respond(headers={"content-type": "text/event-stream"}, content=body)

    async with gateway_client(write_config(cache_config())) as client:
        await read_stream(client, STREAM_REQUEST)
        normal = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    message = normal.json()["choices"][0]["message"]
    assert message == {"role": "assistant", "reasoning": "Let me think.", "content": "Hello!"}


async def test_cut_stream_is_not_stored(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(
        side_effect=[
            complete_stream("length"),
            httpx.Response(200, json=completion_body(GROQ_MODEL)),
        ]
    )

    async with gateway_client(write_config(cache_config())) as client:
        await read_stream(client, STREAM_REQUEST)
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2


async def test_interrupted_stream_is_not_stored(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(
        side_effect=[
            failing_stream(sse(chunk("Hel")), httpx.ReadError("connection reset")),
            httpx.Response(200, json=completion_body(GROQ_MODEL)),
        ]
    )

    async with gateway_client(write_config(cache_config())) as client:
        _, payloads = await read_stream(client, STREAM_REQUEST)
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert "stream_interrupted" in payloads[-1]
    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2


async def test_cancelled_stream_is_not_stored(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    respx_mock.route(host="127.0.0.1").pass_through()  # the client talks to the live gateway
    upstream_closed = asyncio.Event()
    groq = respx_mock.post(GROQ_URL).mock(
        side_effect=[
            held_open_stream(sse(chunk("Hel"), finished("stop")), upstream_closed),
            httpx.Response(200, json=completion_body(GROQ_MODEL)),
        ]
    )

    async with live_gateway(write_config(cache_config())) as client:
        async with client.stream("POST", "/v1/chat/completions", json=STREAM_REQUEST) as stream:
            await asyncio.wait_for(next_event_with(stream.aiter_lines(), "Hel"), timeout=2)
        await asyncio.wait_for(upstream_closed.wait(), timeout=2)  # the client left
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2
