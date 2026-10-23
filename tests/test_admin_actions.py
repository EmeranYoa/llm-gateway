"""Tests for admin actions: operators manage tenant keys, limits and cached answers
through the admin API or the admin CLI, and every change is recorded in `admin_actions`."""

import datetime as dt
import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
import respx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.keys import hash_key
from app.config import Settings
from app.storage.admin_actions import CLI
from app.storage.admin_keys import create_admin_key, list_admin_keys, revoke_admin_key
from app.storage.tenants import (
    create_api_key,
    find_tenant,
    list_api_keys,
    revoke_api_key,
    set_tenant_limits,
)
from tests.conftest import (
    MINIMAL_CONFIG,
    DatabaseProxy,
    gateway_client,
    new_api_key,
    run_admin,
    run_admin_command,
)
from tests.test_admin_api import admin_client, new_admin_key
from tests.upstream import CHAT_REQUEST, OLLAMA_URL, completion_body

WriteConfig = Callable[[str], Settings]
FetchActions = Callable[[], Awaitable[list[dict[str, Any]]]]

DEFAULT_LIMITS_CONFIG = (
    MINIMAL_CONFIG + "\ntenants:\n  default_limits: { rpm: 30, tokens_per_day: 100000 }\n"
)


@pytest.fixture
def settings(write_config: WriteConfig) -> Settings:
    return write_config(MINIMAL_CONFIG)


@pytest.fixture(autouse=True)
def ollama(respx_mock: respx.MockRouter) -> respx.Route:
    """A fake Ollama that answers every chat completion of the gateway."""
    return respx_mock.post(OLLAMA_URL).respond(json=completion_body("llama3.2:3b"))


@pytest.fixture
async def actions(database_url: str) -> AsyncIterator[FetchActions]:
    """Empty the `admin_actions` table, then return a function that reads its rows in order."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE admin_actions"))

    async def _fetch() -> list[dict[str, Any]]:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT * FROM admin_actions ORDER BY id"))
            return [dict(row) for row in result.mappings()]

    yield _fetch
    await engine.dispose()


async def table_text(database_url: str) -> str:
    """Every row of `admin_actions` as text, to check that no key ever appears in it."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.scalars(text("SELECT a::text FROM admin_actions AS a"))
            return "\n".join(rows)
    finally:
        await engine.dispose()


def assert_never_stored(table: str, key: str) -> None:
    assert key not in table
    assert hash_key(key) not in table


async def admin_key_id(database_url: str, key: str) -> int:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            found = await connection.scalar(
                text("SELECT id FROM admin_keys WHERE key_hash = :hash"), {"hash": hash_key(key)}
            )
    finally:
        await engine.dispose()
    assert found is not None
    return int(found)


async def tenant_id(database_url: str, name: str) -> int:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            found = await connection.scalar(
                text("SELECT id FROM tenants WHERE name = :name"), {"name": name}
            )
    finally:
        await engine.dispose()
    assert found is not None
    return int(found)


def unique_tenant() -> str:
    return f"tenant-{uuid4().hex[:8]}"


def is_utc(value: str) -> bool:
    return dt.datetime.fromisoformat(value).utcoffset() == dt.timedelta(0)


# --- Admin API ---


async def test_create_key_returns_the_key_once_and_records_the_action(
    settings: Settings, database_url: str, actions: FetchActions
) -> None:
    operator = f"alice-{uuid4().hex[:6]}"
    admin_key = await new_admin_key(database_url, operator)
    tenant = unique_tenant()

    async with admin_client(settings, admin_key) as client:
        response = await client.post("/admin/v1/keys", json={"tenant": tenant, "rpm": 5})
        listed = await client.get(f"/admin/v1/tenants/{tenant}/keys")

    assert response.status_code == 201
    created = response.json()
    assert set(created) == {"id", "tenant", "prefix", "key"}
    assert created["tenant"] == tenant
    assert created["key"].startswith("gw_")
    assert created["key"].startswith(created["prefix"])
    # The full key is never shown again.
    assert created["key"] not in listed.text
    [action] = await actions()
    assert action["admin_key_id"] == await admin_key_id(database_url, admin_key)
    assert action["actor"] == operator
    assert action["action"] == "create-key"
    assert action["target"] == tenant
    assert action["details"] == {"key_id": created["id"], "prefix": created["prefix"], "rpm": 5}
    assert action["created_at"].utcoffset() == dt.timedelta(0)
    assert_never_stored(await table_text(database_url), created["key"])


