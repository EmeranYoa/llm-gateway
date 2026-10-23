"""Tests for cache failures: the cache can slow a request down, but never makes it fail."""

import asyncio
import logging
from collections.abc import Callable

import httpx
import pytest
import respx

from app.config import Settings
from tests.conftest import gateway_client
from tests.test_cache import GROQ_MODEL
from tests.test_degraded import UNREACHABLE_REDIS
from tests.test_semantic_cache import EMBEDDINGS_URL, QUESTION, asking, semantic_config
from tests.upstream import GROQ_KEY, GROQ_URL, completion_body

WriteConfig = Callable[[str], Settings]


@pytest.fixture(autouse=True)
def groq(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> respx.Route:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    return respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )


def embedding_response() -> httpx.Response:
    return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]}]})


async def slow_embedding(_: httpx.Request) -> httpx.Response:
    await asyncio.sleep(2)
    return embedding_response()


@pytest.mark.parametrize(
    "failure",
    [
        lambda _: httpx.Response(500),
        httpx.ConnectError("connection refused"),
        lambda _: httpx.Response(200, json={"unexpected": "body"}),
        slow_embedding,
    ],
    ids=["error-status", "unreachable", "bad-body", "timeout"],
)
async def test_failing_embedding_model_leaves_the_request_to_the_providers(
    write_config: WriteConfig,
    respx_mock: respx.MockRouter,
    groq: respx.Route,
    caplog: pytest.LogCaptureFixture,
    failure: Exception | Callable[[httpx.Request], object],
) -> None:
    respx_mock.post(EMBEDDINGS_URL).mock(side_effect=failure)
    config = semantic_config().replace(
        "model: nomic-embed-text }", "model: nomic-embed-text, timeout: 0.2 }"
    )

    with caplog.at_level(logging.WARNING):
        async with gateway_client(write_config(config)) as client:
            responses = [
                await client.post("/v1/chat/completions", json=asking(QUESTION)) for _ in range(2)
            ]

    assert [response.status_code for response in responses] == [200, 200]
    assert [r.headers["X-Gateway-Cache"] for r in responses] == ["unavailable", "unavailable"]
    # Nothing was stored: the second identical request was not an exact hit.
    assert groq.call_count == 2
    assert any("embedding" in message for message in caplog.messages)
    assert QUESTION not in caplog.text  # never the prompt


async def test_cache_is_skipped_when_redis_is_down(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    settings = write_config(semantic_config()).model_copy(update={"redis_url": UNREACHABLE_REDIS})

    async with gateway_client(settings) as client:
        response = await client.post("/v1/chat/completions", json=asking(QUESTION))

    assert response.status_code == 200
    assert response.headers["X-Gateway-Cache"] == "unavailable"
    assert groq.call_count == 1


async def test_time_spent_in_the_cache_counts_in_the_deadline(
    write_config: WriteConfig, respx_mock: respx.MockRouter, groq: respx.Route
) -> None:
    async def embedding_just_in_time(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.9)
        return embedding_response()

    async def slow_groq(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.5)
        return httpx.Response(200, json=completion_body(GROQ_MODEL))

    respx_mock.post(EMBEDDINGS_URL).mock(side_effect=embedding_just_in_time)
    groq.mock(side_effect=slow_groq)
    config = "gateway: { deadline: 1, min_attempt_time: 0.05 }\n" + semantic_config().replace(
        "model: nomic-embed-text }", "model: nomic-embed-text, timeout: 2 }"
    )

    async with gateway_client(write_config(config)) as client:
        response = await client.post("/v1/chat/completions", json=asking(QUESTION))

    # The embedding used 0.9 s of the 1 s deadline: too little is left for Groq.
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "deadline_exceeded"


async def test_disabled_embedding_provider_leaves_exact_hits_only(
    write_config: WriteConfig,
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    embeddings = respx_mock.post(EMBEDDINGS_URL).mock(return_value=embedding_response())
    config = semantic_config().replace("api_key_env: null", "api_key_env: OLLAMA_API_KEY")

    with caplog.at_level(logging.WARNING):
        async with gateway_client(write_config(config)) as client:
            responses = [
                await client.post("/v1/chat/completions", json=asking(QUESTION)) for _ in range(2)
            ]

    assert [r.headers["X-Gateway-Cache"] for r in responses] == ["miss", "hit"]
    assert not embeddings.called
    assert any("semantic cache disabled" in message for message in caplog.messages)


async def test_redis_database_other_than_0_is_reported_clearly(
    write_config: WriteConfig,
    respx_mock: respx.MockRouter,
    redis_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Redis creates vector indexes on database 0 only.
    respx_mock.post(EMBEDDINGS_URL).mock(return_value=embedding_response())
    other_database = redis_url.rsplit("/", 1)[0] + "/1"
    settings = write_config(semantic_config()).model_copy(update={"redis_url": other_database})

    with caplog.at_level(logging.ERROR):
        async with gateway_client(settings) as client:
            response = await client.post("/v1/chat/completions", json=asking(QUESTION))

    assert response.status_code == 200
    assert any("database 0" in message for message in caplog.messages)
