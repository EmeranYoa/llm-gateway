"""Tests for error handling and failover between the targets of an alias."""

import logging

import httpx
import pytest
import respx
from httpx import AsyncClient

from tests.upstream import (
    CHAT_REQUEST,
    GEMINI_URL,
    GROQ_URL,
    OLLAMA_URL,
    completion_body,
    error_body,
)


async def test_rate_limited_target_fails_over_to_next_target(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(429)
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "gemini"
    assert response.headers["X-Gateway-Model"] == "gemini-2.5-flash"
    assert response.headers["X-Gateway-Fallbacks"] == "1"


async def test_all_targets_failing_returns_503_in_openai_format(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    for url in (GROQ_URL, GEMINI_URL, OLLAMA_URL):
        respx_mock.post(url).respond(429)

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["type"] == "api_error"
    assert error["code"] == "all_targets_failed"
    assert error["message"] == (
        "All targets of alias 'chat-fast' failed: "
        "groq/llama-3.3-70b-versatile: rate limited; "
        "gemini/gemini-2.5-flash: rate limited; "
        "ollama/llama3.2:3b: rate limited"
    )


@pytest.mark.parametrize(
    "upstream_failure",
    [
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(503),
        httpx.ConnectError("connection refused"),
        httpx.ReadError("connection reset"),
        # A proxy in front of the provider may answer 200 with an HTML page.
        httpx.Response(200, text="<html>Bad gateway</html>"),
        httpx.Response(200, json=["not", "a", "completion"]),
    ],
    ids=["500", "502", "503", "connect-error", "read-error", "not-json", "not-an-object"],
)
async def test_unavailable_target_fails_over_to_next_target(
    failover_client: AsyncClient,
    respx_mock: respx.MockRouter,
    upstream_failure: httpx.Response | Exception,
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=[upstream_failure])
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "gemini"


@pytest.mark.parametrize("status_code", [401, 403, 404])
async def test_misconfigured_target_fails_over_and_logs_an_error(
    failover_client: AsyncClient,
    respx_mock: respx.MockRouter,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
) -> None:
    respx_mock.post(GROQ_URL).respond(status_code, json=error_body("Invalid API Key"))
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    with caplog.at_level(logging.ERROR):
        response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "gemini"
    assert [record.getMessage() for record in caplog.records] == [
        f"target groq/llama-3.3-70b-versatile is misconfigured (HTTP {status_code}): "
        "check its API key and model name"
    ]


@pytest.mark.parametrize("status_code", [400, 422])
async def test_invalid_request_is_returned_without_failover(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, status_code: int
) -> None:
    respx_mock.post(GROQ_URL).respond(
        status_code,
        json={
            "error": {
                "message": "'temperature' must be <= 2",
                "type": "invalid_request_error",
                "param": "temperature",
                "code": "invalid_value",
            }
        },
    )
    gemini = respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    response = await failover_client.post(
        "/v1/chat/completions", json={**CHAT_REQUEST, "temperature": 5}
    )

    assert response.status_code == status_code
    assert response.json() == {
        "error": {
            "message": "groq/llama-3.3-70b-versatile: 'temperature' must be <= 2",
            "type": "invalid_request_error",
            "param": "temperature",
            "code": "invalid_value",
        }
    }
    assert not gemini.called


@pytest.mark.parametrize(
    ("upstream_body", "expected_message"),
    [
        (
            [
                {
                    "error": {
                        "code": 400,
                        "message": "Invalid JSON payload",
                        "status": "INVALID_ARGUMENT",
                    }
                }
            ],
            "Invalid JSON payload",
        ),
        ({"error": "invalid temperature"}, "invalid temperature"),
        ("plain text error", "HTTP 400"),
    ],
    ids=["gemini-list", "ollama-string", "not-json"],
)
async def test_invalid_request_from_any_error_format_is_returned_in_openai_format(
    failover_client: AsyncClient,
    respx_mock: respx.MockRouter,
    upstream_body: object,
    expected_message: str,
) -> None:
    if isinstance(upstream_body, str):
        respx_mock.post(GROQ_URL).respond(400, text=upstream_body)
    else:
        respx_mock.post(GROQ_URL).respond(400, json=upstream_body)

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["message"] == f"groq/llama-3.3-70b-versatile: {expected_message}"
    assert error["type"] == "invalid_request_error"


CONTEXT_TOO_LARGE_RESPONSES = {
    "openai-code": httpx.Response(
        400,
        json=error_body(
            "Please reduce the length of the messages or completion.",
            code="context_length_exceeded",
        ),
    ),
    "openrouter-message": httpx.Response(
        400,
        json=error_body(
            "This endpoint's maximum context length is 8192 tokens. "
            "However, you requested about 9000 tokens."
        ),
    ),
    "gemini-message": httpx.Response(
        400,
        json=[
            {
                "error": {
                    "code": 400,
                    "message": "The input token count (1200000) exceeds the maximum number "
                    "of tokens allowed (1048576).",
                    "status": "INVALID_ARGUMENT",
                }
            }
        ],
    ),
    "http-413": httpx.Response(
        413, json=error_body("Request too large for model", code="rate_limit_exceeded")
    ),
}


@pytest.mark.parametrize(
    "upstream_response",
    CONTEXT_TOO_LARGE_RESPONSES.values(),
    ids=CONTEXT_TOO_LARGE_RESPONSES.keys(),
)
async def test_context_too_large_fails_over_to_next_target(
    failover_client: AsyncClient,
    respx_mock: respx.MockRouter,
    upstream_response: httpx.Response,
) -> None:
    respx_mock.post(GROQ_URL).mock(return_value=upstream_response)
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "gemini"


async def test_request_too_large_for_every_target_returns_400(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    for url in (GROQ_URL, GEMINI_URL, OLLAMA_URL):
        respx_mock.post(url).respond(
            400, json=error_body("too long", code="context_length_exceeded")
        )

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 400
    assert response.json()["error"] == {
        "message": "The request is too large for every target of alias 'chat-fast'. "
        "Reduce the prompt or max_tokens.",
        "type": "invalid_request_error",
        "param": "messages",
        "code": "context_length_exceeded",
    }


async def test_request_too_large_for_some_targets_and_failing_on_others_returns_503(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(
        400, json=error_body("too long", code="context_length_exceeded")
    )
    respx_mock.post(GEMINI_URL).respond(429)
    respx_mock.post(OLLAMA_URL).respond(500)

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 503


async def test_fallbacks_header_counts_targets_tried_before_success(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(429)
    respx_mock.post(GEMINI_URL).respond(503)
    respx_mock.post(OLLAMA_URL).respond(json=completion_body("llama3.2:3b"))

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "ollama"
    assert response.headers["X-Gateway-Fallbacks"] == "2"
