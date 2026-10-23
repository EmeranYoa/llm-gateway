"""Tests for admin keys and the admin API: a separate application, closed to the public."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.admin_api.main import create_admin_app
from app.config import Settings
from app.storage.admin_keys import create_admin_key
from tests.conftest import (
    MINIMAL_CONFIG,
    gateway_client,
    new_api_key,
    run_admin,
    run_admin_command,
)
from tests.upstream import CHAT_REQUEST

WriteConfig = Callable[[str], Settings]


@asynccontextmanager
async def admin_client(settings: Settings, api_key: str | None) -> AsyncIterator[AsyncClient]:
    """Start the admin API with `settings` and yield a client that sends `api_key`."""
    headers = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}
    app = create_admin_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://admin-api", headers=headers
        ) as client,
    ):
        yield client


async def new_admin_key(database_url: str, name: str | None = None) -> str:
    """Create an admin key and return it."""
    engine = create_async_engine(database_url)
    try:
        new_key = await create_admin_key(engine, name or f"operator-{uuid4().hex[:8]}")
    finally:
        await engine.dispose()
    return new_key.key


@pytest.fixture
def settings(write_config: WriteConfig) -> Settings:
    return write_config(MINIMAL_CONFIG)


async def test_create_admin_key_prints_a_key_once(settings: Settings, database_url: str) -> None:
    name = f"alice-{uuid4().hex[:6]}"

    output = await run_admin(database_url, "create-admin-key", "--name", name)
    [key] = [word for word in output.split() if word.startswith("gwa_")]
    listed = await run_admin(database_url, "list-admin-keys")

    assert len(key) > 40
    assert name in listed
    assert key[:10] in listed  # a short prefix, to recognise the key
    assert key not in listed  # never the full key
    async with admin_client(settings, key) as client:
        response = await client.get("/admin/v1/me")
    assert response.status_code == 200
    assert response.json() == {"name": name}


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer gwa_not-a-real-key", "gwa_without-bearer", "Basic abc"],
    ids=["missing", "unknown", "no-scheme", "other-scheme"],
)
async def test_admin_api_refuses_requests_without_a_valid_admin_key(
    settings: Settings, authorization: str | None
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    async with admin_client(settings, None) as client:
        response = await client.get("/admin/v1/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


async def test_tenant_key_does_not_open_the_admin_api(
    settings: Settings, database_url: str
) -> None:
    tenant_key = await new_api_key(database_url)

    async with admin_client(settings, tenant_key) as client:
        response = await client.get("/admin/v1/me")

    assert response.status_code == 401


async def test_admin_key_does_not_open_the_gateway(settings: Settings, database_url: str) -> None:
    admin_key = await new_admin_key(database_url)

    async with gateway_client(settings, api_key=admin_key) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


async def test_revoked_admin_key_is_refused(settings: Settings, database_url: str) -> None:
    name = f"bob-{uuid4().hex[:6]}"
    output = await run_admin(database_url, "create-admin-key", "--name", name)
    [key] = [word for word in output.split() if word.startswith("gwa_")]
    [key_id] = [
        line.split()[0]
        for line in (await run_admin(database_url, "list-admin-keys")).splitlines()
        if name in line
    ]

    revoked = await run_admin(database_url, "revoke-admin-key", key_id)
    again = await run_admin_command(database_url, "revoke-admin-key", key_id)
    unknown = await run_admin_command(database_url, "revoke-admin-key", "999999")
    listed = await run_admin(database_url, "list-admin-keys")

    assert "revoked" in revoked.lower()
    assert again.exit_code == 1 and "already revoked" in again.stderr
    assert unknown.exit_code == 1
    assert any(name in line and "revoked" in line for line in listed.splitlines())
    async with admin_client(settings, key) as client:
        response = await client.get("/admin/v1/me")
    assert response.status_code == 401


async def test_admin_api_health_needs_no_key(settings: Settings) -> None:
    async with admin_client(settings, None) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_api_is_never_published_by_docker_compose() -> None:
    # Defence in depth: even a leaked admin key is useless from outside the
    # internal network, because nothing outside can reach the admin API.
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    admin_api = compose["services"]["admin-api"]

    assert "ports" not in admin_api
    assert "8001" in " ".join(admin_api["command"])
    assert "app.admin_api.main:create_admin_app" in " ".join(admin_api["command"])
