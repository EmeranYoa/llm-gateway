"""Tests for semantic hits: a rephrased question, in the same context, gets the stored answer."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx

from app.config import ConfigError, Settings, load_config
from tests.conftest import gateway_client, new_api_key
from tests.upstream import CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body

WriteConfig = Callable[[str], Settings]

GROQ_MODEL = "llama-3.3-70b-versatile"
EMBEDDINGS_URL = "http://ollama.test/v1/embeddings"

QUESTION = "What is the capital of France?"
REPHRASED = "Which city is the capital of France?"  # cosine similarity 0.99 with QUESTION
RELATED = "What is the capital of Germany?"  # cosine similarity 0.8 with QUESTION
VECTORS = {
    QUESTION: [1.0, 0.0, 0.0, 0.0],
    REPHRASED: [0.99, 0.141, 0.0, 0.0],
    RELATED: [0.8, 0.6, 0.0, 0.0],
}


def semantic_config(
    cache: str = "", aliases: str = "chat-fast: {}", embedding_model: str = "nomic-embed-text"
) -> str:
    """`chat-fast` and `chat-faq` on Groq, with a cache that embeds questions with Ollama."""
    return f"""
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      {GROQ_MODEL}: {{}}
  ollama:
    base_url: http://ollama.test/v1
    api_key_env: null
    models:
      "llama3.2:3b": {{}}
routes:
  chat-fast: [ groq/{GROQ_MODEL} ]
  chat-faq: [ groq/{GROQ_MODEL} ]
cache:
  embedding: {{ provider: ollama, model: {embedding_model} }}
  {cache}
  aliases: {{ {aliases} }}
