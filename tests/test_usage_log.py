"""Tests for the usage log: one `usage_log` row per examined target."""

import asyncio
import datetime as dt
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.storage.tenants import NewApiKey, create_api_key
from tests.conftest import DatabaseProxy, FetchUsageRows, gateway_client
from tests.upstream import (
    CHAT_CONFIG,
    CHAT_REQUEST,
    FAILOVER_CONFIG,
    GEMINI_KEY,
    GEMINI_URL,
    GROQ_KEY,
    GROQ_URL,
    OLLAMA_URL,
    completion_body,
    error_body,
)

WriteConfig = Callable[[str], Settings]


async def new_tenant_key(database_url: str) -> NewApiKey:
    """Create a key of a new tenant, and return it with the ids of its tenant and key."""
    engine = create_async_engine(database_url)
    try:
        return await create_api_key(engine, f"tenant-{uuid4().hex[:8]}")
    finally:
        await engine.dispose()


@pytest.fixture
def groq_and_gemini_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the fake Groq and Gemini providers."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)


async def test_successful_request_writes_one_usage_row(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))

    response = await chat_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    [row] = await usage_rows()
    assert row["request_id"] == response.headers["X-Gateway-Request-Id"]
    assert row["alias"] == "chat-fast"
    assert row["provider"] == "groq"
    assert row["model"] == "llama-3.3-70b-versatile"
    assert row["attempt_index"] == 0
    assert row["outcome"] == "success"


async def test_success_row_stores_prompt_length_and_real_token_usage(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hello there"},
    ]
    before = dt.datetime.now(dt.UTC)

    await chat_client.post("/v1/chat/completions", json={**CHAT_REQUEST, "messages": messages})

    [row] = await usage_rows()
    # Every string the model reads: "system" + "Be brief." + "user" + "Hello there".
    assert row["prompt_chars"] == 30
    assert row["status_code"] == 200
    assert row["prompt_tokens"] == 5
    assert row["completion_tokens"] == 2
    # 30 characters -> 8 prompt tokens, plus the default 512 completion tokens.
    assert row["estimated_tokens"] == 8 + 512
    assert row["degraded"] is False
    assert row["error_message"] is None
    assert row["stream"] is False
    assert row["first_token_ms"] is None
    assert before <= row["created_at"] <= dt.datetime.now(dt.UTC)