async def test_created_key_works_on_the_gateway(settings: Settings, database_url: str) -> None:
    admin_key = await new_admin_key(database_url)

    async with admin_client(settings, admin_key) as client:
        created = (await client.post("/admin/v1/keys", json={"tenant": unique_tenant()})).json()
    async with gateway_client(settings, api_key=created["key"]) as gateway:
        response = await gateway.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200


async def test_tenant_keys_show_own_and_effective_limits(
    write_config: WriteConfig, database_url: str
) -> None:
    settings = write_config(DEFAULT_LIMITS_CONFIG)
    admin_key = await new_admin_key(database_url)
    tenant = unique_tenant()

    async with admin_client(settings, admin_key) as client:
        first = (
            await client.post("/admin/v1/keys", json={"tenant": tenant, "tokens_per_day": 500})
        ).json()
        second = (await client.post("/admin/v1/keys", json={"tenant": tenant})).json()
        response = await client.get(f"/admin/v1/tenants/{tenant}/keys")

    assert response.status_code == 200
    body = response.json()
    assert body["tenant"] == tenant
    assert body["limits"] == {"rpm": None, "tokens_per_day": 500}
    assert body["effective_limits"] == {"rpm": 30, "tokens_per_day": 500}
    assert [key["id"] for key in body["keys"]] == [first["id"], second["id"]]
    key = body["keys"][0]
    assert key["prefix"] == first["prefix"]
    assert key["tenant"] == tenant
    assert is_utc(key["created_at"])
    assert key["last_used_at"] is None
    assert key["revoked_at"] is None


async def test_keys_of_an_unknown_tenant_is_404(settings: Settings, database_url: str) -> None:
    admin_key = await new_admin_key(database_url)

    async with admin_client(settings, admin_key) as client:
        response = await client.get("/admin/v1/tenants/no-such-tenant/keys")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tenant_not_found"


async def test_revoke_key_refuses_it_on_the_gateway_and_records_the_action(
    settings: Settings, database_url: str, actions: FetchActions
) -> None:
    admin_key = await new_admin_key(database_url)
    tenant = unique_tenant()

    async with admin_client(settings, admin_key) as client:
        created = (await client.post("/admin/v1/keys", json={"tenant": tenant})).json()
        revoked = await client.post(f"/admin/v1/keys/{created['id']}/revoke")
        again = await client.post(f"/admin/v1/keys/{created['id']}/revoke")
        unknown = await client.post("/admin/v1/keys/999999999/revoke")
    async with gateway_client(settings, api_key=created["key"]) as gateway:
        refused = await gateway.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert revoked.status_code == 200
    body = revoked.json()
    assert body["id"] == created["id"]
    assert body["tenant"] == tenant
    assert body["prefix"] == created["prefix"]
    assert is_utc(body["revoked_at"])
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "key_already_revoked"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "key_not_found"
    assert refused.status_code == 401
    # Refused revocations change nothing, so they are not recorded.
    _, action = await actions()
    assert action["action"] == "revoke-key"
    assert action["target"] == str(created["id"])
    assert action["details"] == {"tenant": tenant, "prefix": created["prefix"]}


