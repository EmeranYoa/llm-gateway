"""Tests for the gateway's connections to its providers: the connection pool limits
of the shared HTTP client, and the sniffio dependency httpcore needs."""

import importlib
import tomllib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from tests.conftest import MINIMAL_CONFIG

WriteConfig = Callable[[str], Settings]

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"
LIMIT_VARIABLES = ["UPSTREAM_MAX_CONNECTIONS", "UPSTREAM_MAX_KEEPALIVE"]


def pool_limits(client: httpx.AsyncClient) -> tuple[int, int, float | None]:
    """Max connections, max keep-alive connections and keep-alive expiry of the client's pool.

    httpx has no public accessor for the limits a client was built with, so this reads
    the httpcore pool behind the default transport.
    """
    pool = client._transport._pool  # type: ignore[attr-defined]
    return pool._max_connections, pool._max_keepalive_connections, pool._keepalive_expiry


def test_upstream_limits_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in LIMIT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    settings = Settings()

    assert settings.upstream_max_connections == 200
    assert settings.upstream_max_keepalive == 100


def test_upstream_limits_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPSTREAM_MAX_CONNECTIONS", "50")
    monkeypatch.setenv("UPSTREAM_MAX_KEEPALIVE", "10")

    settings = Settings()

    assert settings.upstream_max_connections == 50
    assert settings.upstream_max_keepalive == 10


def test_empty_upstream_limits_keep_their_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # A `.env` copied from `.env.example` sets them to an empty value.
    for variable in LIMIT_VARIABLES:
        monkeypatch.setenv(variable, "")

    settings = Settings()

    assert settings.upstream_max_connections == 200
    assert settings.upstream_max_keepalive == 100


@pytest.mark.parametrize("variable", LIMIT_VARIABLES)
@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_upstream_limits_must_be_positive_integers(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError):
        Settings()


async def test_shared_http_client_uses_the_upstream_limits(write_config: WriteConfig) -> None:
    settings = write_config(MINIMAL_CONFIG).model_copy(
        update={"upstream_max_connections": 50, "upstream_max_keepalive": 10}
    )

    app = create_app(settings)
    try:
        # The keep-alive expiry stays at the httpx default (5 s) on purpose.
        assert pool_limits(app.state.http_client) == (50, 10, 5.0)
    finally:
        await app.state.http_client.aclose()


def test_sniffio_is_importable() -> None:
    # httpcore imports sniffio on every connection pool operation. Without it, the
    # failed import searches the disk again on each request.
    importlib.import_module("sniffio")


def test_sniffio_is_a_runtime_dependency() -> None:
    # The dev tools (openai) also install sniffio, so being importable in the test
    # environment does not prove the production image has it.
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("sniffio") for dependency in dependencies)
