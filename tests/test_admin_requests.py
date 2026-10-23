"""Tests for the requests of the admin API: find a request and see how it was routed.

The usage log is seeded directly with SQL, so each test controls every row.
"""

import asyncio
import base64
import datetime as dt
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.admin_api.request_status import request_status
from app.config import Settings
from app.storage.tenants import create_api_key
from app.storage.usage import UsageLogRow
from tests.conftest import MINIMAL_CONFIG, DatabaseProxy
from tests.test_admin_api import admin_client, new_session

WriteConfig = Callable[[str], Settings]

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.5-flash"
OLLAMA_MODEL = "llama3.2:3b"

NOW = dt.datetime.now(dt.UTC)
"""Seeded rows are dated relative to the start of the test session."""

LAST_24_HOURS = ["failover", "cache-hit", "rejected", "failed", "cancelled", "client-error"]
"""The requests of `mixed_requests` in the last 24 h, newest first."""


@dataclass(frozen=True)
class Tenant:
    id: int
    name: str


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """A connection to the test database, with an empty usage log."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE usage_log"))
    yield engine
    await engine.dispose()


async def create_tenant(engine: AsyncEngine, prefix: str) -> Tenant:
    new_key = await create_api_key(engine, f"{prefix}-{uuid4().hex[:8]}")
    return Tenant(new_key.owner.tenant_id, new_key.owner.tenant_name)


@pytest.fixture
async def acme(engine: AsyncEngine) -> Tenant:
    return await create_tenant(engine, "acme")


@pytest.fixture
async def globex(engine: AsyncEngine) -> Tenant:
    return await create_tenant(engine, "globex")


def usage_row(
    request_id: str, created_at: dt.datetime, tenant: Tenant, outcome: str, **columns: Any
) -> dict[str, Any]:
    """One usage log row. Columns not given take the value of a skipped target."""
    return {
        "request_id": request_id,
        "created_at": created_at,
        "tenant_id": tenant.id,
        "api_key_id": None,
        "alias": "chat-fast",
        "provider": "groq",
        "model": GROQ_MODEL,
        "attempt_index": 0,
        "outcome": outcome,
        "status_code": None,
        "latency_ms": None,
        "first_token_ms": None,
        "prompt_chars": 1200,
        "estimated_tokens": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "degraded": False,
        "stream": False,
        "error_message": None,
        "cache": None,
        "cache_similarity": None,
        "cost_usd": None,
        "saved_cost_usd": None,
        **columns,
    }


async def seed(engine: AsyncEngine, rows: list[dict[str, Any]]) -> None:
    async with engine.begin() as connection:
        await connection.execute(insert(UsageLogRow).values(rows))


@pytest.fixture
def settings(write_config: WriteConfig) -> Settings:
    return write_config(MINIMAL_CONFIG)


@pytest.fixture
async def client(settings: Settings, database_url: str) -> AsyncIterator[AsyncClient]:
    """A client of the admin API that sends a valid session token."""
    async with admin_client(settings, await new_session(database_url)) as client:
        yield client


@pytest.fixture
async def mixed_requests(engine: AsyncEngine, acme: Tenant, globex: Tenant) -> None:
    """One request of every kind in the last 24 h, and two older ones."""
    failover = "failover"
    await seed(
        engine,
        [
            # Answered by the third target: a 429, then a skipped target.
            usage_row(
                failover,
                NOW - dt.timedelta(hours=1),
                acme,
                "rate_limited",
                status_code=429,
                latency_ms=120,
                estimated_tokens=600,
                stream=True,
                error_message="groq/llama-3.3-70b-versatile: rate limited",
            ),
            usage_row(
                failover,
                NOW - dt.timedelta(hours=1),
                acme,
                "skipped_cooldown",
                provider="gemini",
                model=GEMINI_MODEL,
                attempt_index=1,
                estimated_tokens=600,
                stream=True,
                error_message="cooldown",
            ),
            usage_row(
                failover,
                NOW - dt.timedelta(hours=1),
                acme,
                "success",
                provider="ollama",
                model=OLLAMA_MODEL,
                attempt_index=2,
                status_code=200,
                latency_ms=900,
                first_token_ms=150,
                estimated_tokens=600,
                prompt_tokens=400,
                completion_tokens=200,
                stream=True,
                degraded=True,
                cost_usd=Decimal("0.0035"),
            ),
            # Answered from the response cache.
            usage_row(
                "cache-hit",
                NOW - dt.timedelta(hours=2),
                acme,
                "cache_hit",
                alias="chat-cached",
                status_code=200,
                latency_ms=12,
                prompt_tokens=400,
                completion_tokens=200,
                cache="hit",
                cache_similarity=0.97,
                cost_usd=Decimal(0),
                saved_cost_usd=Decimal("0.0035"),
            ),
            # Refused by the tenant quota: no target examined.
            usage_row(
                "rejected",
                NOW - dt.timedelta(hours=3),
                globex,
                "rejected_tenant_quota",
                provider=None,
                model=None,
                status_code=429,
                error_message="tenant requests per minute exceeded",
            ),
            # Every target failed.
            usage_row(
                "failed",
                NOW - dt.timedelta(hours=4),
                globex,
                "timeout",
                alias="chat-cached",
                latency_ms=30000,
                cache="miss",
            ),
            usage_row(
                "failed",
                NOW - dt.timedelta(hours=4),
                globex,
                "unavailable",
                alias="chat-cached",
                provider="gemini",
                model=GEMINI_MODEL,
                attempt_index=1,
                status_code=503,
                latency_ms=40,
                cache="miss",
            ),
            # The client left while the answer streamed.
            usage_row(
                "cancelled",
                NOW - dt.timedelta(hours=5),
                acme,
                "cancelled",
                latency_ms=500,
                first_token_ms=100,
                stream=True,
            ),
            # The provider refused the request itself.
            usage_row(
                "client-error",
                NOW - dt.timedelta(hours=6),
                globex,
                "invalid_request",
                status_code=400,
                latency_ms=30,
            ),
            # Outside the last 24 h.
            usage_row(
                "yesterday",
                NOW - dt.timedelta(hours=25),
                acme,
                "success",
                status_code=200,
                latency_ms=100,
            ),
            usage_row(
                "last-week",
                NOW - dt.timedelta(days=8),
                acme,
                "success",
                status_code=200,
                latency_ms=100,
            ),
        ],
    )


def summary(request_id: str, hours_ago: float, tenant: Tenant, **fields: Any) -> dict[str, Any]:
    """The expected list item of a request. Fields not given take the most common value."""
    return {
        "request_id": request_id,
        "created_at": NOW - dt.timedelta(hours=hours_ago),
        "tenant": tenant.name,
        "alias": "chat-fast",
        "provider": None,
        "model": None,
        "attempts": 1,
        "stream": False,
        "cost_usd": None,
        "cache": None,
        **fields,
    }


def items_of(response_body: dict[str, Any]) -> list[dict[str, Any]]:
    """The items of a page, with their `created_at` parsed back to a datetime."""
    return [
        {**item, "created_at": dt.datetime.fromisoformat(item["created_at"])}
        for item in response_body["items"]
    ]


def ids_of(response_body: dict[str, Any]) -> list[str]:
    return [item["request_id"] for item in response_body["items"]]


@pytest.mark.usefixtures("mixed_requests")
async def test_lists_the_requests_of_the_period_newest_first(
    client: AsyncClient, acme: Tenant, globex: Tenant
) -> None:
    response = await client.get("/admin/v1/requests", params={"period": "24h"})

    assert response.status_code == 200
    assert response.json()["next_cursor"] is None
    assert items_of(response.json()) == [
        summary(
            "failover",
            1,
            acme,
            status="answered",
            status_code=200,
            provider="ollama",
            model=OLLAMA_MODEL,
            attempts=3,
            stream=True,
            latency_ms=1020,
            cost_usd=0.0035,
        ),
        summary(
            "cache-hit",
            2,
            acme,
            alias="chat-cached",
            status="answered",
            status_code=200,
            provider="groq",
            model=GROQ_MODEL,
            latency_ms=12,
            cost_usd=0.0,
            cache="hit",
        ),
        summary("rejected", 3, globex, status="client_error", status_code=429, latency_ms=None),
        summary(
            "failed",
            4,
            globex,
            alias="chat-cached",
            status="failed",
            status_code=503,
            attempts=2,
            latency_ms=30040,
            cache="miss",
        ),
        summary(
            "cancelled",
            5,
            acme,
            status="cancelled",
            status_code=None,
            stream=True,
            latency_ms=500,
        ),
        summary("client-error", 6, globex, status="client_error", status_code=400, latency_ms=30),
    ]


@pytest.mark.usefixtures("mixed_requests")
async def test_dates_are_in_utc(client: AsyncClient) -> None:
    response = await client.get("/admin/v1/requests")

    created_at = dt.datetime.fromisoformat(response.json()["items"][0]["created_at"])
    assert created_at.utcoffset() == dt.timedelta(0)


@pytest.mark.usefixtures("mixed_requests")
@pytest.mark.parametrize(
    ("period", "expected_ids"),
    [
        (None, LAST_24_HOURS),
        ("7d", [*LAST_24_HOURS, "yesterday"]),
        ("30d", [*LAST_24_HOURS, "yesterday", "last-week"]),
    ],
    ids=["default-24h", "7d", "30d"],
)
async def test_period_selects_the_requests(
    client: AsyncClient, period: str | None, expected_ids: list[str]
) -> None:
    params = {} if period is None else {"period": period}

    response = await client.get("/admin/v1/requests", params=params)

    assert ids_of(response.json()) == expected_ids


@pytest.mark.usefixtures("mixed_requests")
@pytest.mark.parametrize(
    ("status", "expected_ids"),
    [
        ("answered", ["failover", "cache-hit"]),
        ("failed", ["failed"]),
        ("client_error", ["rejected", "client-error"]),
        ("cancelled", ["cancelled"]),
    ],
)
async def test_filters_by_status(client: AsyncClient, status: str, expected_ids: list[str]) -> None:
    response = await client.get("/admin/v1/requests", params={"status": status})

    assert ids_of(response.json()) == expected_ids
    assert {item["status"] for item in response.json()["items"]} == {status}


@pytest.mark.usefixtures("mixed_requests")
async def test_filters_by_tenant_and_alias(
    client: AsyncClient, acme: Tenant, globex: Tenant
) -> None:
    by_tenant = await client.get("/admin/v1/requests", params={"tenant": acme.name})
    by_alias = await client.get("/admin/v1/requests", params={"alias": "chat-cached"})
    both = await client.get(
        "/admin/v1/requests",
        params={"tenant": globex.name, "alias": "chat-cached", "status": "failed"},
    )

    assert ids_of(by_tenant.json()) == ["failover", "cache-hit", "cancelled"]
    assert ids_of(by_alias.json()) == ["cache-hit", "failed"]
    assert ids_of(both.json()) == ["failed"]


@pytest.mark.usefixtures("mixed_requests")
async def test_unknown_tenant_or_alias_gives_an_empty_list(client: AsyncClient) -> None:
    unknown_tenant = await client.get("/admin/v1/requests", params={"tenant": "nobody"})
    unknown_alias = await client.get("/admin/v1/requests", params={"alias": "no-such-alias"})

    assert unknown_tenant.status_code == 200
    assert unknown_tenant.json() == {"items": [], "next_cursor": None}
    assert unknown_alias.json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    ("query", "param"),
    [
        ({"period": "1y"}, "period"),
        ({"status": "lost"}, "status"),
    ],
)
async def test_invalid_filters_are_refused(
    client: AsyncClient, query: dict[str, str], param: str
) -> None:
    response = await client.get("/admin/v1/requests", params=query)

    assert response.status_code == 400
    assert response.json()["error"]["param"] == param


# Outcomes of the rows of one request, covering every rule of `request_status.py`.
CLASSIFICATION_CASES = [
    ["success"],
    ["rate_limited", "skipped_cooldown", "success"],
    ["cache_hit"],
    ["cancelled"],
    ["unavailable", "cancelled"],
    ["invalid_request"],
    ["rejected_tenant_quota"],
    ["context_too_large", "context_too_large"],
    ["context_too_large", "rate_limited"],
    ["rate_limited", "unavailable", "timeout"],
    ["skipped_quota", "skipped_breaker"],
    ["interrupted"],
]


async def test_status_matches_the_classification_of_request_status(
    client: AsyncClient, engine: AsyncEngine, acme: Tenant
) -> None:
    # The list classifies requests in SQL, to filter and page on their status:
    # it must agree with `request_status()`.
    await seed(
        engine,
        [
            usage_row(
                f"case-{number:02}",
                NOW - dt.timedelta(minutes=number),
                acme,
                outcome,
                attempt_index=index,
            )
            for number, outcomes in enumerate(CLASSIFICATION_CASES)
            for index, outcome in enumerate(outcomes)
        ],
    )

    response = await client.get("/admin/v1/requests")

    statuses = {item["request_id"]: item["status"] for item in response.json()["items"]}
    assert statuses == {
        f"case-{number:02}": str(request_status(outcomes))
        for number, outcomes in enumerate(CLASSIFICATION_CASES)
    }


async def test_pages_follow_each_other_without_duplicates_or_gaps(
    client: AsyncClient, engine: AsyncEngine, acme: Tenant
) -> None:
    # 120 requests, three per timestamp: pages must split groups of equal timestamps.
    created = {f"req-{number:03}": NOW - dt.timedelta(minutes=number // 3) for number in range(120)}
    await seed(
        engine,
        [
            usage_row(request_id, created_at, acme, "success", status_code=200)
            for request_id, created_at in created.items()
        ],
    )
    newest_first = sorted(created, key=lambda request_id: (created[request_id], request_id))[::-1]

    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params = {} if cursor is None else {"cursor": cursor}
        response = await client.get("/admin/v1/requests", params=params)
        assert response.status_code == 200
        pages.append(response.json())
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break

    assert [len(page["items"]) for page in pages] == [50, 50, 20]
    assert [request_id for page in pages for request_id in ids_of(page)] == newest_first


async def test_cursor_keeps_the_filters(
    client: AsyncClient, engine: AsyncEngine, acme: Tenant
) -> None:
    # 60 answered requests between 60 failed ones, all at the same time.
    await seed(
        engine,
        [
            usage_row(
                f"req-{number:03}",
                NOW - dt.timedelta(minutes=1),
                acme,
                "success" if number % 2 else "unavailable",
            )
            for number in range(120)
        ],
    )

    first = await client.get("/admin/v1/requests", params={"status": "answered"})
    second = await client.get(
        "/admin/v1/requests",
        params={"status": "answered", "cursor": first.json()["next_cursor"]},
    )

    answered = [f"req-{number:03}" for number in range(119, 0, -2)]
    assert ids_of(first.json()) == answered[:50]
    assert ids_of(second.json()) == answered[50:]
    assert second.json()["next_cursor"] is None


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


@pytest.mark.parametrize(
    "cursor",
    [
        "not a cursor!",
        encoded("no separator"),
        encoded("yesterday req-001"),
        encoded("2026-10-23T10:00:00 req-001"),  # no time zone
        encoded("2026-10-23T10:00:00+00:00 "),  # no request id
        "",
    ],
    ids=["not-base64", "no-separator", "bad-date", "naive-date", "no-request-id", "empty"],
)
async def test_invalid_cursor_is_refused(client: AsyncClient, cursor: str) -> None:
    response = await client.get("/admin/v1/requests", params={"cursor": cursor})

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "message": "Invalid cursor: pass the next_cursor of a previous page.",
            "type": "invalid_request_error",
            "param": "cursor",
            "code": "invalid_cursor",
        }
    }


@pytest.mark.usefixtures("mixed_requests")
async def test_request_shows_its_routing_path(client: AsyncClient, acme: Tenant) -> None:
    response = await client.get("/admin/v1/requests/failover")

    assert response.status_code == 200
    body = response.json()
    routing_path = body.pop("routing_path")
    assert items_of({"items": [body]}) == [
        summary(
            "failover",
            1,
            acme,
            status="answered",
            status_code=200,
            provider="ollama",
            model=OLLAMA_MODEL,
            attempts=3,
            stream=True,
            latency_ms=1020,
            cost_usd=0.0035,
        )
    ]
    skipped = {
        "status_code": None,
        "latency_ms": None,
        "first_token_ms": None,
        "estimated_tokens": 600,
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
        "saved_cost_usd": None,
        "degraded": False,
        "cache": None,
        "cache_similarity": None,
    }
    assert routing_path == [
        {
            **skipped,
            "attempt_index": 0,
            "provider": "groq",
            "model": GROQ_MODEL,
            "outcome": "rate_limited",
            "status_code": 429,
            "latency_ms": 120,
            "error_message": "groq/llama-3.3-70b-versatile: rate limited",
        },
        {
            **skipped,
            "attempt_index": 1,
            "provider": "gemini",
            "model": GEMINI_MODEL,
            "outcome": "skipped_cooldown",
            "error_message": "cooldown",
        },
        {
            **skipped,
            "attempt_index": 2,
            "provider": "ollama",
            "model": OLLAMA_MODEL,
            "outcome": "success",
            "status_code": 200,
            "latency_ms": 900,
            "first_token_ms": 150,
            "prompt_tokens": 400,
            "completion_tokens": 200,
            "cost_usd": 0.0035,
            "degraded": True,
            "error_message": None,
        },
    ]


@pytest.mark.usefixtures("mixed_requests")
async def test_cache_hit_shows_the_cost_it_saved(client: AsyncClient) -> None:
    response = await client.get("/admin/v1/requests/cache-hit")

    assert response.json()["cache"] == "hit"
    assert response.json()["routing_path"] == [
        {
            "attempt_index": 0,
            "provider": "groq",
            "model": GROQ_MODEL,
            "outcome": "cache_hit",
            "status_code": 200,
            "latency_ms": 12,
            "first_token_ms": None,
            "estimated_tokens": None,
            "prompt_tokens": 400,
            "completion_tokens": 200,
            "cost_usd": 0.0,
            "saved_cost_usd": 0.0035,
            "degraded": False,
            "cache": "hit",
            "cache_similarity": 0.97,
            "error_message": None,
        }
    ]


@pytest.mark.usefixtures("mixed_requests")
async def test_tenant_quota_refusal_has_no_provider(client: AsyncClient) -> None:
    response = await client.get("/admin/v1/requests/rejected")

    assert response.json()["status"] == "client_error"
    [refusal] = response.json()["routing_path"]
    assert refusal["outcome"] == "rejected_tenant_quota"
    assert (refusal["provider"], refusal["model"], refusal["status_code"]) == (None, None, 429)


@pytest.mark.usefixtures("mixed_requests")
async def test_request_older_than_the_periods_is_still_found(client: AsyncClient) -> None:
    response = await client.get("/admin/v1/requests/last-week")

    assert response.status_code == 200
    assert response.json()["request_id"] == "last-week"


@pytest.mark.usefixtures("mixed_requests")
async def test_unknown_request_is_not_found(client: AsyncClient) -> None:
    response = await client.get("/admin/v1/requests/no-such-request")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "message": "No request with this id.",
            "type": "invalid_request_error",
            "param": "request_id",
            "code": "request_not_found",
        }
    }


@pytest.mark.parametrize("path", ["/admin/v1/requests", "/admin/v1/requests/failover"])
async def test_requests_need_a_session(settings: Settings, path: str) -> None:
    async with admin_client(settings, None) as client:
        response = await client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


@pytest.mark.parametrize("path", ["/admin/v1/requests", "/admin/v1/requests/failover"])
async def test_requests_answer_503_when_postgresql_is_down(
    settings: Settings, database_url: str, database_proxy: DatabaseProxy, path: str
) -> None:
    proxied = settings.model_copy(
        update={"database_url": database_proxy.url, "database_timeout": 0.5}
    )
    session_token = await new_session(database_url)

    async with asyncio.timeout(10), admin_client(proxied, session_token) as client:
        first = await client.get("/admin/v1/me")
        await database_proxy.stop()
        response = await client.get(path)

    assert first.status_code == 200
    # Sessions are checked in PostgreSQL on every request: the check fails first.
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"
