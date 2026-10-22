"""Tests for gateway API keys: the admin CLI creates them, the API checks them."""

import asyncio
import logging
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from tests.conftest import gateway_client, new_api_key
from tests.upstream import CHAT_CONFIG, CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body


@dataclass(frozen=True)
class AdminRun:
    """Result of one admin CLI command."""

    exit_code: int | None
    stdout: str
    stderr: str


async def run_admin_command(database_url: str, *args: str) -> AdminRun:
    """Run the admin CLI as an operator would, whatever its exit code."""
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
    return AdminRun(process.returncode, stdout.decode(), stderr.decode())


async def run_admin(database_url: str, *args: str) -> str:
    """Run an admin CLI command that must succeed, and return what it prints."""
    run = await run_admin_command(database_url, *args)
    assert run.exit_code == 0, run.stderr
    return run.stdout


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


def unique_tenant() -> str:
    """A tenant name no other test uses, because the test database is shared."""
    return f"tenant-{uuid4().hex[:8]}"


async def create_key(database_url: str, tenant: str) -> str:
    """Create a key for `tenant` with the admin CLI and return the printed key."""
    output = await run_admin(database_url, "create-key", "--tenant", tenant)
    [key] = [word for word in output.split() if word.startswith("gw_")]
    return key


def parse_table(output: str) -> list[dict[str, str]]:
    """Read the table printed by `list-keys`: one dict per row, keyed by column title.

    Columns are separated by at least two spaces.
    """
    header, *rows = output.strip().splitlines()
    titles = re.split(r"\s{2,}", header.strip())
    return [dict(zip(titles, re.split(r"\s{2,}", row.strip()), strict=True)) for row in rows]


async def test_list_keys_shows_a_short_prefix_never_the_full_key(database_url: str) -> None:
    tenant = unique_tenant()
    key = await create_key(database_url, tenant)

    output = await run_admin(database_url, "list-keys", "--tenant", tenant)

    assert key not in output
    [row] = parse_table(output)
    assert row["TENANT"] == tenant
    assert row["PREFIX"] == key[:9]
    assert row["ID"].isdigit()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", row["CREATED (UTC)"])
    assert row["LAST USED (UTC)"] == "never"
    assert row["STATUS"] == "active"


async def test_list_keys_without_a_tenant_lists_every_tenant(database_url: str) -> None:
    first, second = unique_tenant(), unique_tenant()
    first_key = await create_key(database_url, first)
    second_key = await create_key(database_url, second)

    output = await run_admin(database_url, "list-keys")

    listed = {(row["TENANT"], row["PREFIX"]) for row in parse_table(output)}
    assert {(first, first_key[:9]), (second, second_key[:9])} <= listed


async def key_id(database_url: str, tenant: str, key: str) -> str:
    """Find the id of `key` in the `list-keys` output, as an operator would."""
    output = await run_admin(database_url, "list-keys", "--tenant", tenant)
    [row] = [row for row in parse_table(output) if row["PREFIX"] == key[:9]]
    return row["ID"]


async def test_revoked_key_is_refused(
    chat_settings: Settings, database_url: str, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    tenant = unique_tenant()
    key = await create_key(database_url, tenant)

    await run_admin(database_url, "revoke-key", await key_id(database_url, tenant, key))

    async with gateway_client(chat_settings, api_key=key) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    [row] = parse_table(await run_admin(database_url, "list-keys", "--tenant", tenant))
    assert row["STATUS"] == "revoked"


async def test_revoking_an_unknown_key_fails(database_url: str) -> None:
    run = await run_admin_command(database_url, "revoke-key", "999999999")

    assert run.exit_code == 1
    assert "no API key with id 999999999" in run.stderr


async def test_revoking_a_key_twice_fails(database_url: str) -> None:
    tenant = unique_tenant()
    key = await create_key(database_url, tenant)
    api_key_id = await key_id(database_url, tenant, key)
    await run_admin(database_url, "revoke-key", api_key_id)

    run = await run_admin_command(database_url, "revoke-key", api_key_id)

    assert run.exit_code == 1
    assert f"API key {api_key_id} is already revoked" in run.stderr


async def test_a_key_can_be_rotated_without_downtime(
    chat_settings: Settings, database_url: str, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    tenant = unique_tenant()
    old_key = await create_key(database_url, tenant)
    new_key = await create_key(database_url, tenant)

    async def status_with(key: str) -> int:
        async with gateway_client(chat_settings, api_key=key) as client:
            response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        return response.status_code

    # Both keys of the tenant work at the same time...
    assert await status_with(old_key) == 200
    assert await status_with(new_key) == 200
    # ...so the old one can be revoked once every client uses the new one.
    await run_admin(database_url, "revoke-key", await key_id(database_url, tenant, old_key))
    assert await status_with(old_key) == 401
    assert await status_with(new_key) == 200
