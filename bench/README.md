# Benchmark

This folder measures what the gateway itself costs: the time it adds to each call
and the number of requests per second it can serve. The provider is a mock that
answers after a fixed delay, so the numbers do not depend on a real provider, the
network or free-tier quotas.

Everything runs in its own Docker Compose project, `llm-gateway-bench`: its own
Redis, PostgreSQL, mock provider, gateway and load runner, on its own network, with
no published port. It does not touch your own stack (`llm-gateway`), its data or its
ports, and it can run while that stack is up.

## Run it

From the repository root:

```bash
docker compose -f bench/docker-compose.yml run --rm --build load
docker compose -f bench/docker-compose.yml down -v
```

The first command builds the gateway image from this repository, starts Redis,
PostgreSQL, the mock and the gateway, waits until the gateway is healthy, creates a
tenant API key, runs every scenario at every concurrency level and prints a Markdown
table. Progress lines go to stderr, so `> result.md` keeps only the table. A full run
takes about ten minutes with one gateway worker.

The second command stops the project and deletes its containers, network and
volumes. Run it after each measurement: a second run on the same project would find
the cache entries and breaker state of the first one.

Options, given after `load`:

| Option | Default | Meaning |
|---|---|---|
| `--levels 1,10,50,100` | `1,10,50,100` | concurrency levels (connections sending requests at the same time) |
| `--requests N` | `max(300, 40 x concurrency)` | measured requests per scenario and level |
| `--scenarios a,b` | all | scenarios to run, by name (see below) |
| `--jsonl` | off | also print one JSON line per result, as each one ends |

Environment variables, set before `docker compose`:

| Variable | Default | Meaning |
|---|---|---|
| `BENCH_WEB_CONCURRENCY` | `1` | gateway worker processes (uvicorn `WEB_CONCURRENCY`) |
| `BENCH_MOCK_DELAY_MS` | `50` | time the mock waits before it answers |
| `BENCH_GATEWAY_CONTEXT` | `..` | build context of the gateway image, relative to `bench/` |

For example, a quick run with two gateway workers:

```bash
BENCH_WEB_CONCURRENCY=2 docker compose -f bench/docker-compose.yml run --rm --build load --levels 1,50
```

## Scenarios

Each scenario first sends one request per connection that is not measured (it opens
the connections and fills the gateway's API key cache), then the measured requests.

| Scenario | What it sends | Compared with |
|---|---|---|
| `direct` | a chat completion straight to the mock, without the gateway | |
| `gateway` | the same request through the gateway (alias `bench`) | `direct` |
| `direct-stream` | a streamed chat completion straight to the mock | |
| `gateway-stream` | the same stream through the gateway | `direct-stream` |
| `first-target-down` | alias `bench-failover`: its first target always answers 503, the second one answers | `direct` |
| `cache-miss` | alias `bench-cache` with a new prompt each time: embedding, vector search, provider call, then the background cache write | `direct` |
| `cache-hit` | alias `bench-cache` with the same prompt each time: an exact hit, no provider call | `direct` |

Columns of the table:

- `errors`: requests without a 200, and streams that did not end with `data: [DONE]`.
  Latencies are computed on the successful requests only.
- `req/s`: measured requests divided by the time they took, for the whole level.
- `p50 ms`, `p95 ms`, `p99 ms`: latency percentiles, from the request sent to the
  last byte of the answer.
- `overhead p50 ms`: p50 of the scenario minus p50 of the scenario it is compared
  with, at the same concurrency. This is the time the gateway adds. It is negative
  for cache hits: the gateway answers without waiting for the provider.
- `TTFT p50 ms`: for streams, time to the first event with content (time to first
  token).
- `check`: what the gateway's response headers say happened (`X-Gateway-Cache`, the
  mean of `X-Gateway-Fallbacks`), to spot a scenario that did not do what its name
  says.

What the gateway does on each call, as in production: API key check, the tenant
quota script, the target quota script (`bench/gateway.yaml` gives the mock high but
present limits, so RPM, TPM and RPD are checked and reserved on every call), the
provider call, the outcome script, and the usage log row in PostgreSQL. The tenant
has no limit: the bench configuration has no `tenants` section.

In `first-target-down`, the circuit breaker of the down target opens after 5
failures. Most requests then skip it without calling it, and a single trial call
goes through every 30 seconds, as in a real outage. The scenario measures that
path: one skipped target, then the call to the second one.

## Read the numbers with care

- Everything runs on one machine: the load runner, the mock, the gateway, Redis and
  PostgreSQL share the same CPUs. Take the numbers as orders of magnitude, and
  compare two versions only when they are measured on the same machine, in the same
  conditions, one after the other.
- The load runner is a minimal HTTP/1.1 client on asyncio streams (`load.py`). A
  first version used httpx, which saturated at about 120 requests per second, before
  the gateway did. The mock (FastAPI, one worker) answers more than 3000 requests per
  second, so neither of them is the limit.
- With real providers, a call takes hundreds of milliseconds and the free tiers allow
  a few requests per minute: the provider quotas are the limit long before the
  gateway is.

## Measure another version

The gateway image can be built from any checkout. For example, to measure the
`v0.5.1` tag, from the repository root:

```bash
git worktree add ../gw-v0.5.1 v0.5.1
BENCH_GATEWAY_CONTEXT=../../gw-v0.5.1 docker compose -f bench/docker-compose.yml run --rm --build load
docker compose -f bench/docker-compose.yml down -v
git worktree remove ../gw-v0.5.1
```

`BENCH_GATEWAY_CONTEXT` is relative to the `bench/` folder, hence `../../`. The mock,
the load runner and `bench/gateway.yaml` always come from the current checkout; only
the gateway code changes. The bench configuration uses the cache section and model
prices, so it needs v0.5.0 or later (older versions refuse to start with it).

Keep `--build`: the image keeps the same name whatever the build context, so without
it Docker Compose would reuse the image of the previous run.

## Clean up

```bash
docker compose -f bench/docker-compose.yml down -v --rmi local
```

`down -v` removes the containers, the network and the volumes of the project.
`--rmi local` also removes the images it built (`llm-gateway-bench-*`).
