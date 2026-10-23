"""Tests for cache bypass, the entry limit of each tenant and duplicate writes."""

import asyncio
import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx

from app.config import ConfigError, Settings, load_config
from tests.conftest import gateway_client, new_api_key, run_admin
from tests.test_cache import GROQ_MODEL, cache_config, with_changes
from tests.test_semantic_cache import QUESTION, REPHRASED, asking, semantic_config
from tests.upstream import CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body

WriteConfig = Callable[[str], Settings]

BYPASS = {"X-Gateway-Cache": "bypass"}


@pytest.fixture(autouse=True)
def groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)


def answers(*contents: str) -> list[httpx.Response]:
    return [httpx.Response(200, json=completion_body(GROQ_MODEL, content)) for content in contents]


def content(response: httpx.Response) -> Any:
    return response.json()["choices"][0]["message"]["content"]


async def test_bypass_calls_a_provider_and_replaces_the_stored_answer(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=answers("Old answer", "Fresh answer"))

    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        bypassed = await client.post("/v1/chat/completions", json=CHAT_REQUEST, headers=BYPASS)
        after = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert groq.call_count == 2
    assert bypassed.headers["X-Gateway-Cache"] == "bypass"
    assert content(bypassed) == "Fresh answer"
    assert after.headers["X-Gateway-Cache"] == "hit"
    assert content(after) == "Fresh answer"


async def test_bypass_is_ignored_on_an_alias_without_cache(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=answers("Hello!"))
    request = with_changes(model="chat-live")

    async with gateway_client(write_config(cache_config())) as client:
        response = await client.post("/v1/chat/completions", json=request, headers=BYPASS)

    assert response.status_code == 200
    assert "X-Gateway-Cache" not in response.headers


async def test_tenant_over_its_entry_limit_stores_no_new_answer(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )
    config = cache_config("max_entries_per_tenant: 2, aliases: { chat-fast: {} }")
    questions = [with_changes(messages=[{"role": "user", "content": q}]) for q in "ABC"]

    async with gateway_client(write_config(config)) as client:
        for question in questions:
            await client.post("/v1/chat/completions", json=question)
        again = [await client.post("/v1/chat/completions", json=q) for q in questions]

    # The first two answers were stored; the third was not, but lookups go on.
    assert [response.headers["X-Gateway-Cache"] for response in again] == ["hit", "hit", "miss"]
    assert groq.call_count == 4


async def test_entry_limit_is_counted_per_tenant(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )
    settings = write_config(cache_config("max_entries_per_tenant: 1, aliases: { chat-fast: {} }"))

    async with gateway_client(settings) as first_tenant:
        await first_tenant.post("/v1/chat/completions", json=CHAT_REQUEST)
    async with gateway_client(settings) as second_tenant:
        await second_tenant.post("/v1/chat/completions", json=CHAT_REQUEST)
        response = await second_tenant.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.headers["X-Gateway-Cache"] == "hit"


async def test_expired_entries_make_room_for_new_ones(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )
    config = cache_config("ttl: 0.5, max_entries_per_tenant: 1, aliases: { chat-fast: {} }")
    other = with_changes(messages=[{"role": "user", "content": "Other"}])

    async with gateway_client(write_config(config)) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await asyncio.sleep(0.6)
        await client.post("/v1/chat/completions", json=other)
        response = await client.post("/v1/chat/completions", json=other)

    assert response.headers["X-Gateway-Cache"] == "hit"


async def test_cleared_entries_make_room_for_new_ones(
    write_config: WriteConfig,
    respx_mock: respx.MockRouter,
    database_url: str,
    redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )
    monkeypatch.setenv("REDIS_URL", redis_url)
    tenant = f"tenant-{uuid4().hex[:8]}"
    output = await run_admin(database_url, "create-key", "--tenant", tenant)
    [api_key] = [word for word in output.split() if word.startswith("gw_")]
    settings = write_config(cache_config("max_entries_per_tenant: 1, aliases: { chat-fast: {} }"))
    other = with_changes(messages=[{"role": "user", "content": "Other"}])

    async with gateway_client(settings, api_key=api_key) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await run_admin(database_url, "clear-cache", "--tenant", tenant)
        await client.post("/v1/chat/completions", json=other)
        response = await client.post("/v1/chat/completions", json=other)

    assert response.headers["X-Gateway-Cache"] == "hit"


async def test_concurrent_identical_misses_keep_the_first_answer(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    calls = 0

    async def groq(_: httpx.Request) -> httpx.Response:
        # The first call answers fast, the second one later: both are misses.
        nonlocal calls
        calls += 1
        name, delay = ("first", 0.1) if calls == 1 else ("second", 0.4)
        await asyncio.sleep(delay)
        return httpx.Response(200, json=completion_body(GROQ_MODEL, name))

    respx_mock.post(GROQ_URL).mock(side_effect=groq)

    async with gateway_client(write_config(cache_config())) as client:
        both = await asyncio.gather(
            *(client.post("/v1/chat/completions", json=CHAT_REQUEST) for _ in range(2))
        )
        after = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert [response.headers["X-Gateway-Cache"] for response in both] == ["miss", "miss"]
    # The later write is skipped: the stored answer is the one written first.
    assert content(after) == "first"


def test_entry_limit_must_be_positive(write_config: WriteConfig) -> None:
    settings = write_config(cache_config("max_entries_per_tenant: 0, aliases: { chat-fast: {} }"))

    with pytest.raises(ConfigError, match="max_entries_per_tenant"):
        load_config(settings.gateway_config_path, environ={"GROQ_API_KEY": GROQ_KEY})


async def test_bypass_keeps_the_answer_available_to_rephrased_questions(
    write_config: WriteConfig, respx_mock: respx.MockRouter, database_url: str
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=answers("Old answer", "Fresh answer"))
    vectors = {QUESTION: [1.0, 0.0, 0.0, 0.0], REPHRASED: [0.99, 0.141, 0.0, 0.0]}

    def embed(request: httpx.Request) -> httpx.Response:
        vector = vectors[json.loads(request.content)["input"]]
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})

    respx_mock.post("http://ollama.test/v1/embeddings").mock(side_effect=embed)
    api_key = await new_api_key(database_url)

    async with gateway_client(write_config(semantic_config()), api_key=api_key) as client:
        await client.post("/v1/chat/completions", json=asking(QUESTION))
        await client.post("/v1/chat/completions", json=asking(QUESTION), headers=BYPASS)
        rephrased = await client.post("/v1/chat/completions", json=asking(REPHRASED))

    assert rephrased.headers["X-Gateway-Cache"] == "hit"
    assert content(rephrased) == "Fresh answer"
