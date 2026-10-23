"""Tests for `clear-cache`: an operator removes cached answers with the admin CLI."""

import hashlib
from collections.abc import AsyncIterator, Callable
from uuid import uuid4

import httpx
import pytest
import respx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.storage.tenants import create_api_key
from tests.conftest import gateway_client, run_admin, run_admin_command
from tests.upstream import CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body

GROQ_MODEL = "llama-3.3-70b-versatile"

CACHE_CONFIG = f"""
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      {GROQ_MODEL}: {{}}
routes:
  chat-fast: [ groq/{GROQ_MODEL} ]
  chat-smart: [ groq/{GROQ_MODEL} ]
cache: {{ aliases: {{ chat-fast: {{}}, chat-smart: {{}} }} }}
"""


@pytest.fixture
async def redis(redis_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Redis]:
    """The test Redis, also given to the admin CLI through `REDIS_URL`."""
    monkeypatch.setenv("REDIS_URL", redis_url)
    client = Redis.from_url(redis_url)
    yield client
    await client.aclose()


async def new_tenant(database_url: str) -> tuple[str, int, str]:
    """Create a tenant with a unique name. Returns its name, its id and an API key."""
    name = f"tenant-{uuid4().hex[:8]}"
    engine = create_async_engine(database_url)
    try:
        new_key = await create_api_key(engine, name)
    finally:
        await engine.dispose()
    return name, new_key.owner.tenant_id, new_key.key


def entry_key(tenant_id: int, alias: str, question: str = "Hi") -> str:
    """A cache entry key in the format of `app/cache/store.py`."""
    exact_hash = hashlib.sha256(question.encode()).hexdigest()
    return f"cache:{tenant_id}:{alias}:{exact_hash}"


async def add_entries(redis: Redis, *keys: str) -> None:
    for key in keys:
        await redis.hset(key, mapping={"body": "{}", "provider": "groq", "model": GROQ_MODEL})


async def remaining_keys(redis: Redis) -> set[str]:
    return {key.decode() for key in await redis.keys("*")}


async def test_clear_cache_of_a_tenant_removes_only_its_answers(
    database_url: str,
    redis: Redis,
    write_config: Callable[[str], Settings],
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    groq = respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=completion_body(GROQ_MODEL))
    )
    settings = write_config(CACHE_CONFIG)
    cleared_tenant, _, cleared_key = await new_tenant(database_url)
    _, kept_tenant_id, kept_key = await new_tenant(database_url)
    async with gateway_client(settings, api_key=cleared_key) as client:
        for alias in ("chat-fast", "chat-smart"):
            await client.post("/v1/chat/completions", json={**CHAT_REQUEST, "model": alias})
    async with gateway_client(settings, api_key=kept_key) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    output = await run_admin(database_url, "clear-cache", "--tenant", cleared_tenant)

    assert output.strip() == "Removed 2 cached answers."
    cache_keys = {key for key in await remaining_keys(redis) if key.startswith("cache:")}
    assert len(cache_keys) == 1
    assert cache_keys.pop().startswith(f"cache:{kept_tenant_id}:chat-fast:")
    # The cleared tenant gets a fresh answer from the provider again.
    async with gateway_client(settings, api_key=cleared_key) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
    assert response.headers["X-Gateway-Cache"] == "miss"
    assert groq.call_count == 4


async def test_clear_cache_of_one_alias_keeps_the_other_aliases(
    database_url: str, redis: Redis
) -> None:
    tenant, tenant_id, _ = await new_tenant(database_url)
    _, other_tenant_id, _ = await new_tenant(database_url)
    cleared = [entry_key(tenant_id, "chat", "Hi"), entry_key(tenant_id, "chat", "Hello")]
    # `chat:x` starts like `chat:` but is another alias; `chat-fast` is unrelated.
    kept = {
        entry_key(tenant_id, "chat:x"),
        entry_key(tenant_id, "chat-fast"),
        entry_key(other_tenant_id, "chat"),
    }
    await add_entries(redis, *cleared, *kept)

    output = await run_admin(database_url, "clear-cache", "--tenant", tenant, "--alias", "chat")

    assert output.strip() == "Removed 2 cached answers."
    assert await remaining_keys(redis) == kept