async def test_set_limits_applies_them_on_the_gateway_and_records_the_action(
    settings: Settings, database_url: str, actions: FetchActions
) -> None:
    admin_key = await new_admin_key(database_url)
    tenant = unique_tenant()

    async with admin_client(settings, admin_key) as client:
        created = (await client.post("/admin/v1/keys", json={"tenant": tenant})).json()
        response = await client.put(f"/admin/v1/tenants/{tenant}/limits", json={"rpm": 1})
    async with gateway_client(settings, api_key=created["key"]) as gateway:
        first = await gateway.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await gateway.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert response.json() == {
        "tenant": tenant,
        "limits": {"rpm": 1, "tokens_per_day": None},
        "effective_limits": {"rpm": 1, "tokens_per_day": None},
    }
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "tenant_quota_exceeded"
    _, action = await actions()
    assert action["action"] == "set-limits"
    assert action["target"] == tenant
    assert action["details"] == {"rpm": 1}


async def test_set_limits_keeps_the_limits_not_given(settings: Settings, database_url: str) -> None:
    admin_key = await new_admin_key(database_url)
    tenant = unique_tenant()

    async with admin_client(settings, admin_key) as client:
        await client.post("/admin/v1/keys", json={"tenant": tenant, "rpm": 10})
        response = await client.put(
            f"/admin/v1/tenants/{tenant}/limits", json={"tokens_per_day": 9000}
        )

    assert response.json()["limits"] == {"rpm": 10, "tokens_per_day": 9000}


