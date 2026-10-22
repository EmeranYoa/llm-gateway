"""Tests for streamed chat completions (`stream: true`, Server-Sent Events)."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import openai
import pytest
import respx
from httpx import AsyncClient

from app.config import Settings
from tests.conftest import ClientFactory, FetchUsageRows, live_gateway, new_api_key
from tests.upstream import (
    CHAT_CONFIG,
    CHAT_REQUEST,
    FAILOVER_CONFIG,
    GEMINI_KEY,
    GEMINI_URL,
    GROQ_KEY,
    GROQ_URL,
    OLLAMA_URL,
    chunk,
    completion_body,
    error_body,
    sse,
    stream_response,
)

STREAM_REQUEST = {**CHAT_REQUEST, "stream": True}


async def read_stream(
    client: AsyncClient, body: dict[str, Any]
) -> tuple[httpx.Response, list[str]]:
    """Send a streamed request and return the response and the `data:` payloads it carried."""
    async with client.stream("POST", "/v1/chat/completions", json=body) as response:
        payloads = [
            line.removeprefix("data: ")
            async for line in response.aiter_lines()
            if line.startswith("data: ")
        ]
    return response, payloads


async def test_stream_is_relayed_in_openai_format(
    chat_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(
        return_value=stream_response(
            ": keep-alive comment",
            chunk(role="assistant", content=""),
            chunk("Hel"),
            chunk("lo"),
            "[DONE]",
        )
    )

    response, payloads = await read_stream(chat_client, STREAM_REQUEST)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-Gateway-Provider"] == "groq"
    assert response.headers["X-Gateway-Model"] == "llama-3.3-70b-versatile"
    assert response.headers["X-Gateway-Fallbacks"] == "0"
    assert payloads[-1] == "[DONE]"
    chunks = [json.loads(payload) for payload in payloads[:-1]]
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "Hello"
    # Like normal responses, `model` is the real configured model; other fields are unchanged.
    assert {c["model"] for c in chunks} == {"llama-3.3-70b-versatile"}
    assert {c["id"] for c in chunks} == {"chatcmpl-123"}


async def test_reasoning_reaches_the_client_before_the_answer(
    write_config: Callable[[str], Settings],
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.route(host="127.0.0.1").pass_through()  # the client talks to the live gateway
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    client_got_reasoning = asyncio.Event()

    async def upstream_body() -> AsyncIterator[bytes]:
        yield sse(chunk(role="assistant", content=""), chunk(reasoning="Let me think."))
        # Like a reasoning model: the answer only comes after some thinking.
        await asyncio.wait_for(client_got_reasoning.wait(), timeout=5)
        yield sse(chunk("Hello"), "[DONE]")

    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=upstream_body()
        )
    )

    async with (
        live_gateway(write_config(CHAT_CONFIG)) as client,
        client.stream("POST", "/v1/chat/completions", json=STREAM_REQUEST) as response,
    ):
        lines = response.aiter_lines()
        # Reasoning is output for the client: it is sent at once, not held back.
        reasoning = await asyncio.wait_for(next_event_with(lines, "reasoning"), timeout=2)
        client_got_reasoning.set()
        answer = await asyncio.wait_for(next_event_with(lines, "Hello"), timeout=2)

    assert "Let me think." in reasoning
    assert "Hello" in answer


async def next_event_with(lines: AsyncIterator[str], text: str) -> str:
    """Read stream lines until a `data:` line that contains `text`."""
    async for line in lines:
        if line.startswith("data: ") and text in line:
            return line
    raise AssertionError(f"the stream ended without {text!r}")


GEMINI_STREAM = (chunk(role="assistant", content=""), chunk("From Gemini"), "[DONE]")


@pytest.mark.parametrize(
    "groq_answer",
    [
        httpx.Response(429),
        httpx.Response(503),
        httpx.ConnectError("connection refused"),
        # Some providers answer 200, then send an error as the first event.
        stream_response({"error": {"code": 429, "message": "rate-limited upstream"}}),
        stream_response({"error": {"code": 502, "message": "upstream failed"}}),
    ],
    ids=["http-429", "http-503", "network-error", "error-event-429", "error-event-502"],
)
async def test_stream_fails_over_before_the_first_content(
    failover_client: AsyncClient,
    respx_mock: respx.MockRouter,
    groq_answer: httpx.Response | Exception,
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=[groq_answer])
    respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))

    response, payloads = await read_stream(failover_client, STREAM_REQUEST)

    assert response.status_code == 200
    assert response.headers["X-Gateway-Provider"] == "gemini"
    assert response.headers["X-Gateway-Fallbacks"] == "1"
    assert payloads[-1] == "[DONE]"
    assert all("error" not in json.loads(payload) for payload in payloads[:-1])


async def test_stream_fails_over_when_the_first_content_comes_too_late(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    config = FAILOVER_CONFIG.replace(
        "llama-3.3-70b-versatile: {}", "llama-3.3-70b-versatile: { timeout: 0.3 }"
    )

    async def slow_body() -> AsyncIterator[bytes]:
        yield sse(chunk(role="assistant", content=""))
        await asyncio.sleep(2)  # the first content comes after the model timeout
        yield sse(chunk("Too late"), "[DONE]")

    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=slow_body()
        )
    )
    respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))

    async with make_client(config) as client:
        response, _ = await read_stream(client, STREAM_REQUEST)

    assert response.headers["X-Gateway-Provider"] == "gemini"


async def test_stream_that_no_target_can_serve_gets_a_json_error(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    for url in (GROQ_URL, GEMINI_URL, OLLAMA_URL):
        respx_mock.post(url).respond(503)

    response = await failover_client.post("/v1/chat/completions", json=STREAM_REQUEST)

    # Nothing was streamed yet, so the client gets the usual error, not a stream.
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "all_targets_failed"


async def test_stream_with_an_invalid_request_is_not_failed_over(
    failover_client: AsyncClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(400, json=error_body("'temperature' must be <= 2"))
    gemini = respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))

    response = await failover_client.post("/v1/chat/completions", json=STREAM_REQUEST)

    assert response.status_code == 400
    assert not gemini.called


async def test_half_open_trial_ends_at_the_first_content_of_a_stream(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)
    # Breaker: open after 3 failures, half-open after 0.5 s. Trial slot TTL: 2 s.
    config = "gateway: { breaker: { failures: 3, window: 60, open: 0.5 } }\n" + (
        FAILOVER_CONFIG.replace(
            "llama-3.3-70b-versatile: {}", "llama-3.3-70b-versatile: { timeout: 2 }"
        )
    )
    trial_committed = asyncio.Event()
    other_request_done = asyncio.Event()

    async def long_trial_stream() -> AsyncIterator[bytes]:
        yield sse(chunk("Trial answer"))
        # The gateway asks for more only after its commit point, so it is recorded now.
        trial_committed.set()
        await asyncio.wait_for(other_request_done.wait(), timeout=5)
        yield sse("[DONE]")

    groq_answers = [
        *(httpx.Response(500) for _ in range(3)),
        httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=long_trial_stream()
        ),
        httpx.Response(200, json=completion_body("llama-3.3-70b-versatile")),
    ]
    respx_mock.post(GROQ_URL).mock(side_effect=groq_answers)
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    async with make_client(config) as client:
        for _ in range(3):  # three failures: the breaker opens
            await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        await asyncio.sleep(0.6)  # half-open: the next call is the single trial
        trial = asyncio.create_task(read_stream(client, STREAM_REQUEST))
        await asyncio.wait_for(trial_committed.wait(), timeout=5)
        # The trial stream is still open, but it sent content: the breaker is closed,
        # so this request goes to Groq instead of being skipped by the breaker.
        other = await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        other_request_done.set()
        await trial

    assert other.headers["X-Gateway-Provider"] == "groq"


def stream_config(stream: str = "", *, deadline: float = 60) -> str:
    """Groq then Gemini, a breaker that opens after one failure, and stream settings."""
    return (
        f"gateway: {{ deadline: {deadline}, min_attempt_time: 0.1,"
        f" breaker: {{ failures: 1, window: 60, open: 30 }},"
        f" stream: {{ {stream} }} }}\n" + FAILOVER_CONFIG
    )


def paced_stream(*parts: tuple[float, bytes]) -> httpx.Response:
    """A streamed answer whose parts arrive after the given delays (in seconds)."""

    async def body() -> AsyncIterator[bytes]:
        for delay, part in parts:
            await asyncio.sleep(delay)
            yield part

    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())


def failing_stream(first: bytes, error: Exception) -> httpx.Response:
    """A streamed answer that sends `first`, then breaks with `error`."""

    async def body() -> AsyncIterator[bytes]:
        yield first
        raise error

    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())


@pytest.fixture
def stream_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)


@pytest.mark.parametrize(
    "broken_stream",
    [
        stream_response(chunk("Hel"), {"error": {"code": 502, "message": "upstream failed"}}),
        failing_stream(sse(chunk("Hel")), httpx.ReadError("connection reset")),
    ],
    ids=["error-event", "connection-lost"],
)
@pytest.mark.usefixtures("stream_keys")
async def test_stream_broken_after_the_first_content_ends_with_an_error_event(
    make_client: ClientFactory,
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
    broken_stream: httpx.Response,
) -> None:
    groq = respx_mock.post(GROQ_URL).mock(side_effect=[broken_stream])
    respx_mock.post(GEMINI_URL).respond(json=completion_body("gemini-2.5-flash"))

    async with make_client(stream_config()) as client:
        response, payloads = await read_stream(client, STREAM_REQUEST)
        # The breaker counted the interruption as a failure: Groq is now skipped.
        after = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 200
    assert json.loads(payloads[0])["choices"][0]["delta"]["content"] == "Hel"
    # A truncated answer is never passed off as complete: an error event, no [DONE].
    assert "[DONE]" not in payloads
    assert json.loads(payloads[-1])["error"]["code"] == "stream_interrupted"
    assert after.headers["X-Gateway-Provider"] == "gemini"
    assert groq.call_count == 1
    stream_rows = [row for row in await usage_rows() if row["provider"] == "groq"]
    assert stream_rows[0]["outcome"] == "interrupted"
    assert stream_rows[0]["status_code"] == 200
    # The stream had started: its time to first content is known.
    assert stream_rows[0]["first_token_ms"] is not None


@pytest.mark.parametrize(
    ("settings", "parts"),
    [
        # Silent for 1 s after the first content: above the 0.3 s idle timeout.
        ("idle_timeout: 0.3", [(0, sse(chunk("Hel"))), (1, sse(chunk("lo"), "[DONE]"))]),
        # Keeps talking, but for longer than the 0.5 s maximum duration.
        (
            "idle_timeout: 5, max_duration: 0.5",
            [(0, sse(chunk("a")))] + [(0.2, sse(chunk("b"))) for _ in range(6)],
        ),
    ],
    ids=["idle-timeout", "max-duration"],
)
@pytest.mark.usefixtures("stream_keys")
async def test_stream_timeouts_interrupt_a_committed_stream(
    make_client: ClientFactory,
    respx_mock: respx.MockRouter,
    settings: str,
    parts: list[tuple[float, bytes]],
) -> None:
    respx_mock.post(GROQ_URL).mock(side_effect=[paced_stream(*parts)])

    async with make_client(stream_config(settings)) as client:
        _, payloads = await read_stream(client, STREAM_REQUEST)

    assert "[DONE]" not in payloads
    assert json.loads(payloads[-1])["error"]["code"] == "stream_interrupted"


@pytest.mark.usefixtures("stream_keys")
async def test_request_deadline_does_not_cut_a_stream_that_keeps_going(
    make_client: ClientFactory, respx_mock: respx.MockRouter
) -> None:
    # 1.5 s of steady output, with a request deadline of 1 s.
    parts = [(0, sse(chunk("a")))] + [(0.3, sse(chunk("b"))) for _ in range(5)]
    respx_mock.post(GROQ_URL).mock(side_effect=[paced_stream(*parts, (0, sse("[DONE]")))])

    async with make_client(stream_config(deadline=1)) as client:
        _, payloads = await read_stream(client, STREAM_REQUEST)

    assert payloads[-1] == "[DONE]"


@pytest.mark.usefixtures("stream_keys")
async def test_sdk_raises_an_api_error_on_an_interrupted_stream(
    make_client: ClientFactory, respx_mock: respx.MockRouter, database_url: str
) -> None:
    respx_mock.post(GROQ_URL).mock(
        side_effect=[stream_response(chunk("Hel"), {"error": {"code": 502, "message": "x"}})]
    )

    async with make_client(stream_config()) as client:
        sdk = openai.AsyncOpenAI(
            base_url="http://gateway/v1",
            api_key=await new_api_key(database_url),
            http_client=client,
        )
        stream = await sdk.chat.completions.create(
            model="chat-fast", messages=[{"role": "user", "content": "Hi"}], stream=True
        )
        with pytest.raises(openai.APIError):
            async for _ in stream:
                pass


@pytest.mark.usefixtures("stream_keys")
async def test_interrupted_stream_keeps_its_reserved_tokens(
    make_client: ClientFactory, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    # Groq: 1000 tokens per minute. Each request reserves about 611 tokens.
    config = FAILOVER_CONFIG.replace(
        "llama-3.3-70b-versatile: {}", "llama-3.3-70b-versatile: { tpm: 1000 }"
    )
    request = {
        **STREAM_REQUEST,
        "messages": [{"role": "user", "content": "x" * 40}],
        "max_tokens": 600,
    }
    respx_mock.post(GROQ_URL).mock(
        side_effect=[stream_response(chunk("Hel"), {"error": {"code": 502, "message": "x"}})]
    )
    respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))

    async with make_client(config) as client:
        await read_stream(client, request)  # interrupted: part of the answer was generated
        second, _ = await read_stream(client, request)

    # The interrupted call kept its tokens, so Groq has no room left for a second one.
    assert second.headers["X-Gateway-Provider"] == "gemini"
    assert [row["outcome"] for row in await usage_rows()][-2:] == ["skipped_quota", "success"]


# --- Usage log ---


async def test_streamed_request_is_marked_as_streamed_on_every_usage_row(
    failover_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).respond(503)
    respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))

    response, _ = await read_stream(failover_client, STREAM_REQUEST)

    assert response.status_code == 200
    rows = await usage_rows()
    assert [(row["provider"], row["outcome"], row["stream"]) for row in rows] == [
        ("groq", "unavailable", True),
        ("gemini", "success", True),
    ]
    # Only the attempt that answered has a first content.
    assert rows[0]["first_token_ms"] is None
    assert rows[1]["first_token_ms"] is not None


async def test_usage_row_measures_the_first_content_and_the_whole_stream(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    async def upstream_body() -> AsyncIterator[bytes]:
        yield sse(chunk(role="assistant", content=""))  # no content yet
        await asyncio.sleep(0.3)
        yield sse(chunk("Hello"))  # the first content: the commit point
        await asyncio.sleep(0.3)
        yield sse("[DONE]")

    respx_mock.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=upstream_body()
        )
    )

    await read_stream(chat_client, STREAM_REQUEST)

    [row] = await usage_rows()
    # Tolerant bounds: timers on Windows can fire up to ~16 ms early.
    assert 280 <= row["first_token_ms"] < 550
    assert row["latency_ms"] >= 580
    assert row["latency_ms"] - row["first_token_ms"] >= 280


async def test_usage_row_of_an_empty_stream_has_no_first_content_time(
    chat_client: AsyncClient, respx_mock: respx.MockRouter, usage_rows: FetchUsageRows
) -> None:
    respx_mock.post(GROQ_URL).mock(
        return_value=stream_response(chunk(role="assistant", content=""), "[DONE]")
    )

    await read_stream(chat_client, STREAM_REQUEST)

    [row] = await usage_rows()
    assert row["outcome"] == "success"
    assert row["first_token_ms"] is None


async def test_streamed_request_refused_by_a_tenant_quota_is_marked_as_streamed(
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))
    config = CHAT_CONFIG + "\ntenants:\n  default_limits: { rpm: 1 }\n"

    async with make_client(config) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        refused = await client.post("/v1/chat/completions", json=STREAM_REQUEST)

    assert refused.status_code == 429
    allowed, rejected = await usage_rows()
    assert (allowed["outcome"], allowed["stream"]) == ("success", False)
    assert (rejected["outcome"], rejected["stream"]) == ("rejected_tenant_quota", True)
    assert rejected["first_token_ms"] is None


# --- Client disconnect ---


def held_open_stream(first: bytes, closed: asyncio.Event) -> httpx.Response:
    """A streamed answer that sends `first`, then stays open until the gateway closes it."""

    async def body() -> AsyncIterator[bytes]:
        try:
            yield first
            await asyncio.sleep(30)
            yield sse("[DONE]")
        finally:
            closed.set()  # the gateway closed the upstream call

    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())


async def rows_when_written(usage_rows: FetchUsageRows, count: int) -> list[dict[str, Any]]:
    """The usage log is written in the background: wait until `count` rows are there."""
    async with asyncio.timeout(5):
        while len(rows := await usage_rows()) < count:  # noqa: ASYNC110 (rows land in the database)
            await asyncio.sleep(0.05)
    return rows


@pytest.mark.usefixtures("stream_keys")
async def test_client_leaving_a_stream_closes_the_upstream_call(
    write_config: Callable[[str], Settings],
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
) -> None:
    respx_mock.route(host="127.0.0.1").pass_through()
    upstream_closed = asyncio.Event()
    groq = respx_mock.post(GROQ_URL).mock(
        side_effect=[
            held_open_stream(sse(chunk("Hel")), upstream_closed),
            httpx.Response(200, json=completion_body("llama-3.3-70b-versatile")),
        ]
    )

    async with live_gateway(write_config(stream_config())) as client:
        async with client.stream("POST", "/v1/chat/completions", json=STREAM_REQUEST) as response:
            await asyncio.wait_for(next_event_with(response.aiter_lines(), "Hel"), timeout=2)
        # The client left: the gateway stops reading from the provider at once.
        await asyncio.wait_for(upstream_closed.wait(), timeout=2)
        rows = await rows_when_written(usage_rows, 1)
        # A client that leaves is not the provider's fault: the breaker (opening
        # after one failure here) did not count it, so Groq still answers.
        after = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert rows[0]["outcome"] == "cancelled"
    assert rows[0]["first_token_ms"] is not None
    assert after.headers["X-Gateway-Provider"] == "groq"
    assert groq.call_count == 2


@pytest.mark.usefixtures("stream_keys")
async def test_client_leaving_before_the_first_content_stops_the_failover(
    write_config: Callable[[str], Settings],
    respx_mock: respx.MockRouter,
    usage_rows: FetchUsageRows,
) -> None:
    respx_mock.route(host="127.0.0.1").pass_through()
    upstream_closed = asyncio.Event()
    respx_mock.post(GROQ_URL).mock(
        side_effect=[held_open_stream(sse(chunk(role="assistant", content="")), upstream_closed)]
    )
    gemini = respx_mock.post(GEMINI_URL).mock(return_value=stream_response(*GEMINI_STREAM))
    # Groq times out after 1 s: without the disconnect, the gateway would then try Gemini.
    config = stream_config().replace(
        "llama-3.3-70b-versatile: {}", "llama-3.3-70b-versatile: { timeout: 1 }"
    )

    async with live_gateway(write_config(config)) as client:
        request = asyncio.create_task(client.post("/v1/chat/completions", json=STREAM_REQUEST))
        await asyncio.sleep(0.3)
        request.cancel()  # the client leaves while Groq has sent no content yet
        await asyncio.gather(request, return_exceptions=True)
        await asyncio.wait_for(upstream_closed.wait(), timeout=2)
        rows = await rows_when_written(usage_rows, 1)
        await asyncio.sleep(1.2)  # past the Groq timeout: a failover would have happened

    assert not gemini.called
    assert [(row["provider"], row["outcome"]) for row in await usage_rows()] == [
        ("groq", "cancelled")
    ]
    assert rows[0]["first_token_ms"] is None
