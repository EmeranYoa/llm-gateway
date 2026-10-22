"""Tests for gateway API keys: the admin CLI creates them, the API checks them."""

import asyncio
import datetime as dt
import logging
import re
from collections.abc import Callable
from uuid import uuid4

import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from tests.conftest import (
    DatabaseProxy,
    gateway_client,
    new_api_key,
    run_admin,
    run_admin_command,
)
from tests.upstream import CHAT_CONFIG, CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body


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


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer gw_secret-part-of-the-key", "Bearer secret-part-of-the-key"],
    ids=["missing", "unknown", "malformed"],
)
async def test_refused_key_is_logged_with_the_client_ip_and_no_part_of_the_key(
    chat_settings: Settings, caplog: pytest.LogCaptureFixture, authorization: str | None
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    with caplog.at_level(logging.WARNING):
        async with gateway_client(chat_settings, api_key=None) as client:
            await client.post("/v1/chat/completions", json=CHAT_REQUEST, headers=headers)

    # The in-process test client connects from 127.0.0.1.
    [record] = [record for record in caplog.records if "127.0.0.1" in record.getMessage()]
    assert record.levelno == logging.WARNING
    assert "API key" in record.getMessage()
    assert "secret" not in caplog.text
    assert "part-of" not in caplog.text


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


async def test_list_keys_shows_when_a_key_was_last_used(
    chat_settings: Settings, database_url: str, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    tenant = unique_tenant()
    key = await create_key(database_url, tenant)
    before = dt.datetime.now(dt.UTC).replace(second=0, microsecond=0)

    async with gateway_client(chat_settings, api_key=key) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    [row] = parse_table(await run_admin(database_url, "list-keys", "--tenant", tenant))
    last_used = dt.datetime.strptime(row["LAST USED (UTC)"], "%Y-%m-%d %H:%M").replace(
        tzinfo=dt.UTC
    )
    assert before <= last_used <= dt.datetime.now(dt.UTC)


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


async def test_revoked_key_keeps_working_until_its_cache_entry_expires(
    chat_settings: Settings, database_url: str, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    tenant = unique_tenant()
    key = await create_key(database_url, tenant)
    settings = chat_settings.model_copy(update={"auth_cache_ttl": 60.0})

    async with gateway_client(settings, api_key=key) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await run_admin(database_url, "revoke-key", await key_id(database_url, tenant, key))
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.status_code == 200
    # The key was verified less than AUTH_CACHE_TTL ago: the gateway does not query
    # the database again, so it does not see the revocation yet (ADR 0004).
    assert second.status_code == 200


async def test_revocation_takes_effect_when_the_cache_entry_expires(
    chat_settings: Settings, database_url: str, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    tenant = unique_tenant()
    key = await create_key(database_url, tenant)
    settings = chat_settings.model_copy(update={"auth_cache_ttl": 0.5})

    async with gateway_client(settings, api_key=key) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await run_admin(database_url, "revoke-key", await key_id(database_url, tenant, key))
        await asyncio.sleep(0.5)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.status_code == 200
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "invalid_api_key"


async def test_new_tenant_limits_take_effect_when_the_cache_entry_expires(
    chat_settings: Settings, database_url: str, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    tenant = unique_tenant()
    key = await create_key(database_url, tenant)
    settings = chat_settings.model_copy(update={"auth_cache_ttl": 0.5})

    async with gateway_client(settings, api_key=key) as client:
        # Verify the key: the cache now holds its tenant without an RPM limit.
        assert (await client.post("/v1/chat/completions", json=CHAT_REQUEST)).status_code == 200
        await run_admin(database_url, "set-limits", "--tenant", tenant, "--rpm", "1")
        await asyncio.sleep(0.5)
        statuses = [
            (await client.post("/v1/chat/completions", json=CHAT_REQUEST)).status_code
            for _ in range(2)
        ]

    # The cache keeps the whole key owner, tenant limits included: they are refreshed too.
    assert statuses == [200, 429]


async def start_outage(proxy: DatabaseProxy, outage: str) -> None:
    """Make PostgreSQL look down ("stopped") or stuck ("hanging") to the gateway."""
    if outage == "stopped":
        await proxy.stop()
    else:
        proxy.hang()


@pytest.fixture
def proxied_settings(chat_settings: Settings, database_proxy: DatabaseProxy) -> Settings:
    """Settings of a gateway that reaches PostgreSQL through `database_proxy`."""
    return chat_settings.model_copy(
        update={"database_url": database_proxy.url, "database_timeout": 0.5}
    )


@pytest.mark.parametrize("outage", ["stopped", "hanging"])
async def test_recently_verified_key_passes_while_postgresql_is_unavailable(
    proxied_settings: Settings,
    database_proxy: DatabaseProxy,
    database_url: str,
    respx_mock: respx.MockRouter,
    outage: str,
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    key = await new_api_key(database_url)
    settings = proxied_settings.model_copy(
        update={"auth_cache_ttl": 0.1, "auth_grace_period": 60.0}
    )

    async with asyncio.timeout(10), gateway_client(settings, api_key=key) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await start_outage(database_proxy, outage)
        await asyncio.sleep(0.2)  # the cache entry expires: the gateway queries the database
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.status_code == 200
    # The key was verified less than AUTH_GRACE_PERIOD ago: it keeps working (ADR 0004).
    assert second.status_code == 200


async def test_key_verified_before_the_grace_period_is_refused_while_postgresql_is_down(
    proxied_settings: Settings,
    database_proxy: DatabaseProxy,
    database_url: str,
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    key = await new_api_key(database_url)
    settings = proxied_settings.model_copy(update={"auth_cache_ttl": 0.1, "auth_grace_period": 0.3})

    async with asyncio.timeout(10), gateway_client(settings, api_key=key) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await asyncio.sleep(0.4)
        await database_proxy.stop()
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.status_code == 200
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "authentication_unavailable"


async def test_key_found_revoked_is_not_trusted_again_while_postgresql_is_down(
    proxied_settings: Settings,
    database_proxy: DatabaseProxy,
    database_url: str,
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    tenant = unique_tenant()
    key = await create_key(database_url, tenant)
    settings = proxied_settings.model_copy(
        update={"auth_cache_ttl": 0.1, "auth_grace_period": 60.0}
    )

    async with asyncio.timeout(20), gateway_client(settings, api_key=key) as client:
        statuses = [(await client.post("/v1/chat/completions", json=CHAT_REQUEST)).status_code]
        await run_admin(database_url, "revoke-key", await key_id(database_url, tenant, key))
        await asyncio.sleep(0.2)
        statuses.append((await client.post("/v1/chat/completions", json=CHAT_REQUEST)).status_code)
        await database_proxy.stop()
        statuses.append((await client.post("/v1/chat/completions", json=CHAT_REQUEST)).status_code)

    assert statuses == [200, 401, 503]


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