# "*", "?" and "[" have a meaning in a Redis SCAN pattern: they must match themselves.
@pytest.mark.parametrize("alias", ["chat:x", "chat[1]", "chat*"])
async def test_clear_cache_of_an_alias_with_special_characters(
    database_url: str, redis: Redis, alias: str
) -> None:
    tenant, tenant_id, _ = await new_tenant(database_url)
    await add_entries(redis, entry_key(tenant_id, alias), entry_key(tenant_id, "chat"))

    output = await run_admin(database_url, "clear-cache", "--tenant", tenant, "--alias", alias)

    assert output.strip() == "Removed 1 cached answer."
    assert await remaining_keys(redis) == {entry_key(tenant_id, "chat")}


async def test_clear_all_removes_the_answers_of_every_tenant(
    database_url: str, redis: Redis
) -> None:
    _, first_id, _ = await new_tenant(database_url)
    _, second_id, _ = await new_tenant(database_url)
    await add_entries(
        redis,
        entry_key(first_id, "chat-fast"),
        entry_key(first_id, "chat:x"),
        entry_key(second_id, "chat-smart"),
    )

    output = await run_admin(database_url, "clear-cache", "--all")

    assert output.strip() == "Removed 3 cached answers."
    assert await remaining_keys(redis) == set()


async def test_clear_cache_never_touches_the_routing_and_quota_state(
    database_url: str, redis: Redis
) -> None:
    tenant, tenant_id, _ = await new_tenant(database_url)
    await add_entries(redis, entry_key(tenant_id, "chat-fast"))
    other_keys = {
        f"cooldown:groq:{GROQ_MODEL}",
        f"rpd:groq:{GROQ_MODEL}:2026-10-23",
        f"tenant_rpm:{tenant_id}",
        f"cache-stats:{tenant_id}",
        f"cache:{tenant_id}:chat-fast:not-a-hash",
    }
    for key in other_keys:
        await redis.set(key, "1")

    await run_admin(database_url, "clear-cache", "--tenant", tenant)
    await run_admin(database_url, "clear-cache", "--all")

    assert await remaining_keys(redis) == other_keys


async def test_clear_cache_with_nothing_cached_removes_nothing(
    database_url: str, redis: Redis
) -> None:
    tenant, _, _ = await new_tenant(database_url)

    output = await run_admin(database_url, "clear-cache", "--tenant", tenant)

    assert output.strip() == "Removed 0 cached answers."


async def test_clear_cache_of_an_unknown_tenant_fails(database_url: str, redis: Redis) -> None:
    run = await run_admin_command(database_url, "clear-cache", "--tenant", "no-such-tenant")

    assert run.exit_code == 1
    assert "unknown tenant 'no-such-tenant'" in run.stderr


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ((), "one of the arguments --tenant --all is required"),
        (("--tenant", "acme", "--all"), "not allowed with argument"),
        (("--all", "--alias", "chat"), "--alias needs --tenant"),
        (("--alias", "chat"), "one of the arguments --tenant --all is required"),
    ],
    ids=["nothing", "tenant-and-all", "alias-with-all", "alias-alone"],
)
async def test_clear_cache_needs_exactly_one_of_tenant_or_all(
    database_url: str, redis: Redis, args: tuple[str, ...], error: str
) -> None:
    await add_entries(redis, entry_key(1, "chat-fast"))

    run = await run_admin_command(database_url, "clear-cache", *args)

    assert run.exit_code == 2
    assert error in run.stderr
    assert await remaining_keys(redis) == {entry_key(1, "chat-fast")}
