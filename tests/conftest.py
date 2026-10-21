"""Shared test fixtures."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from textwrap import dedent

import pytest
from httpx import ASGITransport, AsyncClient

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


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[[str], Settings]:
    """Write a gateway.yaml file and return settings that point to it."""

    def _write(config_yaml: str) -> Settings:
        path = tmp_path / "gateway.yaml"
        path.write_text(dedent(config_yaml), encoding="utf-8")
        return Settings(gateway_config_path=path)

    return _write


@pytest.fixture
def make_client(write_config: Callable[[str], Settings]) -> ClientFactory:
    """Build an in-process HTTP client for a gateway started with the given config."""

    @asynccontextmanager
    async def _make(config_yaml: str) -> AsyncIterator[AsyncClient]:
        app = create_app(write_config(config_yaml))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://gateway") as http_client:
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
