"""Shared test fixtures."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.main import create_app
from tests.upstream import CHAT_CONFIG, FAILOVER_CONFIG, GEMINI_KEY, GROQ_KEY

MINIMAL_CONFIG = """
providers:
  ollama:
    base_url: http://ollama.test/v1
    api_key_env: null
    models:
      "llama3.2:3b": {}
routes:
  chat-fast: [ ollama/llama3.2:3b ]
"""

ClientFactory = Callable[[str], AbstractAsyncContextManager[AsyncClient]]
FetchUsageRows = Callable[[], Awaitable[list[dict[str, Any]]]]

# Tests need a real PostgreSQL. Locally, start a throwaway one with:
#   docker run -d --rm --name gateway-test-pg -e POSTGRES_PASSWORD=test \
#     -e POSTGRES_DB=gateway_test -p 55432:5432 postgres:17-alpine
DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://postgres:test@localhost:55432/gateway_test"


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of the test database, migrated from scratch once per test session.

    Downgrading to `base` first means every session also checks that the
    migrations apply cleanly to an empty database.
    """
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    alembic_config = AlembicConfig(Path(__file__).parent.parent / "alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", url)
    alembic_config.attributes["configure_logging"] = False
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    return url


# Tests need a real Redis, because the routing state relies on Lua scripts. Locally:
#   docker run -d --rm --name gateway-test-redis -p 56379:6379 redis:7.4-alpine
DEFAULT_TEST_REDIS_URL = "redis://localhost:56379/0"


@pytest.fixture
async def redis_url() -> str:
    """URL of the test Redis, emptied before each test so no routing state leaks between tests."""
    url = os.environ.get("TEST_REDIS_URL", DEFAULT_TEST_REDIS_URL)
    redis = Redis.from_url(url)
    await redis.flushdb()
    await redis.aclose()
    return url


@pytest.fixture
async def usage_rows(database_url: str) -> AsyncIterator[FetchUsageRows]:
    """Empty the `usage_log` table, then return a function that reads its rows in insert order."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE usage_log"))

    async def _fetch() -> list[dict[str, Any]]:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT * FROM usage_log ORDER BY id"))
            return [dict(row) for row in result.mappings()]

    yield _fetch
    await engine.dispose()


@pytest.fixture
def write_config(tmp_path: Path, database_url: str, redis_url: str) -> Callable[[str], Settings]:
    """Write a gateway.yaml file and return settings that point to it and to the test stores."""

    def _write(config_yaml: str) -> Settings:
        path = tmp_path / "gateway.yaml"
        path.write_text(dedent(config_yaml), encoding="utf-8")
        return Settings(gateway_config_path=path, database_url=database_url, redis_url=redis_url)

    return _write


@asynccontextmanager
async def gateway_client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """Start a gateway with `settings` (startup and shutdown included) and yield a client for it."""
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://gateway") as http_client,
    ):
        yield http_client


@pytest.fixture
def make_client(write_config: Callable[[str], Settings]) -> ClientFactory:
    """Build an in-process HTTP client for a gateway started with the given config."""

    @asynccontextmanager
    async def _make(config_yaml: str) -> AsyncIterator[AsyncClient]:
        async with gateway_client(write_config(config_yaml)) as http_client:
            yield http_client

    return _make


@pytest.fixture
async def client(make_client: ClientFactory) -> AsyncIterator[AsyncClient]:
    """HTTP client for a gateway started with a minimal valid config."""
    async with make_client(MINIMAL_CONFIG) as http_client:
        yield http_client


@pytest.fixture
async def chat_client(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """HTTP client for a gateway routing `chat-fast` to a fake Groq provider.

    `chat-offline` points to Gemini, which is disabled because its key is not set.
    """
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    async with make_client(CHAT_CONFIG) as http_client:
        yield http_client


@pytest.fixture
async def failover_client(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """HTTP client for a gateway routing `chat-fast` to Groq, then Gemini, then Ollama."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    async with make_client(FAILOVER_CONFIG) as http_client:
        yield http_client


@pytest.fixture
async def silent_server() -> AsyncIterator[int]:
    """A TCP server that accepts connections but never answers, like a hung database.

    Yields its port.
    """
    connections: list[asyncio.StreamWriter] = []

    async def accept_and_stay_silent(_: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connections.append(writer)

    server = await asyncio.start_server(accept_and_stay_silent, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    for writer in connections:
        writer.close()
    server.close()
    await server.wait_closed()