@pytest.mark.parametrize(
    "body",
    [{}, {"rpm": None}, {"rpm": 0}, {"tokens_per_day": -5}, {"rpm": "fast"}, {"burst": 3}],
    ids=["empty", "only-null", "zero", "negative", "not-a-number", "unknown-field"],
)
async def test_set_limits_refuses_invalid_limits(
    settings: Settings, database_url: str, actions: FetchActions, body: dict[str, Any]
) -> None:
    admin_key = await new_admin_key(database_url)
    tenant = unique_tenant()
    async with admin_client(settings, admin_key) as client:
        await client.post("/admin/v1/keys", json={"tenant": tenant})

        response = await client.put(f"/admin/v1/tenants/{tenant}/limits", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert [action["action"] for action in await actions()] == ["create-key"]


async def test_set_limits_of_an_unknown_tenant_is_404(
    settings: Settings, database_url: str, actions: FetchActions
) -> None:
    admin_key = await new_admin_key(database_url)

    async with admin_client(settings, admin_key) as client:
        response = await client.put("/admin/v1/tenants/no-such-tenant/limits", json={"rpm": 5})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tenant_not_found"
    assert await actions() == []


@pytest.mark.parametrize(
    "body",
    [{"tenant": ""}, {"tenant": "acme", "rpm": 0}, {"tenant": "acme", "key": "gw_mine"}],
    ids=["empty-tenant", "zero-rpm", "unknown-field"],
)
async def test_create_key_refuses_an_invalid_body(
    settings: Settings, database_url: str, body: dict[str, Any]
) -> None:
    admin_key = await new_admin_key(database_url)

    async with admin_client(settings, admin_key) as client:
        response = await client.post("/admin/v1/keys", json=body)

    assert response.status_code == 400


# --- Cache ---


def entry_key(tenant: int, alias: str, question: str = "Hi") -> str:
    """A cache entry key in the format of `app/cache/store.py`."""
    return f"cache:{tenant}:{alias}:{hashlib.sha256(question.encode()).hexdigest()}"


async def add_entries(redis_url: str, *keys: str) -> None:
    redis = Redis.from_url(redis_url)
    try:
        for key in keys:
            await redis.hset(key, mapping={"body": "{}", "provider": "groq", "model": "m"})
    finally:
        await redis.aclose()


async def remaining_keys(redis_url: str) -> set[str]:
    redis = Redis.from_url(redis_url)
    try:
        return {key.decode() for key in await redis.keys("*")}
    finally:
        await redis.aclose()


async def test_clear_cache_of_a_tenant_and_alias_records_the_action(
    settings: Settings, database_url: str, redis_url: str, actions: FetchActions
) -> None:
    admin_key = await new_admin_key(database_url)
    tenant = unique_tenant()
    async with admin_client(settings, admin_key) as client:
        await client.post("/admin/v1/keys", json={"tenant": tenant})
        tenant_number = await tenant_id(database_url, tenant)
        await add_entries(
            redis_url,
            entry_key(tenant_number, "chat-fast", "Hi"),
            entry_key(tenant_number, "chat-fast", "Hello"),
            entry_key(tenant_number, "chat-smart"),
        )

        by_alias = await client.post(
            "/admin/v1/cache/clear", json={"tenant": tenant, "alias": "chat-fast"}
        )
        remaining_after_alias = await remaining_keys(redis_url)
        whole_tenant = await client.post("/admin/v1/cache/clear", json={"tenant": tenant})

    assert by_alias.status_code == 200
    assert by_alias.json() == {"removed": 2}
    assert remaining_after_alias == {entry_key(tenant_number, "chat-smart")}
    assert whole_tenant.json() == {"removed": 1}
    assert await remaining_keys(redis_url) == set()
    _, alias_action, tenant_action = await actions()
    assert alias_action["action"] == "clear-cache"
    assert alias_action["target"] == tenant
    assert alias_action["details"] == {"alias": "chat-fast", "removed": 2}
    assert tenant_action["details"] == {"alias": None, "removed": 1}


async def test_clear_cache_of_an_unknown_tenant_is_404(
    settings: Settings, database_url: str, actions: FetchActions
) -> None:
    admin_key = await new_admin_key(database_url)

    async with admin_client(settings, admin_key) as client:
        response = await client.post("/admin/v1/cache/clear", json={"tenant": "no-such-tenant"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tenant_not_found"
    assert await actions() == []


# --- Action history ---


async def test_actions_are_listed_newest_first_with_a_cursor(
    settings: Settings, database_url: str, actions: FetchActions
) -> None:
    operator = f"carol-{uuid4().hex[:6]}"
    admin_key = await new_admin_key(database_url, operator)
    tenant = unique_tenant()

    async with admin_client(settings, admin_key) as client:
        created = (await client.post("/admin/v1/keys", json={"tenant": tenant})).json()
        await client.put(f"/admin/v1/tenants/{tenant}/limits", json={"rpm": 7})
        await client.post(f"/admin/v1/keys/{created['id']}/revoke")
        first_page = (await client.get("/admin/v1/actions", params={"limit": 2})).json()
        second_page = (
            await client.get(
                "/admin/v1/actions", params={"limit": 2, "before": first_page["next_before"]}
            )
        ).json()

    names = [action["action"] for action in first_page["actions"]]
    assert names == ["revoke-key", "set-limits"]
    assert first_page["next_before"] == first_page["actions"][-1]["id"]
    assert [action["action"] for action in second_page["actions"]] == ["create-key"]
    assert second_page["next_before"] is None
    newest = first_page["actions"][0]
    assert newest["actor"] == operator
    assert newest["admin_key_id"] == await admin_key_id(database_url, admin_key)
    assert newest["target"] == str(created["id"])
    assert newest["details"] == {"tenant": tenant, "prefix": created["prefix"]}
    assert is_utc(newest["created_at"])
    assert created["key"] not in str(first_page) + str(second_page)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 1001}, {"before": "x"}])
async def test_actions_refuse_an_invalid_page(
    settings: Settings, database_url: str, params: dict[str, Any]
) -> None:
    admin_key = await new_admin_key(database_url)

    async with admin_client(settings, admin_key) as client:
        response = await client.get("/admin/v1/actions", params=params)

    assert response.status_code == 400


# --- Access and outages ---


