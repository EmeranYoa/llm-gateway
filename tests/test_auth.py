"""Tests for gateway API keys: the admin CLI creates them, the API checks them."""

import asyncio
import logging
import os
import sys
from collections.abc import Callable

import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from tests.conftest import gateway_client, new_api_key
from tests.upstream import CHAT_CONFIG, CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body


async def run_admin(database_url: str, *args: str) -> str:
    """Run the admin CLI as an operator would, and return what it prints."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.admin",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "DATABASE_URL": database_url},
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    return stdout.decode()


@pytest.fixture
def chat_settings(
    write_config: Callable[[str], Settings], monkeypatch: pytest.MonkeyPatch
) -> Settings:
    """Settings of a gateway routing `chat-fast` to a fake Groq provider."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return write_config(CHAT_CONFIG)


async def test_key_created_by_the_cli_is_accepted(
    chat_settings: Settings, database_url: str, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))

    output = await run_admin(database_url, "create-key", "--tenant", "acme")
    [key] = [word for word in output.split() if word.startswith("gw_")]

    async with gateway_client(chat_settings, api_key=key) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer gw_not-a-real-key", "Bearer ", "Basic dXNlcjpwYXNz", "gw_without_scheme"],
    ids=["missing", "unknown", "empty", "other-scheme", "no-scheme"],
)
async def test_request_without_a_valid_key_is_refused(
    chat_settings: Settings, respx_mock: respx.MockRouter, authorization: str | None
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    headers = {} if authorization is None else {"Authorization": authorization}

    async with gateway_client(chat_settings, api_key=None) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"] == {
        "message": "Missing or invalid API key.",
        "type": "invalid_request_error",
        "param": None,
        "code": "invalid_api_key",
    }
    assert not groq.called


async def test_key_check_gives_up_when_postgresql_does_not_answer(
    chat_settings: Settings, silent_server: int
) -> None:
    settings = chat_settings.model_copy(
        update={
            "database_url": f"postgresql+asyncpg://gateway:gateway@127.0.0.1:{silent_server}/gateway",
            "database_timeout": 0.5,
        }
    )

    async with asyncio.timeout(5), gateway_client(settings, api_key="gw_any-key") as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    # An unchecked key is never accepted (ADR 0004).
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"


async def test_api_key_is_never_logged_nor_stored_in_clear(
    chat_settings: Settings,
    database_url: str,
    respx_mock: respx.MockRouter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    key = await new_api_key(database_url)

    with caplog.at_level(logging.DEBUG):
        async with gateway_client(chat_settings, api_key=key) as client:
            await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert key not in caplog.text
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        rows = (await connection.execute(text("SELECT * FROM api_keys"))).mappings().all()
    await engine.dispose()
    assert not any(key in str(value) for row in rows for value in row.values())
    # Only a short prefix is kept in clear, to recognise the key in listings.
    assert key[:9] in {row["prefix"] for row in rows}
