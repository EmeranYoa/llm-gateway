"""Tests for the cache in the usage log: hits, misses and the tokens the cache saved."""

import json
from collections.abc import Callable

import httpx
import pytest
import respx

from app.config import Settings
from tests.conftest import FetchUsageRows, gateway_client
from tests.test_cache import GROQ_MODEL, cache_config, with_changes
from tests.test_semantic_cache import (
    EMBEDDINGS_URL,
    QUESTION,
    REPHRASED,
    VECTORS,
    asking,
    semantic_config,
)
from tests.test_streaming import STREAM_REQUEST, read_stream
from tests.upstream import CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body

WriteConfig = Callable[[str], Settings]


@pytest.fixture(autouse=True)
def groq(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> respx.Route:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    return respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )


async def test_hit_is_logged_with_the_tokens_it_saved(
    write_config: WriteConfig, usage_rows: FetchUsageRows
) -> None:
    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        hit = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    miss_row, hit_row = await usage_rows()
    assert (miss_row["outcome"], miss_row["cache"], miss_row["cache_similarity"]) == (
        "success",
        "miss",
        None,
    )
    assert hit_row["request_id"] == hit.headers["X-Gateway-Request-Id"]
    assert hit_row["outcome"] == "cache_hit"
    assert hit_row["cache"] == "hit"
    assert hit_row["cache_similarity"] == 1.0
    # The target that generated the answer, and the tokens a provider call would have used.
    assert (hit_row["provider"], hit_row["model"]) == ("groq", GROQ_MODEL)
    assert (hit_row["prompt_tokens"], hit_row["completion_tokens"]) == (5, 2)
    assert hit_row["status_code"] == 200
    assert hit_row["latency_ms"] is not None
    assert hit_row["tenant_id"] == miss_row["tenant_id"]
    assert hit_row["prompt_chars"] == miss_row["prompt_chars"]
    assert hit_row["stream"] is False


async def test_semantic_hit_is_logged_with_its_similarity(
    write_config: WriteConfig, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    def embed(request: httpx.Request) -> httpx.Response:
        vector = VECTORS[json.loads(request.content)["input"]]
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})

    respx_mock.post(EMBEDDINGS_URL).mock(side_effect=embed)

    async with gateway_client(write_config(semantic_config())) as client:
        await client.post("/v1/chat/completions", json=asking(QUESTION))
        await client.post("/v1/chat/completions", json=asking(REPHRASED))

    hit_row = (await usage_rows())[-1]
    assert hit_row["outcome"] == "cache_hit"
    assert hit_row["cache_similarity"] == pytest.approx(0.99, abs=0.005)


async def test_streamed_hit_is_logged_as_streamed(
    write_config: WriteConfig, usage_rows: FetchUsageRows
) -> None:
    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await read_stream(client, STREAM_REQUEST)

    hit_row = (await usage_rows())[-1]
    assert (hit_row["outcome"], hit_row["stream"]) == ("cache_hit", True)


async def test_alias_without_cache_logs_no_cache_status(
    write_config: WriteConfig, usage_rows: FetchUsageRows
) -> None:
    async with gateway_client(write_config(cache_config())) as client:
        await client.post("/v1/chat/completions", json=with_changes(model="chat-live"))

    [row] = await usage_rows()
    assert (row["cache"], row["cache_similarity"]) == (None, None)


async def test_every_row_of_a_bypass_says_so(
    write_config: WriteConfig, groq: respx.Route, usage_rows: FetchUsageRows
) -> None:
    groq.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json=completion_body(GROQ_MODEL)),
    ]
    config = cache_config().replace(
        "chat-fast: [ groq/", "chat-fast: [ groq/llama-3.3-70b-versatile, groq/"
    )
    headers = {"X-Gateway-Cache": "bypass"}

    async with gateway_client(write_config(config)) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST, headers=headers)

    rows = await usage_rows()
    assert [(row["outcome"], row["cache"]) for row in rows] == [
        ("unavailable", "bypass"),
        ("success", "bypass"),
    ]


async def test_unavailable_cache_is_logged(
    write_config: WriteConfig, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(EMBEDDINGS_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    async with gateway_client(write_config(semantic_config())) as client:
        await client.post("/v1/chat/completions", json=asking(QUESTION))

    [row] = await usage_rows()
    assert (row["outcome"], row["cache"]) == ("success", "unavailable")