ACTION_REQUESTS = [
    ("GET", "/admin/v1/tenants/acme/keys", None),
    ("POST", "/admin/v1/keys", {"tenant": "acme"}),
    ("POST", "/admin/v1/keys/1/revoke", None),
    ("PUT", "/admin/v1/tenants/acme/limits", {"rpm": 5}),
    ("POST", "/admin/v1/cache/clear", {"tenant": "acme"}),
    ("GET", "/admin/v1/actions", None),
]
ACTION_IDS = ["tenant-keys", "create-key", "revoke-key", "set-limits", "clear-cache", "actions"]


@pytest.mark.parametrize(("method", "path", "body"), ACTION_REQUESTS, ids=ACTION_IDS)
async def test_actions_need_an_admin_key(
    settings: Settings, database_url: str, method: str, path: str, body: dict[str, Any] | None
) -> None:
    tenant_key = await new_api_key(database_url)

    async with admin_client(settings, tenant_key) as client:
        response = await client.request(method, path, json=body)

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), ACTION_REQUESTS, ids=ACTION_IDS)
async def test_actions_answer_503_when_postgresql_is_down(
    write_config: WriteConfig,
    database_url: str,
    database_proxy: DatabaseProxy,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    settings = write_config(MINIMAL_CONFIG).model_copy(update={"database_url": database_proxy.url})
    admin_key = await new_admin_key(database_url)

    async with admin_client(settings, admin_key) as client:
        assert (await client.get("/admin/v1/me")).status_code == 200  # the key is now cached
        await database_proxy.stop()
        response = await client.request(method, path, json=body)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"


# --- Admin CLI ---


async def test_cli_records_its_actions_as_cli(
    database_url: str,
    redis_url: str,
    actions: FetchActions,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_URL", redis_url)
    tenant = unique_tenant()
    operator = f"dave-{uuid4().hex[:6]}"

    created = await run_admin(database_url, "create-key", "--tenant", tenant, "--rpm", "60")
    key = created.split()[-1]
    [key_line] = (await run_admin(database_url, "list-keys", "--tenant", tenant)).splitlines()[1:]
    key_id, _, prefix = key_line.split()[:3]
    await run_admin(database_url, "set-limits", "--tenant", tenant, "--tokens-per-day", "5000")
    await run_admin(database_url, "revoke-key", key_id)
    await add_entries(redis_url, entry_key(await tenant_id(database_url, tenant), "chat-fast"))
    await run_admin(database_url, "clear-cache", "--tenant", tenant, "--alias", "chat-fast")
    await run_admin(database_url, "clear-cache", "--all")
    admin_created = await run_admin(database_url, "create-admin-key", "--name", operator)
    admin_key = admin_created.split()[-1]
    [admin_line] = [
        line
        for line in (await run_admin(database_url, "list-admin-keys")).splitlines()
        if operator in line
    ]
    admin_id, _, admin_prefix = admin_line.split()[:3]
    await run_admin(database_url, "revoke-admin-key", admin_id)

    rows = await actions()
    assert all(row["actor"] == "cli" and row["admin_key_id"] is None for row in rows)
    assert [(row["action"], row["target"], row["details"]) for row in rows] == [
        ("create-key", tenant, {"key_id": int(key_id), "prefix": prefix, "rpm": 60}),
        ("set-limits", tenant, {"tokens_per_day": 5000}),
        ("revoke-key", key_id, {"tenant": tenant, "prefix": prefix}),
        ("clear-cache", tenant, {"alias": "chat-fast", "removed": 1}),
        ("clear-cache", None, {"alias": None, "removed": 0}),
        ("create-admin-key", admin_id, {"name": operator, "prefix": admin_prefix}),
        ("revoke-admin-key", admin_id, {"name": operator, "prefix": admin_prefix}),
    ]
    table = await table_text(database_url)
    assert_never_stored(table, key)
    assert_never_stored(table, admin_key)


async def test_cli_records_nothing_when_a_command_fails(
    database_url: str, actions: FetchActions
) -> None:
    await run_admin_command(database_url, "revoke-key", "999999999")
    await run_admin_command(database_url, "set-limits", "--tenant", "no-such-tenant", "--rpm", "5")
    await run_admin_command(database_url, "revoke-admin-key", "999999999")

    assert await actions() == []


async def test_clear_cache_answers_503_when_redis_is_down(
    write_config: WriteConfig, database_url: str, actions: FetchActions
) -> None:
    # Nothing listens on port 1: every Redis command fails at once.
    settings = write_config(MINIMAL_CONFIG).model_copy(
        update={"redis_url": "redis://127.0.0.1:1/0"}
    )
    admin_key = await new_admin_key(database_url)
    tenant = unique_tenant()

    async with admin_client(settings, admin_key) as client:
        await client.post("/admin/v1/keys", json={"tenant": tenant})
        response = await client.post("/admin/v1/cache/clear", json={"tenant": tenant})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "redis_unavailable"
    assert [action["action"] for action in await actions()] == ["create-key"]


# --- Same transaction ---


class RecordingFailed(Exception):
    pass


async def failing_record(*_: object, **__: object) -> None:
    raise RecordingFailed


async def test_a_change_is_rolled_back_when_its_action_cannot_be_recorded(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(database_url)
    tenant = unique_tenant()
    try:
        new_key = await create_api_key(engine, tenant, rpm=10, actor=CLI)
        monkeypatch.setattr("app.storage.tenants.record_action", failing_record)

        with pytest.raises(RecordingFailed):
            await create_api_key(engine, tenant, actor=CLI)
        with pytest.raises(RecordingFailed):
            await set_tenant_limits(engine, tenant, rpm=99, actor=CLI)
        with pytest.raises(RecordingFailed):
            await revoke_api_key(engine, new_key.owner.api_key_id, actor=CLI)

        keys = await list_api_keys(engine, tenant)
        found = await find_tenant(engine, tenant)
    finally:
        await engine.dispose()
    assert [key.id for key in keys] == [new_key.owner.api_key_id]
    assert keys[0].revoked_at is None
    assert found is not None
    assert found.limits.rpm == 10


async def test_an_admin_key_change_is_rolled_back_when_its_action_cannot_be_recorded(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(database_url)
    name = f"erin-{uuid4().hex[:6]}"
    try:
        new_key = await create_admin_key(engine, name, actor=CLI)
        monkeypatch.setattr("app.storage.admin_keys.record_action", failing_record)

        with pytest.raises(RecordingFailed):
            await create_admin_key(engine, name, actor=CLI)
        with pytest.raises(RecordingFailed):
            await revoke_admin_key(engine, new_key.identity.admin_key_id, actor=CLI)

        keys = [key for key in await list_admin_keys(engine) if key.name == name]
    finally:
        await engine.dispose()
    assert [(key.id, key.revoked_at) for key in keys] == [(new_key.identity.admin_key_id, None)]


# --- OpenAPI schema, from which the dashboard generates its types ---


async def test_openapi_schema_describes_the_action_bodies(settings: Settings) -> None:
    async with admin_client(settings, None) as client:
        schema = (await client.get("/openapi.json")).json()

    models = schema["components"]["schemas"]
    for name in ("TenantKeys", "CreatedKey", "ApiKey", "TenantLimitsView", "AdminActionPage"):
        assert name in models
    assert "key" not in models["ApiKey"]["properties"]
    revoke = schema["paths"]["/admin/v1/keys/{key_id}/revoke"]["post"]
    assert set(revoke["responses"]) >= {"200", "404", "409"}


async def test_tenant_names_lists_every_tenant_in_order(
    settings: Settings, database_url: str
) -> None:
    admin_key = await new_admin_key(database_url)
    created = sorted([f"names-{uuid4().hex[:8]}" for _ in range(3)])
    for name in reversed(created):
        await run_admin(database_url, "create-key", "--tenant", name)

    async with admin_client(settings, admin_key) as client:
        response = await client.get("/admin/v1/tenant-names")

    assert response.status_code == 200
    names = response.json()["tenants"]
    assert names == sorted(names)
    assert [name for name in names if name in created] == created
