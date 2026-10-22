"""Tests for the token usage of streamed answers: quotas stay accurate with streaming."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.config import Settings
from tests.conftest import ClientFactory, FetchUsageRows, gateway_client
from tests.test_quotas import BIG_REQUEST, quota_config
from tests.test_streaming import STREAM_REQUEST, failing_stream, read_stream
from tests.test_tenant_quotas import tenant_config
from tests.upstream import GROQ_KEY, GROQ_URL, chunk, sse, stream_response

WriteConfig = Callable[[str], Settings]


@pytest.fixture(autouse=True)
def groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)


def usage_chunk(prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
    """The last chunk of a stream asked with `include_usage`: no choices, only the usage."""
    return {
        **chunk(),
        "choices": [],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def stream_with_usage(prompt_tokens: int, completion_tokens: int) -> httpx.Response:
    return stream_response(
        chunk(role="assistant", content=""),
        chunk("Hello"),
        usage_chunk(prompt_tokens, completion_tokens),
        "[DONE]",
    )


def streamed(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "stream": True}


def sent_body(route: respx.Route, call: int = 0) -> dict[str, Any]:
    """The JSON body the gateway sent upstream in call number `call`."""
    body: dict[str, Any] = json.loads(route.calls[call].request.content)
    return body


async def test_usage_is_asked_upstream_and_hidden_from_the_client(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=lambda _: stream_with_usage(5, 2))

    response, payloads = await read_stream(chat_client, STREAM_REQUEST)

    assert response.status_code == 200
    # The gateway asks for the usage it needs to keep the quotas accurate (ADR 0005)...
    assert sent_body(groq)["stream_options"] == {"include_usage": True}
    # ...but the client did not ask for it: it gets the stream it would get without it.
    assert payloads[-1] == "[DONE]"
    chunks = [json.loads(payload) for payload in payloads[:-1]]
    assert all("usage" not in c for c in chunks)
    assert all(c["choices"] for c in chunks)
    [row] = await usage_rows()
    assert (row["prompt_tokens"], row["completion_tokens"]) == (5, 2)


async def test_usage_asked_by_the_client_passes_through(
    chat_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=lambda _: stream_with_usage(5, 2))
    body = {**STREAM_REQUEST, "stream_options": {"include_usage": True}}

    _, payloads = await read_stream(chat_client, body)

    assert sent_body(groq)["stream_options"] == {"include_usage": True}
    last_chunk = json.loads(payloads[-2])
    assert last_chunk["usage"] == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    assert last_chunk["choices"] == []


async def test_other_stream_options_of_the_client_are_kept(
    chat_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=lambda _: stream_with_usage(5, 2))
    body = {**STREAM_REQUEST, "stream_options": {"include_usage": False, "other": 1}}

    _, payloads = await read_stream(chat_client, body)

    assert sent_body(groq)["stream_options"] == {"include_usage": True, "other": 1}
    assert all("usage" not in json.loads(payload) for payload in payloads[:-1])


async def test_usage_sent_with_the_last_content_is_hidden_from_the_client(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    # Some providers (Groq) send the usage inside the last chunk with choices.
    last = {**chunk("lo"), "usage": usage_chunk(5, 2)["usage"]}
    respx_mock.post(GROQ_URL).mock(return_value=stream_response(chunk("Hel"), last, "[DONE]"))

    _, payloads = await read_stream(chat_client, STREAM_REQUEST)

    chunks = [json.loads(payload) for payload in payloads[:-1]]
    assert "".join(c["choices"][0]["delta"]["content"] for c in chunks) == "Hello"
    assert all("usage" not in c for c in chunks)
    [row] = await usage_rows()
    assert (row["prompt_tokens"], row["completion_tokens"]) == (5, 2)


async def test_provider_tpm_is_corrected_with_the_usage_of_the_stream(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=lambda _: stream_with_usage(80, 20))

    async with make_client(quota_config("tpm: 1000")) as client:
        await read_stream(client, streamed(BIG_REQUEST))  # 611 reserved, 100 used
        second, _ = await read_stream(client, streamed(BIG_REQUEST))  # 100 + 611 fits

    assert second.status_code == 200
    assert groq.call_count == 2


@pytest.mark.parametrize(
    ("answer_chars", "second_status"),
    # 40 characters are about 10 tokens, so the second request fits; 1600 are
    # about 400 tokens, so with the prompt it no longer fits in the 1000 TPM.
    [(40, 200), (1600, 503)],
)
async def test_stream_without_usage_is_estimated_from_its_characters(
    make_client: ClientFactory, respx_mock: respx.MockRouter, answer_chars: int, second_status: int
) -> None:
    respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: stream_response(chunk("x" * answer_chars), "[DONE]")
    )

    async with make_client(quota_config("tpm: 1000")) as client:
        await read_stream(client, streamed(BIG_REQUEST))  # 611 reserved
        second, _ = await read_stream(client, streamed(BIG_REQUEST))

    assert second.status_code == second_status


async def test_tenant_budget_is_corrected_with_the_usage_of_the_stream(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=lambda _: stream_with_usage(5, 2))
    request = streamed({**STREAM_REQUEST, "max_tokens": 600})  # 602 reserved, 7 used

    async with gateway_client(write_config(tenant_config("tokens_per_day: 1000"))) as client:
        statuses = [(await read_stream(client, request))[0].status_code for _ in range(3)]

    assert statuses == [200, 200, 200]


async def test_tenant_budget_keeps_the_estimate_of_an_interrupted_stream(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    # The provider may have generated every reserved token before the stream broke.
    respx_mock.post(GROQ_URL).mock(
        side_effect=[
            failing_stream(sse(chunk("Hel")), httpx.ReadError("connection reset")),
            stream_with_usage(5, 2),
        ]
    )
    request = streamed({**STREAM_REQUEST, "max_tokens": 600})

    async with gateway_client(write_config(tenant_config("tokens_per_day: 1000"))) as client:
        _, payloads = await read_stream(client, request)
        next_one, _ = await read_stream(client, request)

    assert "stream_interrupted" in payloads[-1]
    assert next_one.status_code == 429


async def test_tenant_rpm_counts_streams(
    write_config: WriteConfig, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=lambda _: stream_with_usage(5, 2))

    async with gateway_client(write_config(tenant_config("rpm: 1"))) as client:
        first, _ = await read_stream(client, STREAM_REQUEST)
        second, _ = await read_stream(client, STREAM_REQUEST)

    assert [first.status_code, second.status_code] == [200, 429]
