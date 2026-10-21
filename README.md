# LLM Gateway

[![CI](https://github.com/EmeranYoa/llm-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/EmeranYoa/llm-gateway/actions/workflows/ci.yml)

An OpenAI-compatible gateway that routes chat requests across several **free-tier LLM providers** (Groq, Google Gemini, OpenRouter, local Ollama). Your application calls one endpoint with a model **alias**. The gateway picks a real provider and model that still has quota, fails over automatically on rate limits and outages, and logs every attempt.

> **Free tiers and your data.** Some free tiers may use the prompts you send to train or improve their models. Use this gateway with public or demo data only, never with confidential or personal data. See [Free-tier providers](#free-tier-providers).

## The problem

Free LLM tiers are generous but fragile. Each provider has its own small limits (requests per minute, tokens per minute, requests per day), its own API key, its own error formats and its own outages. An application that talks to them directly must track every limit, catch every `429` and switch providers by hand. When one provider is saturated, the application fails, even though another one could have answered.

## What the gateway does

- **One OpenAI-compatible endpoint.** The official OpenAI SDK works by changing only `base_url`.
- **Aliases.** The client asks for `chat-fast`; the gateway maps it to an ordered list of real `provider/model` targets.
- **Quotas.** It tracks RPM, TPM and RPD per target in Redis, and never sends a call that would exceed them.
- **Automatic failover.** On a `429`, a `5xx`, a timeout or a bad API key, it moves on to the next target. On a real client error (`400`), it answers at once instead of wasting quota on every provider.
- **Cooldown and circuit breaker.** Rate-limited targets are skipped for the delay the provider asks for; unstable targets are skipped by a circuit breaker.
- **Shared state.** Quotas, cooldowns and breakers live in Redis, so several gateway instances share them.
- **Degraded mode.** If Redis goes down, the gateway keeps routing (without quota checks) instead of failing.
- **Usage log.** Every examined target is logged in PostgreSQL: outcome, latency, tokens, fallbacks. Prompts are never stored.

## Architecture

```mermaid
flowchart LR
    app["Your application<br/>(OpenAI SDK)"] -->|"POST /v1/chat/completions<br/>model: chat-fast"| api

    subgraph gateway["LLM Gateway (FastAPI)"]
        api["API<br/>validation, OpenAI errors"] --> router["Router<br/>failover loop, deadline"]
        router --> gate["TargetGate<br/>Lua scripts"]
        router --> adapter["OpenAI-compatible<br/>provider adapter"]
    end

    gate <-->|"acquire_target / record_outcome<br/>(atomic)"| redis[("Redis<br/>quotas, cooldowns,<br/>circuit breakers")]
    adapter --> groq["Groq"]
    adapter --> gemini["Gemini"]
    adapter --> openrouter["OpenRouter"]
    adapter --> ollama["Ollama (local)"]
    api -->|"after the response"| pg[("PostgreSQL<br/>usage_log")]
```

For each request, the router walks the targets of the alias in order:

```mermaid
flowchart TD
    start(["Next target of the alias"]) --> deadline{"Time left before<br/>the deadline?"}
    deadline -- no --> e504["504 deadline_exceeded"]
    deadline -- yes --> fits{"Prompt estimate<br/>fits the target TPM?"}
    fits -- no --> skip["Skip (logged)"]
    fits -- yes --> acquire{"acquire_target (Lua):<br/>cooldown, breaker,<br/>RPM / TPM / RPD"}
    acquire -- refused --> skip
    acquire -- reserved --> call["Call the provider"]
    call -- success --> ok["200 + X-Gateway-* headers"]
    call -- "400 client error" --> e400["Return the error at once"]
    call -- "429, 5xx, timeout,<br/>401/403/404, context too large" --> skip
    skip --> more{"More targets?"}
    more -- yes --> start
    more -- no --> end_["503 with Retry-After<br/>(or 400 if the request fits no target)"]
```

| Module | Role |
|---|---|
| `app/api/routes.py` | HTTP endpoints, OpenAI error format, response headers |
| `app/routing/router.py` | Failover loop, deadline, outcome of each attempt |
| `app/routing/acquisition.py` + `app/routing/lua/` | Atomic Redis scripts: cooldown, circuit breaker, quota reservation |
| `app/routing/quotas.py` | Token estimate, provider daily reset time |
| `app/providers/` | Provider interface and the generic OpenAI-compatible adapter |
| `app/storage/usage.py` | Usage log (SQLAlchemy async, Alembic migrations in `migrations/`) |
| `app/config.py` | Environment settings and `config/gateway.yaml` validation |

## Quickstart

Requirements: Docker with Docker Compose.

```bash
git clone https://github.com/EmeranYoa/llm-gateway.git
cd llm-gateway
cp .env.example .env
# Put at least one key in .env, for example GROQ_API_KEY=gsk_...
# Providers without a key are disabled at startup, with a warning.

docker compose up -d --build
curl http://localhost:8000/health
```

Ollama is optional. If you run [Ollama](https://ollama.com) on your machine (`ollama pull llama3.2:3b`), the gateway reaches it at `host.docker.internal:11434` as the last-resort target. On Linux, add `extra_hosts: ["host.docker.internal:host-gateway"]` to the `gateway` service.

Then call the gateway with the official OpenAI SDK, changing only `base_url`:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-used-by-the-gateway")
response = client.chat.completions.with_raw_response.create(
    model="chat-fast",
    messages=[{"role": "user", "content": "Say hello in French."}],
)
completion = response.parse()
print(completion.choices[0].message.content)
print(response.headers["X-Gateway-Provider"], response.headers["X-Gateway-Fallbacks"])
```

Every response tells you how it was routed:

| Header | Meaning |
|---|---|
| `X-Gateway-Provider` / `X-Gateway-Model` | The provider and model that answered. The body `model` field has the same value. |
| `X-Gateway-Fallbacks` | Targets examined before the one that answered (skipped or failed). |
| `X-Gateway-Request-Id` | Id of the request in the usage log. Also sent on errors. |

Errors always use the OpenAI format (`{"error": {"message", "type", "param", "code"}}`), so the SDK raises its usual typed exceptions:

| Status | When |
|---|---|
| `400` | Invalid request, `stream: true` (not supported yet), or a request too large for every target (`context_length_exceeded`). Provider client errors keep their status (`400`, `422`, ...) and are not retried elsewhere. |
| `404` | Unknown alias (`model_not_found`). |
| `503` | Every target is blocked or failed (`all_targets_failed`). `Retry-After` gives the smallest known wait. Also returned when no provider of the alias has an API key (`no_enabled_target`). |
| `504` | The request deadline ran out (`deadline_exceeded`). |

## Configuration reference

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` | (none) | Provider keys. The variable names are set per provider in `gateway.yaml`. |
| `GATEWAY_CONFIG_PATH` | `config/gateway.yaml` | Path of the routing config. |
| `REDIS_URL` | `redis://localhost:6379/0` | Set by Docker Compose. |
| `REDIS_TIMEOUT` | `0.25` | Seconds to wait for Redis before routing without it (degraded mode). |
| `DATABASE_URL` | `postgresql+asyncpg://gateway:gateway@localhost:5432/gateway` | Set by Docker Compose. |
| `DATABASE_TIMEOUT` | `5` | Seconds after which a usage log write gives up. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `gateway` | Credentials of the PostgreSQL started by Docker Compose. |

### `config/gateway.yaml`

The file has three sections. Limits belong to the **model**, routes only reference `provider/model`. An invalid file, or a route to an undeclared model, stops the gateway at startup with a clear message.

```yaml
gateway:                      # all optional, defaults shown
  deadline: 60                # seconds for a whole request, failovers included
  min_attempt_time: 1         # no new attempt starts with less time left
  default_completion_tokens: 512   # token estimate when max_tokens is missing
  cooldown:
    initial: 60               # after a 429 without retry delay; doubles on each 429 in a row
    max: 3600                 # cap of that progressive cooldown
    misconfigured: 600        # after a 401, 403 or 404 (bad key, removed model)
  breaker:
    failures: 5               # 5xx / network errors / timeouts within the window that open it
    window: 60                # seconds
    open: 30                  # seconds before a single trial call is let through

providers:
  groq:
    base_url: https://api.groq.com/openai/v1
    api_key_env: GROQ_API_KEY # null for providers without a key (Ollama)
    daily_reset: { time: "00:00", timezone: "UTC" }   # when the provider resets its RPD
    models:
      openai/gpt-oss-20b: { rpm: 30, tpm: 8000, rpd: 1000, timeout: 30 }

routes:
  # provider/model, split on the first "/": the model id may contain "/" itself.
  chat-fast: [ groq/openai/gpt-oss-20b, ollama/llama3.2:3b ]
```

| Model field | Default | Meaning |
|---|---|---|
| `rpm`, `tpm`, `rpd` | no limit | Requests per minute, tokens per minute, requests per day. |
| `timeout` | `30` | Seconds for one attempt (also bounded by the request deadline). |

See [`config/gateway.yaml`](config/gateway.yaml) for the full example.

### Free-tier providers

Checked on the providers' documentation on 2026-10-21. Free tiers change often (Groq removed its free Llama models in August 2026), so check again before relying on these values.

| Provider | Models in the example config | Free-tier limits | Daily reset | Your data on the free tier |
|---|---|---|---|---|
| [Groq](https://console.groq.com/docs/rate-limits) | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` | 30 RPM, 8,000 TPM, 1,000 RPD | Not documented. The config uses 00:00 UTC; `429` responses and rate-limit headers correct it. | [Not used for training](https://console.groq.com/docs/legal/services-agreement); [may be logged up to 30 days](https://console.groq.com/docs/your-data). |
| [Gemini](https://ai.google.dev/gemini-api/docs/rate-limits) | `gemini-2.5-flash` | No longer published: read your project limits in Google AI Studio. The config uses conservative guesses. | 00:00 Pacific time | [Used to improve Google products](https://ai.google.dev/gemini-api/docs/pricing); human reviewers may read it. |
| [OpenRouter](https://openrouter.ai/docs/api/reference/limits) | `google/gemma-4-31b-it:free` | 20 RPM; 50 requests per day for the whole account (1,000 after buying 10 credits) | 00:00 UTC | [Depends on the upstream provider](https://openrouter.ai/docs/guides/privacy/provider-logging) and your account privacy settings. |
| [Ollama](https://ollama.com) (optional) | `llama3.2:3b` | None: runs on your machine | n/a | Stays on your machine. |

## Design decisions

**One atomic Lua script per call.** Before a call, the `acquire_target` script checks, in one atomic Redis operation, the cooldown, the circuit breaker and the RPM/TPM/RPD quotas, and reserves the quota only if every check passes. Separate Redis calls would race under concurrent requests: two requests could both see "1 request left" and both take it. A test sends 20 concurrent requests to a target limited to 5 per minute and checks that exactly 5 reach it; it fails if the check and the reservation are split.

**Fail open when Redis is down.** Exceeding a free-tier quota costs no money: the provider answers `429` and the gateway fails over. A Redis outage that stopped the gateway would cost far more. So without Redis the gateway routes without quota checks, logs a warning, marks usage rows `degraded` and reports `degraded` on `/health`. This must be revisited before using paid providers.

**Limits belong to the model, not to the route.** Providers count usage per model. Declaring limits on routes would allow two aliases to give different limits to the same model, for one shared counter.

**Errors are translated into five types.** The adapter maps every upstream error to `RateLimited`, `ProviderUnavailable`, `TargetMisconfigured`, `ContextTooLarge` or `InvalidRequest`. The router decides failover, cooldown and breaker from these types only, so it never depends on one provider's details.

**A client error is not a provider failure.** A `400` from the provider is returned at once (every other provider would refuse it too), and counts as a *success* for the circuit breaker: the provider worked. Otherwise a client sending bad requests could open the breaker for everyone.

**401, 403 and 404 fail over.** They mean a bad key or a removed model: a gateway configuration problem. The gateway logs an error, puts the target in a long cooldown and tries the next one, instead of returning a misleading `401` to the client.

**400, not 503, when a request is too large for every target.** The OpenAI SDK retries `503` automatically; it would retry forever a request that can never fit.

**Token accounting.** Before a call, the gateway reserves an estimate (`characters / 4`, plus `max_tokens` or `default_completion_tokens`, capped at the target TPM). After the call it replaces the estimate with the real usage, releases it on failure, and keeps it on timeout (the provider may have generated tokens anyway). The request itself always stays counted.

**Never store prompts.** The usage log stores the prompt length only. Upstream error messages of client errors are not stored either, because some providers quote the invalid input in them.

## Development

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync

# Tests need a real Redis (the routing state relies on Lua) and a real PostgreSQL.
docker run -d --rm --name gateway-test-redis -p 56379:6379 redis:7.4-alpine
docker run -d --rm --name gateway-test-pg -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=gateway_test -p 55432:5432 postgres:17-alpine

uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Tests go through the HTTP API: upstream providers are mocked with [respx](https://lundberg.github.io/respx/), Redis and PostgreSQL are real. They cover failover on `429`, `5xx` and timeouts, no failover on `400`, cooldowns, circuit breaker transitions (including the half-open trial under concurrency), concurrent quota reservation, `Retry-After`, the deadline, degraded mode, and the official OpenAI SDK. CI runs the same checks on every push.

## Limitations

- **No streaming yet.** `stream: true` is refused with a clear `400`.
- **No client authentication.** Anyone who can reach the gateway can use its provider keys. Keep it on a private network.
- **Token estimates are approximate** (`characters / 4`). They are corrected with the real usage after each call.
- **The gateway only knows its own traffic.** If the same API key is also used elsewhere, the provider may answer `429` earlier than expected; the cooldown then takes over.
- **A field accepted by one provider but refused by another** gives a `400` without failover, because the gateway cannot tell it from a real client error.
- **Usage rows can be lost** if the process crashes right after sending a response: they are written in the background.
- **Free-tier limits change often.** The values in `config/gateway.yaml` were checked on the date given in the file; check them again before relying on them.
