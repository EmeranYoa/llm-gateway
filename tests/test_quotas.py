"""Tests for quota tracking: requests per minute, tokens per minute and requests per day."""

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from tests.conftest import ClientFactory, FetchUsageRows
from tests.upstream import (
    CHAT_REQUEST,
    GEMINI_KEY,
    GEMINI_URL,
    GROQ_KEY,
    GROQ_URL,
    completion_body,
)


def quota_config(limits: str, *, gateway: str = "", daily_reset: str = "{}") -> str:
    """A config routing `chat-fast` to Groq only, with the given model limits."""
    return f"""
gateway: {{ {gateway} }}
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    daily_reset: {daily_reset}
    models:
      llama-3.3-70b-versatile: {{ {limits} }}
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile ]
"""


@pytest.fixture(autouse=True)
def groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)


async def test_full_rpm_quota_skips_the_target_until_the_window_frees_up(
    make_client: ClientFactory, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))

    async with make_client(quota_config("rpm: 1")) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.status_code == 200
    assert second.status_code == 503
    assert groq.call_count == 1
    # The first request leaves the 60 s window in about 60 s.
    assert int(second.headers["Retry-After"]) in {59, 60}
    rows = await usage_rows()
    assert [row["outcome"] for row in rows] == ["success", "skipped_quota"]


async def test_concurrent_requests_never_over_book_the_quota(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))

    async with make_client(quota_config("rpm: 5")) as client:
        responses = await asyncio.gather(
            *(client.post("/v1/chat/completions", json=CHAT_REQUEST) for _ in range(20))
        )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200] * 5 + [503] * 15
    assert groq.call_count == 5


TOOLS = [{"type": "function", "function": {"name": "get_weather"}}]


