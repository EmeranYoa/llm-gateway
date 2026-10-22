"""Tests for the health endpoint."""

from collections.abc import Callable

from httpx import AsyncClient

from app.config import Settings
from tests.conftest import MINIMAL_CONFIG, gateway_client


async def test_health_reports_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_is_public_and_reveals_only_the_gateway_status(
    write_config: Callable[[str], Settings],
) -> None:
    async with gateway_client(write_config(MINIMAL_CONFIG), api_key=None) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": "up"}
