"""Tests for the response cache: a repeated request is answered without calling a provider."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx

from app.config import ConfigError, Settings, load_config
from tests.conftest import gateway_client
from tests.upstream import CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body

WriteConfig = Callable[[str], Settings]

GROQ_MODEL = "llama-3.3-70b-versatile"


def cache_config(
    cache: str = "aliases: { chat-fast: {}, chat-smart: {} }", tenants: str = ""
) -> str:
    """Three aliases on the same Groq model; by default `chat-fast` and `chat-smart` are cached."""
    return f"""
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      {GROQ_MODEL}: {{}}
routes:
  chat-fast: [ groq/{GROQ_MODEL} ]
  chat-smart: [ groq/{GROQ_MODEL} ]
  chat-live: [ groq/{GROQ_MODEL} ]
cache: {{ {cache} }}
{tenants}
"""


@pytest.fixture(autouse=True)
def groq(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> respx.Route:
    """A fake Groq that answers every chat completion."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    return respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )


def with_changes(**changes: Any) -> dict[str, Any]:
    return {**CHAT_REQUEST, **changes}


async def test_repeated_request_is_answered_from_the_cache(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    async with gateway_client(write_config(cache_config())) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert groq.call_count == 1
    assert first.headers["X-Gateway-Cache"] == "miss"
    assert second.status_code == 200
    assert second.headers["X-Gateway-Cache"] == "hit"
    # The answer names the target that generated it, reached without any fallback.
    assert second.headers["X-Gateway-Provider"] == "groq"
    assert second.headers["X-Gateway-Model"] == GROQ_MODEL
    assert second.headers["X-Gateway-Fallbacks"] == "0"
    assert second.headers["X-Gateway-Request-Id"] != first.headers["X-Gateway-Request-Id"]
    cached, original = second.json(), first.json()
    assert cached["choices"] == original["choices"]
    assert cached["usage"] == original["usage"]
    assert cached["model"] == GROQ_MODEL
    # Each answer has its own id and creation time, as if it was just generated.
    assert cached["id"] != original["id"]
    assert cached["id"].startswith("chatcmpl-")
    assert cached["created"] > original["created"]


async def test_alias_without_cache_always_calls_a_provider(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    request = with_changes(model="chat-live")

    async with gateway_client(write_config(cache_config())) as client:
        responses = [await client.post("/v1/chat/completions", json=request) for _ in range(2)]

    assert groq.call_count == 2
    assert all("X-Gateway-Cache" not in response.headers for response in responses)


async def test_cache_is_isolated_per_tenant(write_config: WriteConfig, groq: respx.Route) -> None:
    settings = write_config(cache_config())

    async with gateway_client(settings) as first_tenant:
        await first_tenant.post("/v1/chat/completions", json=CHAT_REQUEST)
    async with gateway_client(settings) as second_tenant:  # a client with another tenant's key
        response = await second_tenant.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2


async def test_cache_is_isolated_per_alias(write_config: WriteConfig, groq: respx.Route) -> None:
    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        response = await client.post("/v1/chat/completions", json=with_changes(model="chat-smart"))

    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2


@pytest.mark.parametrize(
    "changed_request",
    [
        with_changes(messages=[{"role": "user", "content": "Hello"}]),
        with_changes(
            messages=[{"role": "system", "content": "Be brief."}, *CHAT_REQUEST["messages"]]
        ),
        with_changes(
            messages=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
                {"role": "user", "content": "Hi"},
            ]
        ),
        with_changes(temperature=0.9),
        with_changes(max_tokens=50),
    ],
    ids=["other-question", "system-prompt", "earlier-messages", "temperature", "max-tokens"],
)
async def test_another_question_or_context_is_a_miss(
    write_config: WriteConfig, groq: respx.Route, changed_request: dict[str, Any]
) -> None:
    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        response = await client.post("/v1/chat/completions", json=changed_request)

    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2


async def test_field_order_does_not_matter(write_config: WriteConfig, groq: respx.Route) -> None:
    request = {"temperature": 0.2, **CHAT_REQUEST}
    reordered = {**CHAT_REQUEST, "temperature": 0.2}

    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=request)
        response = await client.post("/v1/chat/completions", json=reordered)

    assert response.headers["X-Gateway-Cache"] == "hit"
    assert groq.call_count == 1


async def test_failed_request_is_not_cached(write_config: WriteConfig, groq: respx.Route) -> None:
    groq.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json=completion_body(GROQ_MODEL)),
    ]

    async with gateway_client(write_config(cache_config())) as client:
        failed = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        retried = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert failed.status_code == 503
    assert failed.headers["X-Gateway-Cache"] == "miss"
    assert retried.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2


async def test_entry_expires_after_its_ttl(write_config: WriteConfig, groq: respx.Route) -> None:
    config = cache_config("ttl: 0.5, aliases: { chat-fast: {}, chat-smart: { ttl: 60 } }")

    async with gateway_client(write_config(config)) as client:
        for alias in ("chat-fast", "chat-smart"):
            await client.post("/v1/chat/completions", json=with_changes(model=alias))
        await asyncio.sleep(0.6)
        expired = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        kept = await client.post("/v1/chat/completions", json=with_changes(model="chat-smart"))

    # The global TTL expired; the alias's own, longer TTL did not.
    assert expired.headers["X-Gateway-Cache"] == "miss"
    assert kept.headers["X-Gateway-Cache"] == "hit"
    assert groq.call_count == 3


