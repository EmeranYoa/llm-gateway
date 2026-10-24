"""Load generator of the gateway benchmark (see bench/README.md).

It sends the same chat completion requests straight to the mock provider and through
the gateway, at several concurrency levels, and prints a Markdown table: throughput,
latency percentiles, and the gateway overhead against the direct call.

Only the standard library is used. The HTTP client is a minimal keep-alive HTTP/1.1
client on asyncio streams, not httpx: in a first measurement the httpx client used so
much CPU per request that it saturated at about 120 requests per second, before the
gateway did, so the numbers measured the client and not the gateway.

Usage (inside the bench Docker Compose project, where `mock` and `gateway` resolve):
    python load.py [--levels 1,10,50,100] [--requests N] [--scenarios a,b] [--jsonl]
The gateway API key is read from the BENCH_KEY environment variable.
"""

import argparse
import asyncio
import contextlib
import json
import math
import os
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

PROMPT = "Explain in one sentence what an API gateway does for a web application. " * 3
MAX_TOKENS = 50
REQUEST_TIMEOUT_SECONDS = 60
# The gateway stores a cache entry in a background task, after the response is sent.
CACHE_WRITE_WAIT_SECONDS = 1.0


@dataclass(frozen=True)
class Scenario:
    name: str
    target: str
    """Where the requests go: `mock` (direct call) or `gateway`."""
    model: str
    """The mock's model name for a direct call, a gateway alias otherwise."""
    stream: bool = False
    unique_prompts: bool = False
    """A new prompt for every request, so the cache never has the answer."""
    warm_cache: bool = False
    """Send one request and wait for its cache write before measuring."""
    baseline: str | None = None
    """The scenario whose p50 at the same concurrency is subtracted to get the overhead."""


SCENARIOS = [
    Scenario("direct", "mock", "mock-model"),
    Scenario("gateway", "gateway", "bench", baseline="direct"),
    Scenario("direct-stream", "mock", "mock-model", stream=True),
    Scenario("gateway-stream", "gateway", "bench", stream=True, baseline="direct-stream"),
    Scenario("first-target-down", "gateway", "bench-failover", baseline="direct"),
    Scenario("cache-miss", "gateway", "bench-cache", unique_prompts=True, baseline="direct"),
    Scenario("cache-hit", "gateway", "bench-cache", warm_cache=True, baseline="direct"),
]


@dataclass(frozen=True)
class Sample:
    """The outcome of one measured request."""

    ok: bool
    latency_ms: float
    first_content_ms: float | None
    cache: str | None
    """The X-Gateway-Cache header of the response, if any."""
    fallbacks: int | None
    """The X-Gateway-Fallbacks header of the response, if any."""
    status: int | None = None
    """The HTTP status, or None when no response came (connection error, timeout)."""


@dataclass(frozen=True)
class Result:
    """The figures of one scenario at one concurrency level."""

    scenario: str
    concurrency: int
    requests: int
    errors: int
    rps: float
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    ttft_p50_ms: float | None
    redis_us_per_request: float | None
    """CPU time of Redis per measured request, in microseconds (None for the mock)."""
    check: str
    """What the gateway headers say happened (cache result, fallbacks), to spot a
    scenario that did not do what its name says."""


# --- Minimal HTTP/1.1 client ---


class Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body
        self.first_content_at: float | None = None


