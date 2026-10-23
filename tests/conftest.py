"""Shared test fixtures."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any
from uuid import uuid4

import pytest
import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.main import create_app
from app.storage.tenants import create_api_key
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
#   docker run -d --rm --name gateway-test-redis -p 56379:6379 redis:8.8
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


# Pass as `api_key` to `gateway_client` to get a client with a fresh, valid key.
NEW_KEY = "create a new key"


@asynccontextmanager
async def gateway_client(
    settings: Settings, api_key: str | None = NEW_KEY
) -> AsyncIterator[AsyncClient]:
    """Start a gateway with `settings` (startup and shutdown included) and yield a client for it.

    By default the client sends a valid API key of a new tenant. Pass another
    `api_key` to send that one, or None to send no key at all.
    """
    if api_key == NEW_KEY:
        api_key = await new_api_key(settings.database_url)
    headers = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://gateway", headers=headers) as http_client,
    ):
        yield http_client


async def new_api_key(database_url: str) -> str:
    """Create a tenant with a unique name and return a valid API key for it."""
    engine = create_async_engine(database_url)
    try:
        new_key = await create_api_key(engine, f"tenant-{uuid4().hex[:8]}")
    finally:
        await engine.dispose()
    return new_key.key


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


class DatabaseProxy:
    """A TCP proxy in front of the test PostgreSQL, to simulate an outage mid-test.

    The gateway connects through `url`. Until an outage starts, bytes flow both ways.
    `hang()` makes PostgreSQL look stuck: connections stay open but nothing comes back.
    `stop()` makes it look down: connections are closed and new ones refused.
    Stopping the shared test container instead would break other tests.
    """

    def __init__(self, database_url: str) -> None:
        self._target = make_url(database_url)
        self._server: asyncio.Server | None = None
        self._hanging = False
        self._writers: list[asyncio.StreamWriter] = []
        self._pumps: set[asyncio.Task[None]] = set()
        self.url = ""

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = self._target.set(host="127.0.0.1", port=port).render_as_string(
            hide_password=False
        )

    def hang(self) -> None:
        """From now on, drop every byte: queries and connection attempts never get an answer."""
        self._hanging = True

    async def stop(self) -> None:
        """Close every connection and stop listening: new connections are refused."""
        if self._server is not None:
            self._server.close()
            self._server = None
        for pump in self._pumps:
            pump.cancel()
        await asyncio.gather(*self._pumps, return_exceptions=True)
        for writer in self._writers:
            writer.close()
        self._writers.clear()

    async def _accept(
        self, client_reader: asyncio.StreamReader, client: asyncio.StreamWriter
    ) -> None:
        self._writers.append(client)
        if self._hanging:
            return
        server_reader, server = await asyncio.open_connection(self._target.host, self._target.port)
        self._writers.append(server)
        for source, destination in ((client_reader, server), (server_reader, client)):
            pump = asyncio.create_task(self._pump(source, destination))
            self._pumps.add(pump)
            pump.add_done_callback(self._pumps.discard)

    async def _pump(self, source: asyncio.StreamReader, destination: asyncio.StreamWriter) -> None:
        try:
            while data := await source.read(65536):
                if not self._hanging:
                    destination.write(data)
                    await destination.drain()
        except ConnectionError:
            pass
        finally:
            destination.close()


@pytest.fixture
async def database_proxy(database_url: str) -> AsyncIterator[DatabaseProxy]:
    """A proxy to the test PostgreSQL that a test can switch to "stuck" or "down"."""
    proxy = DatabaseProxy(database_url)
    await proxy.start()
    yield proxy
    await proxy.stop()


# --- Admin CLI, run as an operator would: a real subprocess ---


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


@asynccontextmanager
async def live_gateway(
    settings: Settings, api_key: str | None = NEW_KEY
) -> AsyncIterator[AsyncClient]:
    """Serve a gateway with uvicorn on a free local port and yield a client for it.

    Unlike `gateway_client`, a real HTTP server sends a stream event by event, so
    tests can see when each event reaches the client, or close the connection early.
    """
    if api_key == NEW_KEY:
        api_key = await new_api_key(settings.database_url)
    headers = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=0, log_level="warning")
    )
    serving = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 (uvicorn only exposes a `started` flag)
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers) as client:
            yield client
    finally:
        server.should_exit = True
        await serving