async def test_hit_counts_in_the_tenant_rpm(write_config: WriteConfig) -> None:
    config = cache_config(tenants="tenants: { default_limits: { rpm: 2 } }")

    async with gateway_client(write_config(config)) as client:
        statuses = [
            (await client.post("/v1/chat/completions", json=CHAT_REQUEST)).status_code
            for _ in range(3)
        ]

    assert statuses == [200, 200, 429]


async def test_hit_uses_no_tokens_of_the_tenant_budget(write_config: WriteConfig) -> None:
    # Each request reserves 2 + 600 tokens; the first one really used 7.
    config = cache_config(tenants="tenants: { default_limits: { tokens_per_day: 1000 } }")
    request = with_changes(max_tokens=600)

    async with gateway_client(write_config(config)) as client:
        responses = [await client.post("/v1/chat/completions", json=request) for _ in range(3)]

    # Without releasing the reservation of each hit, the third request would not fit.
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert [response.headers["X-Gateway-Cache"] for response in responses] == ["miss", "hit", "hit"]


@pytest.mark.parametrize(
    ("cache", "error"),
    [
        ("aliases: { chat-unknown: {} }", "chat-unknown"),
        ("ttl: 0, aliases: { chat-fast: {} }", "ttl"),
        ("aliases: { chat-fast: { ttl: -1 } }", "ttl"),
        ("aliases: { chat-fast: { unknown: 1 } }", "unknown"),
    ],
    ids=["unknown-alias", "zero-ttl", "negative-alias-ttl", "unknown-field"],
)
def test_invalid_cache_section_stops_the_gateway(
    write_config: WriteConfig, cache: str, error: str
) -> None:
    settings = write_config(cache_config(cache))

    with pytest.raises(ConfigError, match=error):
        load_config(settings.gateway_config_path, environ={"GROQ_API_KEY": GROQ_KEY})


WEATHER_TOOL = {
    "type": "function",
    "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {}}},
}
TEXT_PART = {"type": "text", "text": "Hi"}
IMAGE_PART = {"type": "image_url", "image_url": {"url": "https://images.test/cat.png"}}
AUDIO_PART = {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "wav"}}


def with_content(*parts: dict[str, Any]) -> dict[str, Any]:
    """The usual request, with a user message made of the content `parts`."""
    return with_changes(messages=[{"role": "user", "content": list(parts)}])


@pytest.mark.parametrize(
    "request_body",
    [
        with_changes(tools=[WEATHER_TOOL]),
        with_changes(tools=[]),
        with_changes(functions=[WEATHER_TOOL["function"]]),
        with_changes(n=2),
        with_changes(seed=42),
        with_changes(seed=None),
        with_content(TEXT_PART, IMAGE_PART),
        with_content(AUDIO_PART),
    ],
    ids=["tools", "empty-tools", "functions", "n-2", "seed", "null-seed", "image", "audio"],
)
async def test_request_unsafe_to_replay_does_not_use_the_cache(
    write_config: WriteConfig, groq: respx.Route, request_body: dict[str, Any]
) -> None:
    async with gateway_client(write_config(cache_config())) as client:
        responses = [await client.post("/v1/chat/completions", json=request_body) for _ in range(2)]

    # Exactly like an alias without cache: no lookup, no store, no header.
    assert [response.status_code for response in responses] == [200, 200]
    assert all("X-Gateway-Cache" not in response.headers for response in responses)
    assert groq.call_count == 2


@pytest.mark.parametrize(
    "request_body",
    [with_changes(n=1), with_content(TEXT_PART, {"type": "text", "text": "How are you?"})],
    ids=["n-1", "text-parts"],
)
async def test_request_safe_to_replay_uses_the_cache(
    write_config: WriteConfig, groq: respx.Route, request_body: dict[str, Any]
) -> None:
    async with gateway_client(write_config(cache_config())) as client:
        responses = [await client.post("/v1/chat/completions", json=request_body) for _ in range(2)]

    assert [response.headers["X-Gateway-Cache"] for response in responses] == ["miss", "hit"]
    assert groq.call_count == 1


def answer_with(*finish_reasons: str | None) -> dict[str, Any]:
    """A completion body with one choice per finish reason (None: no `finish_reason` field)."""
    body = completion_body(GROQ_MODEL)
    choices = []
    for index, finish_reason in enumerate(finish_reasons):
        choice = {"index": index, "message": {"role": "assistant", "content": "Hello!"}}
        if finish_reason is not None:
            choice["finish_reason"] = finish_reason
        choices.append(choice)
    body["choices"] = choices
    return body


@pytest.mark.parametrize(
    "answer",
    [
        answer_with("length"),
        answer_with("content_filter"),
        answer_with("tool_calls"),
        answer_with(None),
        answer_with("stop", "length"),
        answer_with(),
    ],
    ids=["length", "content-filter", "tool-calls", "missing", "one-choice-cut", "no-choice"],
)
async def test_answer_that_did_not_stop_normally_is_not_stored(
    write_config: WriteConfig, groq: respx.Route, answer: dict[str, Any]
) -> None:
    groq.side_effect = lambda _: httpx.Response(200, json=answer)

    async with gateway_client(write_config(cache_config())) as client:
        responses = [await client.post("/v1/chat/completions", json=CHAT_REQUEST) for _ in range(2)]

    assert [response.status_code for response in responses] == [200, 200]
    assert [response.headers["X-Gateway-Cache"] for response in responses] == ["miss", "miss"]
    assert groq.call_count == 2