class Connection:
    """One keep-alive HTTP/1.1 connection, sending one request at a time.

    It reads bodies sent with Content-Length or with chunked transfer encoding (the
    streams). When `watch_stream` is set, it reads a chunked body part by part and
    records when the first SSE event with content arrives.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def request(self, raw_request: bytes, watch_stream: bool = False) -> Response:
        if self._reader is None or self._writer is None:
            self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        reader, writer = self._reader, self._writer
        writer.write(raw_request)
        status_line = await reader.readline()
        if not status_line:
            raise ConnectionError("the server closed the connection")
        status = int(status_line.split()[1])
        headers: dict[str, str] = {}
        while (line := await reader.readline()) not in (b"\r\n", b"\n", b""):
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        scanner = _StreamScanner() if watch_stream else None
        body = await _read_body(reader, headers, scanner)
        response = Response(status, headers, body)
        if scanner is not None:
            response.first_content_at = scanner.first_content_at
        if headers.get("connection", "").lower() == "close":
            await self.close()
        return response

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()
        self._reader = None
        self._writer = None


async def _read_body(
    reader: asyncio.StreamReader, headers: dict[str, str], scanner: "_StreamScanner | None"
) -> bytes:
    if "chunked" in headers.get("transfer-encoding", "").lower():
        parts = []
        while True:
            size = int((await reader.readline()).split(b";")[0].strip(), 16)
            if size == 0:
                # Optional trailers, then the empty line that ends the body.
                while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                    pass
                return b"".join(parts)
            part = (await reader.readexactly(size + 2))[:-2]
            if scanner is not None:
                scanner.feed(part)
            parts.append(part)
    if "content-length" in headers:
        body = await reader.readexactly(int(headers["content-length"]))
    else:
        body = await reader.read()  # no length: the body ends when the connection closes
    if scanner is not None:
        scanner.feed(body)
    return body


class _StreamScanner:
    """Finds the first SSE event that carries content for the client."""

    def __init__(self) -> None:
        self.first_content_at: float | None = None
        self._pending = b""

    def feed(self, data: bytes) -> None:
        if self.first_content_at is not None:
            return
        lines = (self._pending + data).split(b"\n")
        self._pending = lines.pop()  # an incomplete line, completed by the next part
        for line in lines:
            if line.startswith(b"data: {") and _has_content(line[len(b"data: ") :]):
                self.first_content_at = time.perf_counter()
                return


def _has_content(event: bytes) -> bool:
    try:
        chunk = json.loads(event)
    except ValueError:
        return False
    return any(choice.get("delta", {}).get("content") for choice in chunk.get("choices", []))


def _raw_request(method: str, url: str, body: dict[str, object] | None, key: str | None) -> bytes:
    parts = urlsplit(url)
    data = json.dumps(body).encode() if body is not None else b""
    head = f"{method} {parts.path} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
    if body is not None:
        head += f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n"
    if key is not None:
        head += f"Authorization: Bearer {key}\r\n"
    return head.encode() + b"\r\n" + data


def _host_port(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    return parts.hostname or "localhost", parts.port or 80


# --- Scenarios ---


def _request_factory(scenario: Scenario, base_url: str, key: str | None) -> Callable[[], bytes]:
    """Build the raw requests of a scenario. Fixed requests are encoded only once."""
    path = "/v1/chat/completions" if scenario.target == "gateway" else "/ok/v1/chat/completions"
    url = base_url.rstrip("/") + path
    auth = key if scenario.target == "gateway" else None

    def build(prompt: str) -> bytes:
        body: dict[str, object] = {
            "model": scenario.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_TOKENS,
        }
        if scenario.stream:
            body["stream"] = True
        return _raw_request("POST", url, body, auth)

    if scenario.unique_prompts:
        return lambda: build(f"{PROMPT}[{uuid.uuid4().hex}]")
    fixed = build(PROMPT)
    return lambda: fixed


async def _send(connection: Connection, raw_request: bytes, scenario: Scenario) -> Sample:
    start = time.perf_counter()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
            response = await connection.request(raw_request, watch_stream=scenario.stream)
    except (OSError, ValueError, IndexError, TimeoutError, asyncio.IncompleteReadError):
        await connection.close()  # the next request opens a new connection
        return Sample(False, (time.perf_counter() - start) * 1000, None, None, None)
    end = time.perf_counter()
    ok = response.status == 200
    if scenario.stream:
        # A stream cut after its first content still has status 200: it is complete
        # only when it ends with [DONE].
        ok = ok and b"data: [DONE]" in response.body
    first_content_ms = None
    if response.first_content_at is not None:
        first_content_ms = (response.first_content_at - start) * 1000
    fallbacks = response.headers.get("x-gateway-fallbacks")
    return Sample(
        ok=ok,
        latency_ms=(end - start) * 1000,
        first_content_ms=first_content_ms,
        cache=response.headers.get("x-gateway-cache"),
        fallbacks=int(fallbacks) if fallbacks is not None else None,
        status=response.status,
    )


async def _drain(
    connection: Connection, requests: Iterator[bytes], scenario: Scenario, samples: list[Sample]
) -> None:
    # Every worker pulls from the same iterator, so the total number of requests is
    # fixed whatever the concurrency. Pulling is synchronous: no lock is needed.
    for raw_request in requests:
        samples.append(await _send(connection, raw_request, scenario))


async def run_scenario(
    scenario: Scenario,
    base_url: str,
    key: str | None,
    concurrency: int,
    total: int,
    redis_url: str | None = None,
) -> Result:
    next_request = _request_factory(scenario, base_url, key)
    connections = [Connection(*_host_port(base_url)) for _ in range(concurrency)]
    try:
        if scenario.warm_cache:
            await _send(connections[0], next_request(), scenario)
            await asyncio.sleep(CACHE_WRITE_WAIT_SECONDS)
        # Warm-up, not measured: opens the connections and fills the gateway's key cache.
        await asyncio.gather(*(_send(c, next_request(), scenario) for c in connections))
        samples: list[Sample] = []
        requests = (next_request() for _ in range(total))
        redis_before = await redis_cpu_seconds(redis_url) if redis_url else None
        start = time.perf_counter()
        await asyncio.gather(*(_drain(c, requests, scenario, samples) for c in connections))
        wall = time.perf_counter() - start
        redis_after = await redis_cpu_seconds(redis_url) if redis_url else None
    finally:
        await asyncio.gather(*(c.close() for c in connections))
    redis_us = None
    if redis_before is not None and redis_after is not None and samples:
        # Background work of the previous requests (usage log, cache writes) does not
        # touch Redis much, so the delta is close to the cost of these requests.
        redis_us = round((redis_after - redis_before) * 1_000_000 / len(samples), 1)
    return _summarise(scenario, concurrency, samples, wall, redis_us)


async def redis_cpu_seconds(url: str) -> float | None:
    """CPU seconds used so far by the main thread of Redis, from `INFO cpu`.

    The main thread runs every command and Lua script, so its CPU time per request is
    what the gateway costs Redis. Speaks RESP directly to keep to the standard library.
    None when Redis cannot be read: the column is then left empty.
    """
    host, port = _host_port(url)
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError:
        return None
    try:
        writer.write(b"*2\r\n$4\r\nINFO\r\n$3\r\ncpu\r\n")
        await writer.drain()
        header = await reader.readline()  # b"$<length>\r\n"
        if not header.startswith(b"$"):
            return None
        info = (await reader.readexactly(int(header[1:]) + 2)).decode()
    except (OSError, ValueError, asyncio.IncompleteReadError):
        return None
    finally:
        writer.close()
    fields = dict(line.split(":", 1) for line in info.splitlines() if ":" in line)
    try:
        return float(fields["used_cpu_sys_main_thread"]) + float(
            fields["used_cpu_user_main_thread"]
        )
    except (KeyError, ValueError):
        return None


def _summarise(
    scenario: Scenario,
    concurrency: int,
    samples: list[Sample],
    wall: float,
    redis_us_per_request: float | None = None,
) -> Result:
    latencies = [s.latency_ms for s in samples if s.ok]
    first_content = [s.first_content_ms for s in samples if s.ok and s.first_content_ms is not None]
    return Result(
        scenario=scenario.name,
        concurrency=concurrency,
        requests=len(samples),
        errors=sum(1 for s in samples if not s.ok),
        rps=round(len(samples) / wall, 1),
        p50_ms=_percentile(latencies, 50),
        p95_ms=_percentile(latencies, 95),
        p99_ms=_percentile(latencies, 99),
        ttft_p50_ms=_percentile(first_content, 50) if scenario.stream else None,
        redis_us_per_request=redis_us_per_request,
        check=_check(samples),
    )


def _percentile(values: list[float], percent: float) -> float | None:
    """Nearest-rank percentile, rounded to 0.1 ms. None when there is no value."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return round(ordered[rank - 1], 1)


