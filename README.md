# LLM Gateway

[![CI](https://github.com/EmeranYoa/llm-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/EmeranYoa/llm-gateway/actions/workflows/ci.yml)

An OpenAI-compatible gateway that routes chat requests across several LLM providers. Your application calls one endpoint with a model **alias**. The gateway picks a real provider and model that still has quota, fails over automatically on rate limits and outages, and logs every attempt.

It works with any provider that speaks the OpenAI Chat Completions API: paid APIs, free tiers, or models you host yourself (Ollama, vLLM). The example configuration uses free tiers (Groq, Google Gemini, OpenRouter) and a local Ollama model, so you can try everything at no cost.

## The problem

An application that depends on LLM APIs inherits all their failures. Each provider has its own limits (requests per minute, tokens per minute, requests per day), its own API key, its own error formats and its own outages, and models get renamed or removed. An application that talks to providers directly must track every limit, catch every `429` and switch providers by hand. When its provider is saturated or down, the application fails, even though another provider could have answered.

This is true of paid plans and of free tiers alike; free tiers only show it sooner, because their limits are small. And when several applications share the same provider accounts, one of them can use up the limits, or the budget, of all the others.

## What the gateway does

- **One OpenAI-compatible endpoint.** The official OpenAI SDK works by changing only `base_url` and `api_key`.
- **API keys and tenants.** Each client application (tenant) gets its own `gw_` API key, created and revoked with an admin command. Authentication is always on.
- **Tenant quotas.** Each tenant has its own requests per minute and daily token budget, so one greedy client cannot use up the provider limits, or the token budget, shared by everyone else.
- **Aliases.** The client asks for `chat-fast`; the gateway maps it to an ordered list of real `provider/model` targets.
- **Quotas.** It tracks RPM, TPM and RPD per target in Redis, and never sends a call that would exceed them.
- **Automatic failover.** On a `429`, a `5xx`, a timeout or a bad API key, it moves on to the next target. On a real client error (`400`), it answers at once instead of wasting quota on every provider.
- **Streaming.** `stream: true` returns Server-Sent Events in OpenAI format. The gateway still fails over until the first token, then relays the stream as it comes.
- **Semantic cache.** On the aliases you choose, a repeated or rephrased question is answered from Redis in milliseconds, without calling any provider. Each tenant has its own cache.
- **Cooldown and circuit breaker.** Rate-limited targets are skipped for the delay the provider asks for; unstable targets are skipped by a circuit breaker.
- **Shared state.** Quotas, cooldowns and breakers live in Redis, so several gateway instances share them.
- **Degraded mode.** If Redis goes down, the gateway keeps routing (without quota checks) instead of failing.
- **Usage log.** Every examined target is logged in PostgreSQL with its tenant and API key: outcome, latency, tokens, cost, fallbacks. Prompts are never stored.
- **Admin dashboard.** A web dashboard shows traffic, errors, latency, cost and cache savings, per tenant and per provider, the live state of every provider, and the routing path of each request. Operators also manage tenant keys and limits there. It talks to an admin API that is never exposed to the public network.

## Use cases

- **A production application that must stay up.** Route an alias to two or three paid providers: an outage or a `429` at one of them is invisible to your users.
- **One gateway for several applications.** Provider keys stay in one place. Each application gets its own `gw_` key, its own quotas and its own rows in the usage log.
- **Local first, cloud as a backup** (or the reverse). Put a self-hosted model and a cloud model in the same alias.
- **Prototyping at no cost.** Chain free tiers, as the example configuration does.

## Architecture

```mermaid
flowchart LR
    app["Your application<br/>(OpenAI SDK)"] -->|"POST /v1/chat/completions<br/>Bearer gw_... key<br/>model: chat-fast"| auth

    subgraph gateway["LLM Gateway (FastAPI)"]
        auth["Authenticator<br/>API key, cached 60 s"] --> tenant["TenantGate<br/>tenant RPM and<br/>daily token budget"]
        tenant --> cache["ResponseCache<br/>exact, then semantic lookup"]
        cache -->|"miss"| router["Router<br/>failover loop, deadline"]
        router --> gate["TargetGate<br/>Lua scripts"]
        router --> adapter["OpenAI-compatible<br/>provider adapter"]
    end

    auth <-->|"tenants, api_keys"| pg
    tenant <-->|"acquire_tenant<br/>(atomic)"| redis
    gate <-->|"acquire_target / record_outcome<br/>(atomic)"| redis[("Redis 8<br/>quotas, cooldowns,<br/>circuit breakers,<br/>cached answers")]
    cache <-->|"entries, vector search"| redis
    cache -->|"embeddings"| ollama
    adapter --> groq["Groq"]
    adapter --> gemini["Gemini"]
    adapter --> openrouter["OpenRouter"]
    adapter --> ollama["Ollama (local)"]
    router -->|"after the response"| pg[("PostgreSQL<br/>tenants, api_keys,<br/>usage_log")]
```

Operators sign in to the dashboard with a username and a password. Its Next.js server calls a separate admin API, on the internal network only; the browser never sees the session token:

```mermaid
flowchart LR
    operator["Operator<br/>(browser)"] -->|"session cookie<br/>(encrypted, httpOnly)"| dashboard["Dashboard<br/>(Next.js server, port 3000)"]
    dashboard -->|"Bearer gws_... session<br/>internal network only"| adminapi["Admin API<br/>(FastAPI, port 8001,<br/>never published)"]
    adminapi -->|"statistics, keys,<br/>admin actions"| pg[("PostgreSQL")]
    adminapi -->|"live state of targets,<br/>cache clear"| redis[("Redis")]
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
| `app/auth/` | API key generation, hashing and verification (with its cache) |
| `app/admin.py` | Admin command line: tenant keys and limits, cache clear, usage log purge |
| `app/admin_api/` | Admin API for the dashboard: statistics, live state of targets, requests and their routing path, admin actions |
| `app/routing/router.py` | Failover loop, deadline, outcome of each attempt |
| `app/routing/streaming.py` | A stream after its first content: idle timeout, maximum duration, token usage |
| `app/routing/acquisition.py` + `app/routing/lua/` | Atomic Redis scripts: tenant quotas, cooldown, circuit breaker, provider quota reservation |
| `app/routing/quotas.py` | Token estimate, provider daily reset time |
| `app/cache/` | Response cache: request keys, eligibility rules, embedding client, Redis store with vector search, replay of a cached answer as a stream |
| `app/providers/` | Provider interface and the generic OpenAI-compatible adapter |
| `app/storage/` | Tenants, API keys and usage log (SQLAlchemy async, Alembic migrations in `migrations/`) |
| `app/config.py` | Environment settings and `config/gateway.yaml` validation |
| `dashboard/` | Next.js admin dashboard (TypeScript); its API types are generated from the admin API's OpenAPI schema |

## Quickstart

Requirements: Docker with Docker Compose.

> **Free tiers and your data.** The quickstart uses the example configuration, with free tiers. Some free tiers may use the prompts you send to train or improve their models: with them, use public or demo data only, never confidential or personal data. See [Free-tier providers](#free-tier-providers).

```bash
git clone https://github.com/EmeranYoa/llm-gateway.git
cd llm-gateway
cp .env.example .env
# Put at least one key in .env, for example GROQ_API_KEY=gsk_...
# Providers without a key are disabled at startup, with a warning.

docker compose up -d --build
curl http://localhost:8000/health

# Create an API key for your application (shown only once: store it now).
docker compose exec gateway python -m app.admin create-key --tenant demo
```

To use the dashboard, also set its session secret in `.env` before `docker compose up`, then open [http://localhost:3000](http://localhost:3000) and create the first operator account with the setup token printed in the admin API logs:

```bash
# In .env: DASHBOARD_SESSION_SECRET=<at least 32 characters>, for example:
openssl rand -base64 32

# The one-time setup token, printed while no operator account exists:
docker compose logs admin-api | grep -i "setup token"
```

No API key at all? Run the optional local model instead (about 2 GB to download):

```bash
docker compose --profile ollama up -d --build
docker compose exec ollama ollama pull llama3.2:3b
```

Then call the gateway with the official OpenAI SDK, changing only `base_url` and `api_key`:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="gw_...")  # your gateway key
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
| `X-Gateway-Cache` | Only on aliases that use the cache: `hit`, `miss`, `bypass` or `unavailable` (see [Response cache](#response-cache)). |

Errors always use the OpenAI format (`{"error": {"message", "type", "param", "code"}}`), so the SDK raises its usual typed exceptions:

| Status | When |
|---|---|
| `400` | Invalid request, or a request too large for every target (`context_length_exceeded`). Provider client errors keep their status (`400`, `422`, ...) and are not retried elsewhere. |
| `401` | Missing, unknown or revoked gateway API key (`invalid_api_key`). |
| `404` | Unknown alias (`model_not_found`). |
| `429` | Your tenant is over its own quota (`tenant_quota_exceeded`): requests per minute, or daily token budget. `Retry-After` says when to retry. This is your quota, not a provider limit. |
| `503` | Every target is blocked or failed (`all_targets_failed`). `Retry-After` gives the smallest known wait. Also returned when no provider of the alias has an API key (`no_enabled_target`), or when your key cannot be checked because the database is down (`authentication_unavailable`). |
| `504` | The request deadline ran out (`deadline_exceeded`). |

## Streaming

Set `stream=True` as with the OpenAI API. Chunks arrive as the model writes them:

```python
stream = client.chat.completions.create(
    model="chat-fast",
    messages=[{"role": "user", "content": "Tell me a short story."}],
    stream=True,
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

Or with `curl` (`-N` prints each event as soon as it arrives):

```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer gw_..." -H "Content-Type: application/json" \
  -d '{"model": "chat-fast", "stream": true, "messages": [{"role": "user", "content": "Hi"}]}'
```

The stream follows one rule, the **commit point**: the first chunk with output for the client (text, reasoning or a tool call).

- **Before the commit point**, nothing is sent to the client, not even the status or the headers. Every error fails over as for a normal request: a `429`, a `5xx`, a timeout, or an error event sent by the provider just after its `200`. The client never sees the failed attempts.
- **At the commit point**, the client receives `200`, the `X-Gateway-*` headers and the first chunks. The target is fixed: there is no more failover.
- **After the commit point**, if the provider fails, goes silent for longer than `gateway.stream.idle_timeout`, or the stream lasts longer than `gateway.stream.max_duration`, the gateway sends an error event with the code `stream_interrupted` and closes the stream **without** `data: [DONE]`. The OpenAI SDK raises `APIError`, so a cut answer is never taken for a complete one.
- **If the client disconnects**, the gateway closes the provider call at once and stops failing over: a client that left costs nothing more.

Each chunk is relayed unchanged, except `model`, set to the real model like in normal responses. The request deadline only bounds the time to the first content: a long answer is not cut by it.

To keep quotas accurate, the gateway asks the provider for the token usage of the stream (`stream_options.include_usage`) even when the client did not, and then removes it from the stream: the client gets exactly what it asked for. Provider extensions pass through unchanged (Groq always sends its own `x_groq.usage`). If a provider reports no usage, the completion is estimated from the streamed characters.

## Response cache

Applications often ask the same question, or the same question in other words. For the aliases you choose, the gateway keeps complete answers in Redis and answers again without calling any provider: in about 65 ms instead of seconds, and without using any provider quota.

### Enable it

The cache compares questions by meaning with a local embedding model, run by Ollama:

```bash
docker compose --profile ollama up -d
docker compose exec ollama ollama pull nomic-embed-text   # about 270 MB
```

Then add a `cache` section to `config/gateway.yaml` (the example file has one, commented out) and restart the gateway:

```yaml
cache:
  embedding: { provider: ollama, model: nomic-embed-text }
  aliases:
    chat-fast: {}          # only the aliases listed here use the cache
```

Without the `embedding` line, the cache still answers identical requests.

### How it works

1. **Exact hit.** The request is hashed (every field except `stream`, `stream_options` and `model`, with sorted keys). An identical earlier request of the same tenant on the same alias gets its answer at once, without any embedding.
2. **Semantic hit.** Otherwise, the last user message is turned into a vector, and Redis vector search looks for the closest stored question **with exactly the same context**: same system prompt, same earlier messages, same parameters (`temperature`, `max_tokens`, ...). Above the similarity threshold (0.95 by default), the stored answer is returned.
3. **Miss.** The request is routed as usual. A complete answer (`finish_reason: stop`) is stored after the response, from a normal request or from a complete stream.

A cached answer comes with a new `id` and `created`, the original `model` and `usage`, and the `X-Gateway-Provider` / `X-Gateway-Model` of the target that generated it. A streamed request gets it as a stream. The client sees what happened in `X-Gateway-Cache`: `hit`, `miss`, `bypass` or `unavailable`.

```python
# Force a fresh answer: no lookup, and the new answer replaces the stored one.
client.chat.completions.create(
    model="chat-fast",
    messages=[{"role": "user", "content": "What is the capital of France?"}],
    extra_headers={"X-Gateway-Cache": "bypass"},
)
```

The default threshold was checked with the real `nomic-embed-text`: rephrased questions scored 0.89 to 0.99, while different but close questions ("reverse a list" / "reverse a string", "2 + 2" / "2 + 3", "capital of France" / "capital of Germany") scored 0.67 to 0.86. At 0.95, none of them gave a wrong hit. Each alias can set its own `similarity_threshold`, and the usage log records the similarity of every hit to tune it.

### Rules

- **Never cached:** requests with `tools`, `functions`, `n > 1` or `seed`, and requests with images or audio. Answers cut short (`length`), errors, and interrupted or cancelled streams are never stored.
- **Exact hits only:** when the last message is not a user question, or is longer than `max_semantic_chars` (2,000 characters by default): embedding models silently cut long texts, and two long texts with the same start would get the same vector.
- **Per tenant and per alias:** a tenant never gets an answer generated for another tenant.
- **Quotas:** a hit counts in the tenant's requests per minute, but uses none of its daily token budget and no provider quota.
- **Expiry:** an entry is kept for `ttl` seconds (24 h by default); a hit does not extend it. Above `max_entries_per_tenant` (10,000 by default), a tenant's new answers are no longer stored, but its lookups go on.
- **Failures:** if Redis or the embedding model fails or takes longer than `embedding.timeout` (1 s), the request is routed without the cache (`X-Gateway-Cache: unavailable`). The cache never makes a request fail. Its time counts in the request deadline.

To remove stored answers, for example after changing a system prompt:

```bash
docker compose exec gateway python -m app.admin clear-cache --tenant acme [--alias chat-fast]
docker compose exec gateway python -m app.admin clear-cache --all
```

> **Data kept in Redis.** With the cache on, model answers stay in Redis until they expire or are cleared. The text of the messages is never stored: lookups use hashes and vectors only. Redis creates vector indexes on database 0 only, so `REDIS_URL` must end with `/0` (as in Docker Compose).

## Authentication and tenants

Every request to `/v1/chat/completions` needs a gateway API key, sent as `Authorization: Bearer <key>` (the `api_key` of the OpenAI SDK). There is no setting to turn authentication off. `/health` stays public and only reports the gateway and Redis status.

A **tenant** is one client of the gateway: an application or a customer. Manage tenants and keys with the admin command, inside the container:

```bash
docker compose exec gateway python -m app.admin create-key --tenant acme --rpm 30 --tokens-per-day 200000
docker compose exec gateway python -m app.admin list-keys --tenant acme
docker compose exec gateway python -m app.admin revoke-key 12
docker compose exec gateway python -m app.admin set-limits --tenant acme --tokens-per-day 500000
```

- Keys look like `gw_` + 32 random bytes. `create-key` prints a key once; only its SHA-256 hash is stored. `list-keys` shows a short prefix (`gw_Ta-3Yw`), never a full key.
- A tenant can have several keys at the same time, to rotate a key without downtime: create the new key, switch the client, revoke the old key.
- Each tenant has a **requests-per-minute** limit and a **daily token budget** (reset at 00:00 UTC). Defaults come from `tenants.default_limits` in `gateway.yaml`; `create-key` and `set-limits` override them per tenant.
- Tenant quotas are checked once per request, before routing, on top of the provider quotas. The token budget works like the provider TPM: the estimate is reserved before the call, then replaced by the real usage on success, given back when the whole request fails, and kept on timeout.
- Verified keys are cached in memory for 60 s (`AUTH_CACHE_TTL`): most requests need no database query. A revoked key or new limits take effect within that time.

## Admin dashboard

The dashboard is for operators: whoever runs the gateway. It shows every tenant, and can filter on one.

| Screen | What it shows |
|---|---|
| **Overview** | Requests, error rate, fallback rate, latency p50/p95, time to first token, tokens, cost, cache hit rate and savings, with charts per hour (24 h) or per UTC day (7 and 30 days). |
| **Tenants** | One row per tenant: requests, tokens, cost, error rate, cache savings, quota refusals. A row opens the overview of that tenant. |
| **Providers** | For each provider/model: success rate, latency, `429`s, timeouts, skips, and its **live state** read in Redis: cooldown, circuit breaker, quotas used. It shows at a glance why traffic moves to another provider. |
| **Requests** | Recent requests, filtered by tenant, alias and status. A request opens its **routing path**: every target examined, in order, with its outcome and latency. |
| **Keys** | Create a tenant key (shown once), revoke a key, change a tenant's limits, clear its cache, and the history of admin actions. |

| **Operators** | The accounts that can sign in: create one, reset a password, disable or enable an account, change your own password. |

Live screens refresh every 10 seconds without reloading the page, and pause while the tab is hidden. Times are shown in your browser's time zone.

The dashboard speaks **English and French**. Before signing in it follows your browser's language; once signed in, the language chosen in the navigation bar is saved in your account and follows you on every device. Numbers, amounts and dates use the format of that language.

The indicators are counted per request, the way a client sees them:

- **Error rate**: requests that got no answer (`503`, `504`, a stream interrupted). Client errors (`400`, an unknown alias, a tenant over its quota) and requests the client cancelled are counted apart: they are not failures of the gateway.
- **Latency**: the whole request, all its attempts included. Cache hits are left out and shown apart, so they do not make providers look fast.
- **Cost**: the sum of the cost of each answer (see below). Answers of a model without a price are counted and shown as such, never as 0.

### Operator accounts and security

Operators sign in with a **username and a password**. Accounts are managed in the dashboard only, on the Operators screen; there is no command for them.

- **First account.** While no account exists, the admin API prints a one-time **setup token** in its logs. The dashboard's setup screen asks for it: only someone with access to the server can create the first account, not the first visitor of the page. Once an account exists, the setup screen is gone for good.
- **Other accounts.** An operator creates them with an initial password, which the new operator must change at their first sign-in. Creating an account, resetting a password, disabling or enabling an account and changing your own password all ask for **your current password again**: a stolen session alone cannot create new access. Nobody can disable themselves or the last enabled account, and disabling an account or resetting its password ends its sessions at once.
- **Lost passwords.** Set `OPERATOR_RECOVERY=true` in `.env` and restart: the admin API prints a one-time **recovery token**, and the dashboard's recovery screen uses it to give an account a new password (to change at the next sign-in). A banner reminds you to remove the variable afterwards.
- **Passwords** have at least 12 characters and are hashed with `scrypt` (OWASP parameters, a salt per account). After 5 wrong passwords in 15 minutes an account is locked for 15 minutes, and each browser address may try 20 times in 15 minutes. The sign-in answer is the same for an unknown username, a wrong password and a locked or disabled account, and takes the same time.
- **Sessions** last 8 hours. Only a hash of the session token is stored, and the admin API checks it in PostgreSQL on every call: signing out, disabling an account or resetting its password takes effect at once.
- The admin API runs in its own container, on port 8001, which Docker Compose never publishes. The dashboard's server keeps the session token in an encrypted, `httpOnly`, `SameSite=Strict` cookie and calls the admin API itself: the token never reaches the browser's JavaScript.
- Docker Compose publishes the dashboard on `127.0.0.1:3000` only. Its session cookie is `Secure`: to reach it from another machine, put it behind HTTPS.
- Every change made from the dashboard or the command line (accounts, keys, limits, cache clear, purge) is recorded in the `admin_actions` table, shown on the Keys screen. Passwords, tokens and key values are never recorded.

### Costs

Give each model its price in `gateway.yaml`, in US dollars per million tokens:

```yaml
models:
  openai/gpt-oss-20b: { rpm: 30, price: { input: 0.075, output: 0.30 } }   # example: check the provider's pricing page
```

The cost of each usage row is computed when it is written, from the real token usage and the price of that moment, so a later price change does not rewrite the past. A cache hit costs 0 and records what it saved at the price of the model that first answered. The example configuration prices its free-tier models at 0.

### Retention

The usage log keeps every row until you delete it. The dashboard looks back 30 days at most. To keep the table small, run the purge from a scheduler, for example every night with cron:

```bash
0 3 * * * docker compose -f /path/to/docker-compose.yml exec -T gateway python -m app.admin purge-usage-log --older-than-days 90
```

It deletes in small batches, so the gateway keeps writing while it runs, and records the purge as an admin action.

## Configuration reference

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` | (none) | Provider keys. The variable names are set per provider in `gateway.yaml`. |
| `GATEWAY_CONFIG_PATH` | `config/gateway.yaml` | Path of the routing config. |
| `REDIS_URL` | `redis://localhost:6379/0` | Set by Docker Compose. |
| `REDIS_TIMEOUT` | `0.25` | Seconds to wait for Redis before routing without it (degraded mode). |
| `DATABASE_URL` | `postgresql+asyncpg://gateway:gateway@localhost:5432/gateway` | Set by Docker Compose. |
| `DATABASE_TIMEOUT` | `5` | Seconds after which a usage log write or an API key check gives up. |
| `AUTH_CACHE_TTL` | `60` | Seconds a verified API key is trusted without a new database check. A revoked key or new tenant limits take effect within that time. |
| `AUTH_GRACE_PERIOD` | `900` | Seconds a verified API key keeps working while PostgreSQL is unavailable. Other keys get `503 authentication_unavailable`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `gateway` | Credentials of the PostgreSQL started by Docker Compose. |
| `DASHBOARD_SESSION_SECRET` | (none) | Dashboard only. Encrypts its session cookie. At least 32 characters, or the dashboard refuses to start. |
| `OPERATOR_RECOVERY` | `false` | Admin API only. `true` prints a one-time recovery token at startup, to give back access to an operator account. Remove it once done. |
| `ADMIN_API_URL` | (none) | Dashboard only. Where its server reaches the admin API. Set by Docker Compose (`http://admin-api:8001`). |

### `config/gateway.yaml`

The file has five sections. Limits belong to the **model**, routes only reference `provider/model`. An invalid file, or a route to an undeclared model, stops the gateway at startup with a clear message.

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
  stream:                     # streamed answers, after their first content
    idle_timeout: 30          # longest silence allowed between two events of the provider
    max_duration: 600         # longest time a stream may last (the deadline no longer applies)

tenants:                      # optional; a missing limit means "no limit"
  default_limits:
    rpm: 60                   # requests per minute of each tenant
    tokens_per_day: 500000    # daily token budget of each tenant, reset at 00:00 UTC

cache:                        # optional; no section, no cache
  embedding:                  # optional; without it, identical requests only
    provider: ollama          # a declared provider, called on /embeddings
    model: nomic-embed-text   # changing it starts an empty semantic cache
    timeout: 1                # seconds; slower means no cache for that request
  similarity_threshold: 0.95  # cosine similarity for a semantic hit
  ttl: 86400                  # seconds an answer is kept
  max_semantic_chars: 2000    # longer questions: exact hits only
  max_entries_per_tenant: 10000
  aliases:                    # only these aliases use the cache
    chat-fast: {}
    chat-faq: { similarity_threshold: 0.9, ttl: 604800 }   # per-alias overrides

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
| `price` | unknown | `{ input, output }` in US dollars per million tokens. Without it, the cost of the model's answers is unknown. |

See [`config/gateway.yaml`](config/gateway.yaml) for the full example.

### Usage log

The `usage_log` table has one row per examined target, grouped by `request_id`: tenant, API key, alias, provider, model, outcome, status, latency, token estimate and real usage. Streamed requests have `stream = true` and `first_token_ms`, the time to the first content; `latency_ms` is the whole duration of the attempt. On aliases that use the cache, every row has `cache` (`hit`, `miss`, `bypass` or `unavailable`); a hit is one `cache_hit` row with the tokens the cache saved and its `cache_similarity`. `cost_usd` is the cost of the row (NULL without a price or without token counts) and `saved_cost_usd` what a cache hit saved.

| Outcome | Meaning |
|---|---|
| `success` | The target answered. |
| `rate_limited`, `unavailable`, `timeout`, `misconfigured` | The call failed (`429`; `5xx` or network error; timeout; `401`/`403`/`404`). The gateway failed over. |
| `invalid_request` | The provider refused the client request. Returned to the client, no failover. |
| `context_too_large` | The request is too large for this target (skipped before the call, or refused by the provider). |
| `skipped_cooldown`, `skipped_breaker`, `skipped_quota` | Not called: cooldown, open circuit breaker, or full RPM/TPM/RPD quota. |
| `rejected_tenant_quota` | The tenant was over its own quota. No target is examined (`provider` and `model` are empty). |
| `interrupted` | A stream broke after its first content (provider error, idle timeout or maximum duration). |
| `cancelled` | The client disconnected before the end of the answer. |
| `cache_hit` | Answered from the cache. `provider`, `model` and the token counts are those of the original answer: the tokens saved. `latency_ms` is the lookup time. |

### Free-tier providers

Checked on the providers' documentation on 2026-10-21. Free tiers change often (Groq removed its free Llama models in August 2026), so check again before relying on these values.

| Provider | Models in the example config | Free-tier limits | Daily reset | Your data on the free tier |
|---|---|---|---|---|
| [Groq](https://console.groq.com/docs/rate-limits) | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` | 30 RPM, 8,000 TPM, 1,000 RPD | Not documented. The config uses 00:00 UTC; `429` responses and rate-limit headers correct it. | [Not used for training](https://console.groq.com/docs/legal/services-agreement); [may be logged up to 30 days](https://console.groq.com/docs/your-data). |
| [Gemini](https://ai.google.dev/gemini-api/docs/rate-limits) | `gemini-2.5-flash` | No longer published: read your project limits in Google AI Studio. The config uses conservative guesses. | 00:00 Pacific time | [Used to improve Google products](https://ai.google.dev/gemini-api/docs/pricing); human reviewers may read it. |
| [OpenRouter](https://openrouter.ai/docs/api/reference/limits) | `google/gemma-4-31b-it:free` | 20 RPM; 50 requests per day for the whole account (1,000 after buying 10 credits) | 00:00 UTC | [Depends on the upstream provider](https://openrouter.ai/docs/guides/privacy/provider-logging) and your account privacy settings. |
| [Ollama](https://ollama.com) (optional) | `llama3.2:3b` | None: runs on your machine | n/a | Stays on your machine. |

### Paid and self-hosted providers

Any API compatible with OpenAI Chat Completions can be declared as a provider, with its `base_url`, the environment variable of its key, and its models:

```yaml
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    models:
      gpt-5-mini: { rpm: 500, tpm: 200000, timeout: 60 }   # example: use the models and limits of your plan
  vllm:
    base_url: http://vllm:8000/v1   # a model you host yourself
    api_key_env: null
    models:
      my-model: { timeout: 120 }
```

- Set the limits of your plan, a little below the real ones: the gateway then spreads the load instead of waiting for `429`s. Without limits, it relies on `429`s and cooldowns only.
- The provider must take its key as `Authorization: Bearer` and accept `stream_options` (see [Limitations](#limitations)).
- Tenant token budgets become spending limits: set one per application with `set-limits`.
- In degraded mode (Redis down), quotas are not checked. With free tiers this costs nothing; with paid providers, tenant budgets no longer cap spending while Redis is down (see [Design decisions](#design-decisions)).

## Design decisions

**One atomic Lua script per call.** Before a call, the `acquire_target` script checks, in one atomic Redis operation, the cooldown, the circuit breaker and the RPM/TPM/RPD quotas, and reserves the quota only if every check passes. Separate Redis calls would race under concurrent requests: two requests could both see "1 request left" and both take it. A test sends 20 concurrent requests to a target limited to 5 per minute and checks that exactly 5 reach it; it fails if the check and the reservation are split.

**Fail open when Redis is down.** Exceeding a free-tier quota costs no money: the provider answers `429` and the gateway fails over. A Redis outage that stopped the gateway would cost far more. So without Redis the gateway routes without quota checks, logs a warning, marks usage rows `degraded` and reports `degraded` on `/health`. This must be revisited before using paid providers.

**Fail closed for authentication, fail open for quotas.** When PostgreSQL is down, a key verified in the last 15 minutes (`AUTH_GRACE_PERIOD`) keeps working, and any other key is refused with `503`: an unchecked key is never accepted. Quotas do the opposite and let requests through when Redis is down. The asymmetry follows the cost of a mistake: a missed quota check costs a `429` from a free tier, a missed authentication check lets anyone spend the provider keys.

**Two barriers: the tenant, then the providers.** A tenant over its own quota gets `429 tenant_quota_exceeded`; a request that no provider can serve gets `503`. The two errors are distinct, so a client knows whether the limit is its own or the platform's.

**Limits belong to the model, not to the route.** Providers count usage per model. Declaring limits on routes would allow two aliases to give different limits to the same model, for one shared counter.

**Errors are translated into five types.** The adapter maps every upstream error to `RateLimited`, `ProviderUnavailable`, `TargetMisconfigured`, `ContextTooLarge` or `InvalidRequest`. The router decides failover, cooldown and breaker from these types only, so it never depends on one provider's details.

**A client error is not a provider failure.** A `400` from the provider is returned at once (every other provider would refuse it too), and counts as a *success* for the circuit breaker: the provider worked. Otherwise a client sending bad requests could open the breaker for everyone.

**401, 403 and 404 fail over.** They mean a bad key or a removed model: a gateway configuration problem. The gateway logs an error, puts the target in a long cooldown and tries the next one, instead of returning a misleading `401` to the client.

**400, not 503, when a request is too large for every target.** The OpenAI SDK retries `503` automatically; it would retry forever a request that can never fit.

**Token accounting.** Before a call, the gateway reserves an estimate (`characters / 4`, plus `max_tokens` or `default_completion_tokens`, capped at the target TPM). After the call it replaces the estimate with the real usage, releases it on failure, and keeps it on timeout (the provider may have generated tokens anyway). The request itself always stays counted.

**Fail over until the first token, never after.** Before the commit point the client has received nothing, so switching targets is invisible to it. After it, switching would mix two answers in one stream, so the gateway reports the failure instead (`stream_interrupted`, no `[DONE]`). Reasoning counts as output: reasoning models think before they answer, and holding their reasoning back would leave the client waiting.

**A stream is recorded in two steps.** The commit point counts as a success for the circuit breaker (the provider answered), so a half-open trial ends there instead of lasting the whole stream. The end of the stream corrects the tokens; an interrupted stream also counts as a breaker failure. A disconnected client is neutral: it is not the provider's fault. Interrupted and cancelled streams keep their reserved tokens, as the provider may have generated them.

**The only change to the client request: stream usage.** The gateway never changes the request, with one exception: for streams it adds `stream_options.include_usage` and removes the usage chunk from what the client receives. Without it, most streams would report no usage, and every stream would keep its whole `max_tokens` reservation: budgets would run out far too early.

**A local embedding model, never a failover between them.** Vectors from two embedding models cannot be compared, so the cache uses one fixed model, and its name is part of the semantic search: changing it starts an empty semantic cache. A local model (Ollama) keeps the questions on your machine and costs no quota. If it is down, the cache is skipped, not switched to another model.

**Same context, similar question.** Comparing whole conversations by meaning would match two different conversations that end with "and in Python?". So only the last user question is compared by meaning; everything else (system prompt, earlier messages, parameters) must be identical. Unknown request fields count too, so a new parameter can never produce a wrong hit.

**Cache per tenant, opt-in per alias.** Sharing answers between tenants would give more hits, but an answer can quote the prompt of another client. And a semantic cache can return an answer to a slightly different question, so the operator turns it on alias by alias.

**One atomic write per answer.** A Lua script checks that no answer to the same request is stored yet and that the tenant is under its entry limit, then writes the entry: identical concurrent requests keep the first answer, and the limit is never over-booked. Redis has no eviction policy set, because it could evict quota or breaker keys instead of cache entries.

**The admin API in its own process, on a port nobody outside can reach.** The same code and image as the gateway, started with another command. The public surface is unchanged, a bug in an admin route or a stolen session cannot be used from the internet, and heavy statistics queries never slow down the chat traffic.

**A backend for frontend.** The dashboard's server, not the browser, holds the session token and calls the admin API. A script injected in the page could not steal it, and the admin API needs no CORS.

**Accounts for people, managed where people work.** v0.5.0 opened the dashboard with long admin keys created on the command line, which ended up pasted in chats and notes. Operators now sign in with a password, and manage each other's accounts in the dashboard. What a key gave for free has to be built: slow password hashing, account locks, no account enumeration, re-authentication for sensitive actions, and a way back in that only someone with the server can use.

**Translated in the dashboard, not in the API.** The admin API stays in English, like the gateway: a stable technical contract. The dashboard translates its error codes; its dictionaries are typed, so a missing French text fails the build.

**Statistics computed from the usage log, when asked.** Direct SQL with an index on `created_at`, over 30 days at most, instead of pre-aggregated tables to keep in sync. The admin API hides how the numbers are computed, so pre-aggregation can come later without changing the dashboard.

**One contract for two languages.** The dashboard's TypeScript types are generated from the admin API's OpenAPI schema, and CI fails when they are out of date: a field renamed in Python breaks the dashboard's type check, not production.

**Never store prompts.** The usage log stores the prompt length only. Upstream error messages of client errors are not stored either, because some providers quote the invalid input in them.

## Development

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync

# Tests need a real Redis (the routing state relies on Lua) and a real PostgreSQL.
docker run -d --rm --name gateway-test-redis -p 56379:6379 redis:8.8
docker run -d --rm --name gateway-test-pg -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=gateway_test -p 55432:5432 postgres:17-alpine

uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy

# Dashboard (bun installs packages and runs scripts; Node.js runs Next.js).
cd dashboard
bun install
bun run lint && bun run format:check && bun run typecheck && bun run test
bun run export:openapi && bun run generate:api   # after a change to the admin API
```

Tests go through the HTTP API: upstream providers are mocked with [respx](https://lundberg.github.io/respx/), Redis and PostgreSQL are real. They cover failover on `429`, `5xx` and timeouts, no failover on `400`, cooldowns, circuit breaker transitions (including the half-open trial under concurrency), concurrent quota reservation, `Retry-After`, streaming (failover before the first token, interruptions, stream timeouts, client disconnects, token usage), the response cache (exact and semantic hits, isolation per tenant and alias, eligibility, streams, bypass, entry limit, failures), the deadline, degraded mode, API keys (revocation, cache, database outages), tenant quotas under concurrency, the admin command line run as a real process, the admin API (exact statistics on known rows, key separation, live state, admin actions recorded in the same transaction), and the official OpenAI SDK. The dashboard is tested with Vitest and Testing Library (session, API client, every screen). CI runs the same checks on every push.

## Limitations

- **No failover once a stream has started.** After the first token, a provider failure ends the stream with a `stream_interrupted` error event; the client must retry.
- **A provider must accept `stream_options`.** The gateway adds it to every streamed request. The providers of the example config accept it; check a new provider before adding it.
- **A semantic hit answers a similar question, not the same one.** With a lower threshold, a close but different question can get a wrong answer. Keep the cache for aliases where that is acceptable, and use `bypass` or `clear-cache` to fix a wrong answer.
- **Identical concurrent requests all call a provider.** Before the first answer is stored, each of them is a miss; only the first answer is kept.
- **The cache needs Redis database 0**, where Redis creates its vector indexes.
- **The dashboard is for operators only.** Tenants cannot log in to see their own usage yet.
- **The sign-in limit per client address is per admin API process.** 20 attempts per address within 15 minutes are counted in memory: several admin API processes would each allow 20, and a restart forgets the count. The lock of an account after 5 failed sign-ins is stored in PostgreSQL and shared by every process.
- **Statistics are computed on demand**, over 30 days at most. On a very large usage log, pre-aggregated tables would be faster.
- **Costs are only as accurate as the configured prices.** Prices change: check them on each provider's pricing page.
- **A revoked key keeps working up to 60 s** on each gateway instance, until its cache entry expires (`AUTH_CACHE_TTL`). The cache is per instance.
- **A hanging PostgreSQL slows down authentication.** If the database accepts connections but never answers, each request whose key cache entry has expired waits `DATABASE_TIMEOUT` (5 s) before the grace period lets it through.
- **The tenant token budget is checked against an estimate.** A request whose `max_tokens` does not fit the remaining budget is refused, even if the real answer would have been short. The error message suggests lowering `max_tokens`.
- **Token estimates are approximate** (`characters / 4`). They are corrected with the real usage after each call.
- **The gateway only knows its own traffic.** If the same API key is also used elsewhere, the provider may answer `429` earlier than expected; the cooldown then takes over.
- **A field accepted by one provider but refused by another** gives a `400` without failover, because the gateway cannot tell it from a real client error.
- **Usage rows can be lost** if the process crashes right after sending a response: they are written in the background.
- **Ollama silently cuts long prompts.** On CPU its context window is 4,096 tokens by default; a longer prompt is truncated without an error. Raise `num_ctx` on the Ollama side for long prompts.
- **Free-tier limits change often.** The values in `config/gateway.yaml` were checked on the date given in the file; check them again before relying on them.