@pytest.mark.parametrize(
    ("extra_fields", "expected_estimate"),
    [
        # "user" + 40 x "x" = 44 characters -> 11 prompt tokens.
        ({}, 11 + 100),  # no max_tokens: default_completion_tokens
        ({"max_tokens": 50}, 11 + 50),
        ({"max_completion_tokens": 70}, 11 + 70),
        # Tools count too: "function" + "get_weather" = 19 more characters -> 16 prompt tokens.
        ({"tools": TOOLS, "max_tokens": 50}, 16 + 50),
        ({"max_tokens": 5000}, 1000),  # capped at the target TPM
    ],
    ids=["default", "max-tokens", "max-completion-tokens", "tools", "capped"],
)
async def test_token_estimate_is_logged_for_each_call(
    make_client: ClientFactory,
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
    extra_fields: dict[str, object],
    expected_estimate: int,
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    request = {**CHAT_REQUEST, "messages": [{"role": "user", "content": "x" * 40}]}

    config = quota_config("tpm: 1000", gateway="default_completion_tokens: 100")
    async with make_client(config) as client:
        await client.post("/v1/chat/completions", json={**request, **extra_fields})

    [row] = await usage_rows()
    assert row["estimated_tokens"] == expected_estimate


# 44 characters -> 11 prompt tokens, + 600 completion tokens = 611 tokens reserved per call.
BIG_REQUEST = {
    **CHAT_REQUEST,
    "messages": [{"role": "user", "content": "x" * 40}],
    "max_tokens": 600,
}


def usage_body(total_tokens: int | None) -> dict[str, object]:
    """A completion body that reports `total_tokens` of real usage, or no usage at all."""
    body = completion_body("llama-3.3-70b-versatile")
    if total_tokens is None:
        del body["usage"]
    else:
        body["usage"] = {
            "prompt_tokens": total_tokens - 20,
            "completion_tokens": 20,
            "total_tokens": total_tokens,
        }
    return body


async def test_full_tpm_quota_skips_the_target(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(json=usage_body(None))

    async with make_client(quota_config("tpm: 1000")) as client:
        first = await client.post("/v1/chat/completions", json=BIG_REQUEST)
        second = await client.post("/v1/chat/completions", json=BIG_REQUEST)

    assert first.status_code == 200
    assert second.status_code == 503
    assert "tpm quota full" in second.json()["error"]["message"]
    assert groq.call_count == 1


async def test_reservation_is_corrected_with_the_real_usage(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(json=usage_body(100))

    async with make_client(quota_config("tpm: 1000")) as client:
        await client.post("/v1/chat/completions", json=BIG_REQUEST)  # 611 reserved, 100 used
        second = await client.post("/v1/chat/completions", json=BIG_REQUEST)  # 100 + 611 fits

    assert second.status_code == 200
    assert groq.call_count == 2


async def test_tokens_are_released_when_the_call_fails(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=usage_body(None))]
    )

    async with make_client(quota_config("tpm: 1000")) as client:
        first = await client.post("/v1/chat/completions", json=BIG_REQUEST)
        second = await client.post("/v1/chat/completions", json=BIG_REQUEST)

    assert first.status_code == 503
    assert second.status_code == 200


async def test_tokens_are_kept_when_the_call_times_out(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    # The provider may have generated tokens before the timeout.
    groq = respx_mock.post(GROQ_URL).mock(side_effect=httpx.ReadTimeout("read timed out"))

    async with make_client(quota_config("tpm: 1000")) as client:
        await client.post("/v1/chat/completions", json=BIG_REQUEST)
        second = await client.post("/v1/chat/completions", json=BIG_REQUEST)

    assert "tpm quota full" in second.json()["error"]["message"]
    assert groq.call_count == 1


async def test_request_count_is_kept_when_the_call_fails(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    # The provider may have counted the request even though it failed.
    groq = respx_mock.post(GROQ_URL).respond(500)

    async with make_client(quota_config("rpm: 1")) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert "rpm quota full" in second.json()["error"]["message"]
    assert groq.call_count == 1


async def test_prompt_larger_than_tpm_is_never_sent_to_the_target(
    make_client: ClientFactory, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(json=usage_body(None))
    # "user" + 100 characters -> 26 prompt tokens, above the TPM of 10 even in an empty window.
    request = {**CHAT_REQUEST, "messages": [{"role": "user", "content": "x" * 100}]}

    async with make_client(quota_config("tpm: 10")) as client:
        response = await client.post("/v1/chat/completions", json=request)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "context_length_exceeded"
    assert "Retry-After" not in response.headers
    assert not groq.called
    [row] = await usage_rows()
    assert row["outcome"] == "context_too_large"
    assert row["latency_ms"] is None


async def test_rpd_quota_resets_at_the_daily_reset_time_of_the_provider(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).respond(json=usage_body(None))
    # A reset 2 seconds from now, Los Angeles time. Ignoring the timezone would put it
    # hours away from now.
    reset_at = dt.datetime.now(ZoneInfo("America/Los_Angeles")) + dt.timedelta(seconds=2)
    daily_reset = f'{{ time: "{reset_at:%H:%M:%S}", timezone: "America/Los_Angeles" }}'

    async with make_client(quota_config("rpd: 1", daily_reset=daily_reset)) as client:
        first = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        second = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await asyncio.sleep(2.2)
        third = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert first.status_code == 200
    assert second.status_code == 503
    assert "rpd quota full" in second.json()["error"]["message"]
    assert int(second.headers["Retry-After"]) in {1, 2, 3}
    assert third.status_code == 200
    assert groq.call_count == 2


async def test_target_too_small_for_the_prompt_does_not_count_for_retry_after(
    make_client: ClientFactory, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    respx_mock.post(GEMINI_URL).respond(429, headers={"Retry-After": "10"})
    config = """
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      llama-3.3-70b-versatile: { tpm: 10 }
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: GEMINI_API_KEY
    models:
      gemini-2.5-flash: {}
routes:
  chat-fast: [ groq/llama-3.3-70b-versatile, gemini/gemini-2.5-flash ]
"""
    request = {**CHAT_REQUEST, "messages": [{"role": "user", "content": "x" * 100}]}

    async with make_client(config) as client:
        response = await client.post("/v1/chat/completions", json=request)

    # Groq can never take this prompt; only Gemini's 10 s matter.
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "10"
