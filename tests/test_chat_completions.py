"""Tests for POST /v1/chat/completions."""

import json
import logging
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient

from tests.upstream import CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body


async def test_request_is_routed_to_first_target(
    chat_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    upstream = respx_mock.post(GROQ_URL).respond(
        json=completion_body(model="llama-3.3-70b-versatile-internal-name")
    )

    response = await chat_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Hello!"
    assert body["model"] == "llama-3.3-70b-versatile"

    sent: httpx.Request = upstream.calls.last.request
    assert sent.headers["Authorization"] == f"Bearer {GROQ_KEY}"
    assert json.loads(sent.content)["model"] == "llama-3.3-70b-versatile"


async def test_response_headers_describe_the_routing(
    chat_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body(model="llama-3.3-70b-versatile"))

    first = await chat_client.post("/v1/chat/completions", json=CHAT_REQUEST)
    second = await chat_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.headers["X-Gateway-Provider"] == "groq"
    assert first.headers["X-Gateway-Model"] == "llama-3.3-70b-versatile"
    assert first.headers["X-Gateway-Fallbacks"] == "0"
    assert first.headers["X-Gateway-Request-Id"]
    assert first.headers["X-Gateway-Request-Id"] != second.headers["X-Gateway-Request-Id"]


@pytest.mark.parametrize(
    "client_fields",
    [
        {},
        {
            "max_tokens": 50,
            "temperature": 0.2,
            "tools": [{"type": "function", "function": {"name": "get_weather"}}],
            "response_format": {"type": "json_object"},
        },
    ],
)
async def test_request_fields_reach_the_provider_unchanged(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, client_fields: dict[str, Any]
) -> None:
    upstream = respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))

    await chat_client.post("/v1/chat/completions", json={**CHAT_REQUEST, **client_fields})

    sent = json.loads(upstream.calls.last.request.content)
    assert sent == {**CHAT_REQUEST, **client_fields, "model": "llama-3.3-70b-versatile"}


async def test_unknown_alias_returns_404_in_openai_format(chat_client: AsyncClient) -> None:
    response = await chat_client.post(
        "/v1/chat/completions", json={**CHAT_REQUEST, "model": "no-such-alias"}
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "message": "The model 'no-such-alias' does not exist.",
            "type": "invalid_request_error",
            "param": "model",
            "code": "model_not_found",
        }
    }


async def test_streaming_is_refused_with_400(
    chat_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    upstream = respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))

    response = await chat_client.post("/v1/chat/completions", json={**CHAT_REQUEST, "stream": True})

    assert response.status_code == 400
    assert response.json()["error"] == {
        "message": "Streaming is not supported yet.",
        "type": "invalid_request_error",
        "param": "stream",
        "code": "unsupported_parameter",
    }
    assert not upstream.called


async def test_alias_without_enabled_target_returns_503(chat_client: AsyncClient) -> None:
    response = await chat_client.post(
        "/v1/chat/completions", json={**CHAT_REQUEST, "model": "chat-offline"}
    )

    assert response.status_code == 503
    assert "Retry-After" not in response.headers
    assert response.json()["error"] == {
        "message": "No enabled provider for alias 'chat-offline'. Check the gateway API keys.",
        "type": "api_error",
        "param": None,
        "code": "no_enabled_target",
    }


async def test_malformed_request_returns_400_in_openai_format(chat_client: AsyncClient) -> None:
    response = await chat_client.post("/v1/chat/completions", json={"model": "chat-fast"})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["type"] == "invalid_request_error"
    assert error["param"] == "messages"
    assert "messages" in error["message"]


async def test_logs_never_contain_api_keys_or_prompts(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    prompt = "my confidential prompt"

    with caplog.at_level(logging.DEBUG):
        await chat_client.post(
            "/v1/chat/completions",
            json={**CHAT_REQUEST, "messages": [{"role": "user", "content": prompt}]},
        )

    assert caplog.records, "expected some log records to inspect"
    assert GROQ_KEY not in caplog.text
    assert prompt not in caplog.text