async def test_token_columns_are_null_when_provider_returns_no_usage(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    body = completion_body("llama-3.3-70b-versatile")
    del body["usage"]
    respx_mock.post(GROQ_URL).respond(json=body)

    response = await chat_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    [row] = await usage_rows()
    assert row["prompt_tokens"] is None
    assert row["completion_tokens"] is None


async def test_failover_writes_one_row_per_examined_target(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).respond(429)
    respx_mock.post(GEMINI_URL).respond(503)
    respx_mock.post(OLLAMA_URL).respond(json=completion_body("llama3.2:3b"))

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    rows = await usage_rows()
    assert {row["request_id"] for row in rows} == {response.headers["X-Gateway-Request-Id"]}
    assert [
        (row["attempt_index"], row["provider"], row["outcome"], row["status_code"]) for row in rows
    ] == [
        (0, "groq", "rate_limited", 429),
        (1, "gemini", "unavailable", 503),
        (2, "ollama", "success", 200),
    ]
    assert [row["error_message"] for row in rows] == ["rate limited", "HTTP 503", None]
    assert [row["prompt_tokens"] for row in rows] == [None, None, 5]


@pytest.mark.parametrize(
    ("upstream_failure", "outcome", "status_code", "error_message"),
    [
        (
            httpx.ConnectError("connection refused"),
            "unavailable",
            None,
            "network error (ConnectError)",
        ),
        (httpx.Response(401), "misconfigured", 401, "misconfigured (HTTP 401)"),
        (
            httpx.Response(400, json=error_body("too long", code="context_length_exceeded")),
            "context_too_large",
            400,
            "request too large for this model",
        ),
        (httpx.Response(413), "context_too_large", 413, "request too large for this model"),
    ],
    ids=["network-error", "misconfigured", "context-too-large", "http-413"],
)
async def test_failed_attempt_row_describes_the_failure(
    failover_client: AsyncClient,
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
    upstream_failure: httpx.Response | Exception,
    outcome: str,
    status_code: int | None,
    error_message: str,
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=[upstream_failure])
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    failed_row, _ = await usage_rows()
    assert failed_row["outcome"] == outcome
    assert failed_row["status_code"] == status_code
    assert failed_row["error_message"] == error_message
    assert failed_row["prompt_tokens"] is None
    assert failed_row["completion_tokens"] is None


def slow_upstream(delay: float, response: httpx.Response) -> Callable[[httpx.Request], Any]:
    """A respx side effect that answers `response` after `delay` seconds."""

    async def _answer(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delay)
        return response

    return _answer


async def test_each_row_stores_the_latency_of_its_attempt(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=slow_upstream(0.2, httpx.Response(503)))
    respx_mock.post(GEMINI_URL).mock(
        side_effect=slow_upstream(0.05, httpx.Response(200, json=completion_body("gemini")))
    )

    await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    failed_row, success_row = await usage_rows()
    # Lower bounds allow for timers that fire up to one clock tick early (about 16 ms on Windows).
    assert 180 <= failed_row["latency_ms"] < 1000
    assert 30 <= success_row["latency_ms"] < 200


async def test_request_ending_in_503_logs_every_target(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    for url in (GROQ_URL, GEMINI_URL, OLLAMA_URL):
        respx_mock.post(url).respond(429)

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 503
    rows = await usage_rows()
    assert {row["request_id"] for row in rows} == {response.headers["X-Gateway-Request-Id"]}
    assert [(row["attempt_index"], row["outcome"]) for row in rows] == [
        (0, "rate_limited"),
        (1, "rate_limited"),
        (2, "rate_limited"),
    ]


async def test_request_rejected_by_a_target_logs_the_rejection(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).respond(
        400,
        json={
            "error": {
                "message": "'temperature' must be <= 2",
                "type": "invalid_request_error",
                "param": "temperature",
                "code": "invalid_value",
            }
        },
    )

    response = await failover_client.post(
        "/v1/chat/completions", json={**CHAT_REQUEST, "temperature": 5}
    )

    assert response.status_code == 400
    [row] = await usage_rows()
    assert row["request_id"] == response.headers["X-Gateway-Request-Id"]
    assert row["outcome"] == "invalid_request"
    assert row["status_code"] == 400
    assert row["error_message"] == (
        "invalid request (HTTP 400, type: invalid_request_error, code: invalid_value, "
        "param: temperature)"
    )


async def test_long_error_message_is_cut_to_500_characters(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    long_code = "x" * 600
    respx_mock.post(GROQ_URL).respond(400, json=error_body("bad request", code=long_code))

    response = await failover_client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.json()["error"]["code"] == long_code
    [row] = await usage_rows()
    assert row["error_message"].startswith("invalid request (HTTP 400, type: invalid_request_error")
    assert len(row["error_message"]) == 500


async def test_prompt_is_never_stored(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    prompt = "my confidential prompt"
    respx_mock.post(GROQ_URL).respond(400, json=error_body(f"cannot process '{prompt}'"))

    await failover_client.post(
        "/v1/chat/completions",
        json={**CHAT_REQUEST, "messages": [{"role": "user", "content": prompt}]},
    )

    [row] = await usage_rows()
    assert row["prompt_chars"] == len("user") + len(prompt)
    assert not any(prompt in str(value) for value in row.values())


async def test_usage_log_write_gives_up_when_postgresql_does_not_answer(
    write_config: WriteConfig,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    caplog: pytest.LogCaptureFixture,
    database_proxy: DatabaseProxy,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    settings = write_config(CHAT_CONFIG).model_copy(
        update={"database_url": database_proxy.url, "database_timeout": 0.5}
    )

    async with gateway_client(settings) as client:
        # A first request verifies the key while PostgreSQL answers.
        assert (await client.post("/v1/chat/completions", json=CHAT_REQUEST)).status_code == 200
        database_proxy.hang()
        with caplog.at_level(logging.ERROR):
            async with asyncio.timeout(3):
                # The key is still in the verification cache: no database query is needed.
                # The background write runs before the in-process client returns.
                response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    request_id = response.headers["X-Gateway-Request-Id"]
    assert f"could not write the usage log of request {request_id}" in caplog.messages


async def test_client_gets_its_response_when_the_usage_log_write_fails(
    chat_client: AsyncClient,
    respx_mock: respx.MockRouter,
    caplog: pytest.LogCaptureFixture,
    database_url: str,
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    prompt = "my confidential prompt"
    admin = create_async_engine(database_url)

    # Hide the table: the usage log INSERT fails, while API key checks still work.
    async with admin.begin() as connection:
        await connection.execute(text("ALTER TABLE usage_log RENAME TO usage_log_hidden"))
    try:
        with caplog.at_level(logging.ERROR):
            response = await chat_client.post(
                "/v1/chat/completions",
                json={**CHAT_REQUEST, "messages": [{"role": "user", "content": prompt}]},
            )
    finally:
        async with admin.begin() as connection:
            await connection.execute(text("ALTER TABLE usage_log_hidden RENAME TO usage_log"))
        await admin.dispose()

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Hello!"
    request_id = response.headers["X-Gateway-Request-Id"]
    assert f"could not write the usage log of request {request_id}" in caplog.messages
    assert prompt not in caplog.text


# --- Tenants: who consumed what ---


@pytest.mark.usefixtures("groq_and_gemini_keys")
async def test_every_row_records_the_tenant_and_key_of_its_request(
    write_config: WriteConfig,
    database_url: str,
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
) -> None:
    respx_mock.post(GROQ_URL).respond(503)
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))
    first, second = await new_tenant_key(database_url), await new_tenant_key(database_url)

    async with gateway_client(write_config(FAILOVER_CONFIG), api_key=first.key) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await client.post(
            "/v1/chat/completions",
            json=CHAT_REQUEST,
            headers={"Authorization": f"Bearer {second.key}"},
        )

    rows = await usage_rows()
    assert [(row["tenant_id"], row["api_key_id"], row["outcome"]) for row in rows] == [
        (first.owner.tenant_id, first.owner.api_key_id, "unavailable"),
        (first.owner.tenant_id, first.owner.api_key_id, "success"),
        (second.owner.tenant_id, second.owner.api_key_id, "unavailable"),
        (second.owner.tenant_id, second.owner.api_key_id, "success"),
    ]


@pytest.mark.usefixtures("groq_and_gemini_keys")
async def test_request_refused_by_a_tenant_quota_writes_one_row_without_provider(
    write_config: WriteConfig,
    database_url: str,
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    tenant = await new_tenant_key(database_url)
    config = CHAT_CONFIG + "\ntenants:\n  default_limits: { rpm: 1 }\n"

    async with gateway_client(write_config(config), api_key=tenant.key) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        refused = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert refused.status_code == 429
    _, row = await usage_rows()
    assert row["request_id"] == refused.headers["X-Gateway-Request-Id"]
    assert row["outcome"] == "rejected_tenant_quota"
    assert row["status_code"] == 429
    assert row["tenant_id"] == tenant.owner.tenant_id
    assert row["api_key_id"] == tenant.owner.api_key_id
    assert row["alias"] == "chat-fast"
    assert row["provider"] is None
    assert row["model"] is None
    assert row["attempt_index"] == 0
    assert row["latency_ms"] is None
    # "user" + "Hi": the prompt length, never the prompt.
    assert row["prompt_chars"] == 6
    assert row["degraded"] is False


@pytest.mark.usefixtures("groq_and_gemini_keys")
async def test_request_with_an_invalid_key_writes_no_row(
    write_config: WriteConfig, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))

    async with gateway_client(write_config(CHAT_CONFIG), api_key="gw_unknown") as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 401
    assert await usage_rows() == []