"""


@pytest.fixture(autouse=True)
def groq(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> respx.Route:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    return respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )


@pytest.fixture(autouse=True)
def embeddings(respx_mock: respx.MockRouter) -> respx.Route:
    """A fake Ollama embedding endpoint that returns the vector chosen for each question."""

    def embed(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["input"]
        vector = VECTORS.get(text, [0.0, 0.0, 0.0, 1.0])
        return httpx.Response(
            200, json={"object": "list", "data": [{"index": 0, "embedding": vector}]}
        )

    return respx_mock.post(EMBEDDINGS_URL).mock(side_effect=embed)


def asking(question: str | list[dict[str, str]], **changes: Any) -> dict[str, Any]:
    return {**CHAT_REQUEST, "messages": [{"role": "user", "content": question}], **changes}


def embedded_texts(route: respx.Route) -> list[str]:
    return [json.loads(call.request.content)["input"] for call in route.calls]


async def test_rephrased_question_is_a_hit(
    write_config: WriteConfig, groq: respx.Route, embeddings: respx.Route
) -> None:
    async with gateway_client(write_config(semantic_config())) as client:
        first = await client.post("/v1/chat/completions", json=asking(QUESTION))
        second = await client.post("/v1/chat/completions", json=asking(REPHRASED))

    assert first.headers["X-Gateway-Cache"] == "miss"
    assert second.headers["X-Gateway-Cache"] == "hit"
    assert second.json()["choices"] == first.json()["choices"]
    assert groq.call_count == 1
    # One embedding per request: the write reuses the embedding of the lookup.
    assert embedded_texts(embeddings) == [QUESTION, REPHRASED]
    sent = json.loads(embeddings.calls[0].request.content)
    assert sent["model"] == "nomic-embed-text"


async def test_question_below_the_threshold_is_a_miss(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    async with gateway_client(write_config(semantic_config())) as client:
        await client.post("/v1/chat/completions", json=asking(QUESTION))
        response = await client.post("/v1/chat/completions", json=asking(RELATED))

    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2


async def test_threshold_can_be_set_per_alias(write_config: WriteConfig, groq: respx.Route) -> None:
    config = semantic_config(
        cache="similarity_threshold: 0.9",
        aliases="chat-fast: {}, chat-faq: { similarity_threshold: 0.75 }",
    )

    async with gateway_client(write_config(config)) as client:
        for alias in ("chat-fast", "chat-faq"):
            await client.post("/v1/chat/completions", json=asking(QUESTION, model=alias))
        strict = await client.post("/v1/chat/completions", json=asking(RELATED))
        lenient = await client.post("/v1/chat/completions", json=asking(RELATED, model="chat-faq"))

    assert strict.headers["X-Gateway-Cache"] == "miss"
    assert lenient.headers["X-Gateway-Cache"] == "hit"


async def test_semantic_hit_needs_the_same_context(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    system = {"role": "system", "content": "Answer in German."}
    with_system_prompt = {**CHAT_REQUEST, "messages": [system, asking(REPHRASED)["messages"][0]]}

    async with gateway_client(write_config(semantic_config())) as client:
        await client.post("/v1/chat/completions", json=asking(QUESTION))
        response = await client.post("/v1/chat/completions", json=with_system_prompt)

    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 2


async def test_semantic_hit_stays_within_the_tenant_and_the_alias(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    settings = write_config(semantic_config(aliases="chat-fast: {}, chat-faq: {}"))

    async with gateway_client(settings) as first_tenant:
        await first_tenant.post("/v1/chat/completions", json=asking(QUESTION))
        other_alias = await first_tenant.post(
            "/v1/chat/completions", json=asking(REPHRASED, model="chat-faq")
        )
    async with gateway_client(settings) as second_tenant:
        other_tenant = await second_tenant.post("/v1/chat/completions", json=asking(REPHRASED))

    assert other_alias.headers["X-Gateway-Cache"] == "miss"
    assert other_tenant.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 3


async def test_new_embedding_model_ignores_older_vectors(
    write_config: WriteConfig, groq: respx.Route, database_url: str
) -> None:
    api_key = await new_api_key(database_url)  # the same tenant on both gateways

    async with gateway_client(write_config(semantic_config()), api_key=api_key) as client:
        await client.post("/v1/chat/completions", json=asking(QUESTION))
    new_model = semantic_config(embedding_model="mxbai-embed-large")
    async with gateway_client(write_config(new_model), api_key=api_key) as client:
        rephrased = await client.post("/v1/chat/completions", json=asking(REPHRASED))
        identical = await client.post("/v1/chat/completions", json=asking(QUESTION))

    # Vectors of two embedding models are not comparable; exact hits need no vector.
    assert rephrased.headers["X-Gateway-Cache"] == "miss"
    assert identical.headers["X-Gateway-Cache"] == "hit"


async def test_last_message_not_from_the_user_uses_exact_hits_only(
    write_config: WriteConfig, groq: respx.Route, embeddings: respx.Route
) -> None:
    prefill = {"role": "assistant", "content": "The capital is"}
    request = {**CHAT_REQUEST, "messages": [*asking(QUESTION)["messages"], prefill]}

    async with gateway_client(write_config(semantic_config())) as client:
        first = await client.post("/v1/chat/completions", json=request)
        second = await client.post("/v1/chat/completions", json=request)

    assert [first.headers["X-Gateway-Cache"], second.headers["X-Gateway-Cache"]] == ["miss", "hit"]
    assert not embeddings.called


async def test_long_question_uses_exact_hits_only(
    write_config: WriteConfig, groq: respx.Route, embeddings: respx.Route
) -> None:
    # An embedding model silently cuts long texts: two long texts with the same start
    # would get the same vector, and the second one the answer of the first.
    config = semantic_config(cache="max_semantic_chars: 20")
    request = asking("x" * 21)

    async with gateway_client(write_config(config)) as client:
        first = await client.post("/v1/chat/completions", json=request)
        second = await client.post("/v1/chat/completions", json=request)

    assert [first.headers["X-Gateway-Cache"], second.headers["X-Gateway-Cache"]] == ["miss", "hit"]
    assert not embeddings.called


async def test_text_parts_are_joined_into_one_question(
    write_config: WriteConfig, groq: respx.Route, embeddings: respx.Route
) -> None:
    parts = [
        {"type": "text", "text": "Which city is the capital"},
        {"type": "text", "text": "of France?"},
    ]

    async with gateway_client(write_config(semantic_config())) as client:
        await client.post("/v1/chat/completions", json=asking(QUESTION))
        response = await client.post("/v1/chat/completions", json=asking(parts))

    assert embedded_texts(embeddings)[1] == REPHRASED
    assert response.headers["X-Gateway-Cache"] == "hit"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (("embedding: { provider: ollama,", "embedding: { provider: unknown,"), "unknown"),
        (("aliases:", "similarity_threshold: 1.5\n  aliases:"), "similarity_threshold"),
        (("aliases:", "max_semantic_chars: 0\n  aliases:"), "max_semantic_chars"),
        (("chat-fast: {}", "chat-fast: { similarity_threshold: 0 }"), "similarity_threshold"),
    ],
    ids=["unknown-provider", "threshold-above-1", "zero-max-chars", "zero-alias-threshold"],
)
def test_invalid_semantic_settings_stop_the_gateway(
    write_config: WriteConfig, change: tuple[str, str], error: str
) -> None:
    settings = write_config(semantic_config().replace(*change))

    with pytest.raises(ConfigError, match=error):
        load_config(settings.gateway_config_path, environ={"GROQ_API_KEY": GROQ_KEY})