def _check(samples: list[Sample]) -> str:
    notes = []
    cache = Counter(s.cache for s in samples if s.cache is not None)
    if cache:
        total = sum(cache.values())
        notes += [f"cache {value} {count * 100 // total}%" for value, count in cache.most_common()]
    fallbacks = [s.fallbacks for s in samples if s.fallbacks is not None]
    if fallbacks and any(fallbacks):
        notes.append(f"fallbacks {sum(fallbacks) / len(fallbacks):.2f}")
    # What the errors were: an HTTP status, a stream cut before [DONE], or no response.
    failures = Counter(
        "no response" if s.status is None else ("cut stream" if s.status == 200 else str(s.status))
        for s in samples
        if not s.ok
    )
    notes += [f"error {kind} x{count}" for kind, count in failures.most_common()]
    return ", ".join(notes)


# --- Output ---


COLUMNS = [
    "scenario",
    "concurrency",
    "requests",
    "errors",
    "req/s",
    "p50 ms",
    "p95 ms",
    "p99 ms",
    "overhead p50 ms",
    "TTFT p50 ms",
    "Redis us/req",
    "check",
]


def markdown_table(results: list[Result], scenarios: list[Scenario]) -> str:
    """One row per scenario and concurrency, grouped by scenario."""
    by_key = {(r.scenario, r.concurrency): r for r in results}
    order = {s.name: index for index, s in enumerate(scenarios)}
    baselines = {s.name: s.baseline for s in scenarios}
    rows = []
    for result in sorted(results, key=lambda r: (order[r.scenario], r.concurrency)):
        baseline = by_key.get((baselines[result.scenario] or "", result.concurrency))
        overhead = ""
        if baseline is not None and result.p50_ms is not None and baseline.p50_ms is not None:
            overhead = f"{result.p50_ms - baseline.p50_ms:+.1f}"
        rows.append(
            [
                result.scenario,
                str(result.concurrency),
                str(result.requests),
                str(result.errors),
                f"{result.rps:.1f}",
                _ms(result.p50_ms),
                _ms(result.p95_ms),
                _ms(result.p99_ms),
                overhead,
                _ms(result.ttft_p50_ms),
                _ms(result.redis_us_per_request),
                result.check,
            ]
        )
    widths = [max(len(row[i]) for row in [COLUMNS, *rows]) for i in range(len(COLUMNS))]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)) + " |"

    separator = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    return "\n".join([line(COLUMNS), separator, *(line(row) for row in rows)])


