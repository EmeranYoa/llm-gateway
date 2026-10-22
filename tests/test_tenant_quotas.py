"""Tests for tenant quotas: each tenant has its own requests-per-minute limit."""

import asyncio
from collections.abc import Callable
from uuid import uuid4

import openai
import pytest
import respx

from app.config import Settings
from tests.conftest import gateway_client, new_api_key, run_admin
from tests.upstream import CHAT_CONFIG, CHAT_REQUEST, GROQ_KEY, GROQ_URL, completion_body

WriteConfig = Callable[[str], Settings]


def tenant_config(default_limits: str) -> str:
    """The chat config (`chat-fast` routed to Groq) with the given tenant default limits."""
    return CHAT_CONFIG + f"\ntenants:\n  default_limits: {{ {default_limits} }}\n"


async def created_key(database_url: str, *options: str, tenant: str | None = None) -> str:
    """Create a key with the admin CLI, for `tenant` or a new tenant, and return it."""
    tenant = tenant or f"tenant-{uuid4().hex[:8]}"
    output = await run_admin(database_url, "create-key", "--tenant", tenant, *options)
    [key] = [word for word in output.split() if word.startswith("gw_")]
    return key


@pytest.fixture(autouse=True)
def groq(respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> respx.Route:
    """A fake Groq that answers every chat completion."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    return respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))


async def test_tenant_over_its_rpm_gets_429_without_calling_a_provider(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    async with gateway_client(write_config(tenant_config("rpm: 1"))) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.status_code == 200
    assert second.status_code == 429
    error = second.json()["error"]
    assert error["code"] == "tenant_quota_exceeded"
    assert error["type"] == "rate_limit_error"
    assert "requests per minute" in error["message"]
    # The first request leaves the 60 s window in about 60 s.
    assert int(second.headers["Retry-After"]) in {59, 60}
    assert groq.call_count == 1


async def test_openai_sdk_raises_rate_limit_error_for_a_tenant_over_its_rpm(
    write_config: WriteConfig, database_url: str
) -> None:
    key = await new_api_key(database_url)
    messages: list[openai.types.chat.ChatCompletionMessageParam] = [
        {"role": "user", "content": "Hi"}
    ]

    async with gateway_client(write_config(tenant_config("rpm: 1")), api_key=key) as client:
        # No retries: the SDK would otherwise wait for Retry-After (about 60 s).
        sdk = openai.AsyncOpenAI(
            base_url="http://gateway/v1", api_key=key, http_client=client, max_retries=0
        )
        await sdk.chat.completions.create(model="chat-fast", messages=messages)
        with pytest.raises(openai.RateLimitError) as error:
            await sdk.chat.completions.create(model="chat-fast", messages=messages)

    assert error.value.code == "tenant_quota_exceeded"


async def test_concurrent_requests_of_a_tenant_never_over_book_its_rpm(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    async with gateway_client(write_config(tenant_config("rpm: 5"))) as client:
        responses = await asyncio.gather(
            *(client.post("/v1/chat/completions", json=CHAT_REQUEST) for _ in range(20))
        )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200] * 5 + [429] * 15
    assert groq.call_count == 5


async def test_each_tenant_has_its_own_rpm(write_config: WriteConfig, database_url: str) -> None:
    other_tenant = {"Authorization": f"Bearer {await new_api_key(database_url)}"}

    async with gateway_client(write_config(tenant_config("rpm: 1"))) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        other = await client.post("/v1/chat/completions", json=CHAT_REQUEST, headers=other_tenant)

    assert [first.status_code, second.status_code, other.status_code] == [200, 429, 200]


async def test_a_failed_request_still_counts_in_the_tenant_rpm(
    write_config: WriteConfig, groq: respx.Route
) -> None:
    groq.respond(500)

    async with gateway_client(write_config(tenant_config("rpm: 1"))) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.status_code == 503
    assert second.status_code == 429
    assert groq.call_count == 1


async def test_rpm_set_at_key_creation_overrides_the_default(
    write_config: WriteConfig, database_url: str
) -> None:
    key = await created_key(database_url, "--rpm", "1")

    # No default limit in the config: only the tenant's own limit applies.
    async with gateway_client(write_config(CHAT_CONFIG), api_key=key) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert [first.status_code, second.status_code] == [200, 429]


async def test_set_limits_overrides_the_default_rpm_of_a_tenant(
    write_config: WriteConfig, database_url: str
) -> None:
    tenant = f"tenant-{uuid4().hex[:8]}"
    key = await created_key(database_url, tenant=tenant)

    await run_admin(database_url, "set-limits", "--tenant", tenant, "--rpm", "2")

    async with gateway_client(write_config(tenant_config("rpm: 1")), api_key=key) as client:
        statuses = [
            (await client.post("/v1/chat/completions", json=CHAT_REQUEST)).status_code
            for _ in range(3)
        ]
    assert statuses == [200, 200, 429]