def _ms(value: float | None) -> str:
    return "" if value is None else f"{value:.1f}"


# --- Main ---


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the gateway against the mock.")
    parser.add_argument(
        "--levels",
        default="1,10,50,100",
        help="concurrency levels, comma separated (default: 1,10,50,100)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        help="measured requests per scenario and level (default: max(300, 40 x concurrency))",
    )
    parser.add_argument(
        "--scenarios",
        default=",".join(s.name for s in SCENARIOS),
        help="scenarios to run, comma separated (default: all)",
    )
    parser.add_argument(
        "--jsonl", action="store_true", help="also print one JSON line per result as it ends"
    )
    parser.add_argument(
        "--gateway-url", default=os.environ.get("BENCH_GATEWAY_URL", "http://gateway:8000")
    )
    parser.add_argument("--mock-url", default=os.environ.get("BENCH_MOCK_URL", "http://mock:9000"))
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("BENCH_REDIS_URL", "redis://redis:6379"),
        help="Redis of the gateway, read for the Redis CPU time per request",
    )
    args = parser.parse_args(argv)
    names = {s.name for s in SCENARIOS}
    unknown = set(args.scenarios.split(",")) - names
    if unknown:
        parser.error(f"unknown scenario(s): {', '.join(sorted(unknown))}")
    return args


async def _check_health(url: str) -> None:
    """Stop at once when a service is not up, instead of measuring only errors."""
    connection = Connection(*_host_port(url))
    try:
        response = await connection.request(_raw_request("GET", url + "/health", None, None))
    finally:
        await connection.close()
    status = json.loads(response.body).get("status") if response.status == 200 else None
    if status != "ok":
        # "degraded" means the gateway runs without Redis: no quota or breaker to measure.
        sys.exit(f"{url}/health is not ok: HTTP {response.status} {response.body[:200]!r}")


async def main(argv: list[str]) -> None:
    args = _parse_args(argv)
    levels = [int(level) for level in args.levels.split(",")]
    selected = args.scenarios.split(",")
    scenarios = [s for s in SCENARIOS if s.name in selected]
    key = os.environ.get("BENCH_KEY")
    urls = {"mock": args.mock_url, "gateway": args.gateway_url}
    if any(s.target == "gateway" for s in scenarios):
        if not key:
            sys.exit("BENCH_KEY is empty: the gateway scenarios need a tenant API key")
        await _check_health(args.gateway_url)
    if any(s.target == "mock" for s in scenarios):
        await _check_health(args.mock_url)

    results = []
    for concurrency in levels:
        total = args.requests or max(300, 40 * concurrency)
        for scenario in scenarios:
            print(f"{scenario.name}, concurrency {concurrency}...", file=sys.stderr, flush=True)
            redis_url = args.redis_url if scenario.target == "gateway" else None
            result = await run_scenario(
                scenario, urls[scenario.target], key, concurrency, total, redis_url
            )
            results.append(result)
            if args.jsonl:
                print(json.dumps(asdict(result)), flush=True)

    delay = os.environ.get("BENCH_MOCK_DELAY_MS", "?")
    workers = os.environ.get("BENCH_WEB_CONCURRENCY", "?")
    print(f"\nMock delay {delay} ms, gateway workers {workers}.\n")
    print(markdown_table(results, scenarios))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
