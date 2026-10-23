"""Tests for the statistics of the admin API: the overview and the per-tenant table.

Every test seeds `usage_log` rows directly, then checks the exact numbers the
admin API computes from them.
"""

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.storage.tenants import create_api_key
from app.storage.usage import UsageLogRow
from tests.conftest import MINIMAL_CONFIG, DatabaseProxy, FetchUsageRows
from tests.test_admin_api import admin_client, new_session

WriteConfig = Callable[[str], Settings]
HOUR = dt.timedelta(hours=1)
DAY = dt.timedelta(days=1)


@pytest.fixture
def settings(write_config: WriteConfig) -> Settings:
    return write_config(MINIMAL_CONFIG)


@pytest.fixture
async def session_token(database_url: str, usage_rows: FetchUsageRows) -> str:
    """A session token of an operator, with an empty usage log."""
    return await new_session(database_url)


async def new_tenant(database_url: str, name: str) -> tuple[int, int]:
    """Create a tenant with one API key. Returns (tenant id, API key id)."""
    engine = create_async_engine(database_url)
    try:
        new_key = await create_api_key(engine, f"{name}-{uuid4().hex[:8]}")
    finally:
        await engine.dispose()
    return new_key.owner.tenant_id, new_key.owner.api_key_id


async def tenant_name(database_url: str, tenant: tuple[int, int]) -> str:
    """The name of a tenant created by `new_tenant`."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.exec_driver_sql(
                "SELECT name FROM tenants WHERE id = $1", (tenant[0],)
            )
            return str(result.scalar_one())
    finally:
        await engine.dispose()


def row(
    request_id: str,
    outcome: str,
    at: dt.datetime,
    tenant: tuple[int, int] | None,
    *,
    attempt_index: int = 0,
    **columns: Any,
) -> dict[str, Any]:
    """One usage row. Unset columns keep the values of a row without tokens or cost."""
    tenant_id, api_key_id = tenant or (None, None)
    return {
        "request_id": request_id,
        "created_at": at,
        "tenant_id": tenant_id,
        "api_key_id": api_key_id,
        "alias": "chat-fast",
        "provider": None if outcome == "rejected_tenant_quota" else "groq",
        "model": None if outcome == "rejected_tenant_quota" else "openai/gpt-oss-20b",
        "attempt_index": attempt_index,
        "outcome": outcome,
        "prompt_chars": 40,
        **columns,
    }


async def insert_rows(database_url: str, rows: list[dict[str, Any]]) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for each in rows:  # one INSERT per row: rows do not all set the same columns
                await connection.execute(insert(UsageLogRow).values(each))
    finally:
        await engine.dispose()


def usd(value: str) -> Decimal:
    return Decimal(value)


async def seed_two_tenants(
    database_url: str, now: dt.datetime
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Seed requests of every status for tenants alpha and beta; gamma has none.

    Returns the three tenants. In the last 24 h:

    | request | tenant | rows (attempt order)                      | status       |
    |---------|--------|-------------------------------------------|--------------|
    | a1      | alpha  | success                                   | answered     |
    | a2      | alpha  | rate_limited, skipped_cooldown, success   | answered     |
    | a3      | alpha  | success (stream, unpriced)                | answered     |
    | a4      | alpha  | cache_hit                                 | answered     |
    | a5      | alpha  | success (cache miss)                      | answered     |
    | a6      | alpha  | unavailable, timeout                      | failed       |
    | a7      | alpha  | invalid_request                           | client_error |
    | a8      | alpha  | rejected_tenant_quota                     | client_error |
    | a9      | alpha  | cancelled (stream)                        | cancelled    |
    | b1      | beta   | unavailable, success (stream)             | answered     |
    | b2      | beta   | interrupted (stream)                      | failed       |
    | b3      | beta   | context_too_large, context_too_large      | client_error |

    a0 (alpha, answered) is 25 h old: outside 24 h, inside 7 days.
    """
    alpha = await new_tenant(database_url, "alpha")
    beta = await new_tenant(database_url, "beta")
    gamma = await new_tenant(database_url, "gamma")
    rows = [
        row("a0", "success", now - 25 * HOUR, alpha, latency_ms=100,
            prompt_tokens=1, completion_tokens=1, cost_usd=usd("0.0002")),
        row("a1", "success", now - 1 * HOUR, alpha, latency_ms=100,
            prompt_tokens=10, completion_tokens=20, cost_usd=usd("0.001")),
        row("a2", "rate_limited", now - 2 * HOUR, alpha, latency_ms=50, status_code=429),
        row("a2", "skipped_cooldown", now - 2 * HOUR, alpha, attempt_index=1),
        row("a2", "success", now - 2 * HOUR, alpha, attempt_index=2, latency_ms=200,
            prompt_tokens=30, completion_tokens=40, cost_usd=usd("0.002")),
        row("a3", "success", now - 3 * HOUR, alpha, latency_ms=400, stream=True,
            first_token_ms=80, prompt_tokens=5, completion_tokens=5),
        row("a4", "cache_hit", now - 4 * HOUR, alpha, latency_ms=7, cache="hit",
            cache_similarity=1.0, prompt_tokens=10, completion_tokens=20,
            cost_usd=usd("0"), saved_cost_usd=usd("0.001")),
        row("a5", "success", now - 5 * HOUR, alpha, latency_ms=300, cache="miss",
            prompt_tokens=1, completion_tokens=2, cost_usd=usd("0.0005")),
        row("a6", "unavailable", now - 6 * HOUR, alpha, latency_ms=30, status_code=502),
        row("a6", "timeout", now - 6 * HOUR, alpha, attempt_index=1, latency_ms=1000),
        row("a7", "invalid_request", now - 7 * HOUR, alpha, latency_ms=20, status_code=400),
        row("a8", "rejected_tenant_quota", now - 8 * HOUR, alpha, status_code=429),
        row("a9", "cancelled", now - 9 * HOUR, alpha, latency_ms=90, stream=True),
        row("b1", "unavailable", now - 10 * HOUR, beta, latency_ms=40, stream=True),
        row("b1", "success", now - 10 * HOUR, beta, attempt_index=1, latency_ms=160,
            stream=True, first_token_ms=120, prompt_tokens=100, completion_tokens=200,
            cost_usd=usd("0.01")),
        row("b2", "interrupted", now - 11 * HOUR, beta, latency_ms=500, stream=True,
            prompt_tokens=3, completion_tokens=4, cost_usd=usd("0.0001")),
        row("b3", "context_too_large", now - 12 * HOUR, beta),
        row("b3", "context_too_large", now - 12 * HOUR, beta, attempt_index=1),
    ]  # fmt: skip
    await insert_rows(database_url, rows)
    return alpha, beta, gamma


def hour_start(moment: dt.datetime) -> dt.datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def day_start(moment: dt.datetime) -> dt.datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_time(value: str) -> dt.datetime:
    moment = dt.datetime.fromisoformat(value)
    assert moment.utcoffset() == dt.timedelta(0), f"{value} is not in UTC"
    return moment


def series_by_start(body: dict[str, Any]) -> dict[dt.datetime, dict[str, Any]]:
    return {parse_time(point.pop("start")): point for point in body["series"]}


def empty_point() -> dict[str, Any]:
    return {"requests": 0, "answered": 0, "failed": 0, "cost_usd": 0.0, "cache_hits": 0}


async def test_overview_of_the_last_24_hours(
    settings: Settings, database_url: str, session_token: str
) -> None:
    now = dt.datetime.now(dt.UTC)
    await seed_two_tenants(database_url, now)

    async with admin_client(settings, session_token) as client:
        response = await client.get("/admin/v1/overview", params={"period": "24h"})

    assert response.status_code == 200
    body = response.json()
    series = series_by_start(body)
    del body["series"]
    end = parse_time(body.pop("end"))
    assert parse_time(body.pop("start")) == end - 24 * HOUR
    latency, first_token = body.pop("latency_ms"), body.pop("time_to_first_token_ms")
    assert body == {
        "period": "24h",
        "tenant": None,
        "requests": 12,
        "answered": 6,
        "failed": 2,
        "client_error": 3,
        "cancelled": 1,
        "error_rate": 2 / 12,
        # Answered without the cache: a1, a2, a3, a5, b1. Answered by a fallback: a2, b1.
        "fallback_rate": 2 / 5,
        "cache_hit_latency_ms": {"p50": 7.0},
        # Success rows only: a1 30, a2 70, a3 10, a5 3, b1 300.
        "tokens": 413,
        # Every row: a1, a2, a3 (unpriced), a4 (0), a5, b1, b2 (interrupted).
        "cost_usd": 0.0136,
        "unpriced_requests": 1,
        "cache_requests": 2,
        "cache_hits": 1,
        "cache_hit_rate": 0.5,
        "saved_tokens": 30,
        "saved_cost_usd": 0.001,
    }
    # Request latencies (sum of their rows): 100, 250, 400, 300, 200.
    assert latency == {"p50": 250.0, "p95": pytest.approx(380.0)}
    # Streams answered: a3 80, b1 120.
    assert first_token == {"p50": 100.0, "p95": pytest.approx(118.0)}

    # One point per hour, from the hour of the period start to the current hour.
    first_hour = hour_start(end - 24 * HOUR)
    assert list(series) == [first_hour + index * HOUR for index in range(25)]
    expected = {hour: empty_point() for hour in series}
    for hours_ago, answered, failed, cost, cache_hits in [
        (1, 1, 0, 0.001, 0),
        (2, 1, 0, 0.002, 0),
        (3, 1, 0, 0.0, 0),
        (4, 1, 0, 0.0, 1),
        (5, 1, 0, 0.0005, 0),
        (6, 0, 1, 0.0, 0),
        (7, 0, 0, 0.0, 0),
        (8, 0, 0, 0.0, 0),
        (9, 0, 0, 0.0, 0),
        (10, 1, 0, 0.01, 0),
        (11, 0, 1, 0.0001, 0),
        (12, 0, 0, 0.0, 0),
    ]:
        expected[hour_start(now - hours_ago * HOUR)] = {
            "requests": 1,
            "answered": answered,
            "failed": failed,
            "cost_usd": cost,
            "cache_hits": cache_hits,
        }
    assert series == expected


async def test_overview_of_one_tenant(
    settings: Settings, database_url: str, session_token: str
) -> None:
    now = dt.datetime.now(dt.UTC)
    _, beta, _ = await seed_two_tenants(database_url, now)
    beta_name = await tenant_name(database_url, beta)

    async with admin_client(settings, session_token) as client:
        response = await client.get(
            "/admin/v1/overview", params={"period": "24h", "tenant": beta_name}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant"] == beta_name
    assert {key: body[key] for key in body if key not in {"series", "start", "end"}} == {
        "period": "24h",
        "tenant": beta_name,
        "requests": 3,
        "answered": 1,
        "failed": 1,
        "client_error": 1,
        "cancelled": 0,
        "error_rate": 1 / 3,
        "fallback_rate": 1.0,
        "latency_ms": {"p50": 200.0, "p95": 200.0},
        "time_to_first_token_ms": {"p50": 120.0, "p95": 120.0},
        "cache_hit_latency_ms": {"p50": None},
        "tokens": 300,
        "cost_usd": 0.0101,
        "unpriced_requests": 0,
        "cache_requests": 0,
        "cache_hits": 0,
        "cache_hit_rate": 0.0,
        "saved_tokens": 0,
        "saved_cost_usd": 0.0,
    }
    assert sum(point["requests"] for point in body["series"]) == 3


async def test_overview_of_7_days_counts_older_requests_in_utc_days(
    settings: Settings, database_url: str, session_token: str
) -> None:
    now = dt.datetime.now(dt.UTC)
    alpha, _, _ = await seed_two_tenants(database_url, now)
    # Two requests on each side of a UTC midnight, three days ago.
    midnight = day_start(now) - 3 * DAY
    await insert_rows(
        database_url,
        [
            row("late", "success", midnight - dt.timedelta(microseconds=1), alpha),
            row("early", "success", midnight, alpha),
            row("evening", "unavailable", midnight + DAY - dt.timedelta(seconds=1), alpha),
        ],
    )

    async with admin_client(settings, session_token) as client:
        response = await client.get("/admin/v1/overview", params={"period": "7d"})

    assert response.status_code == 200
    body = response.json()
    assert body["requests"] == 12 + 1 + 3  # a0 is 25 h old
    assert body["answered"] == 6 + 1 + 2
    series = series_by_start(body)
    end = parse_time(body["end"])
    first_day = day_start(end - 7 * DAY)
    assert list(series) == [first_day + index * DAY for index in range(8)]
    assert series[midnight - DAY] == {**empty_point(), "requests": 1, "answered": 1}
    assert series[midnight] == {**empty_point(), "requests": 2, "answered": 1, "failed": 1}


async def test_series_of_24_hours_is_cut_at_utc_hours(
    settings: Settings, database_url: str, session_token: str
) -> None:
    now = dt.datetime.now(dt.UTC)
    tenant = await new_tenant(database_url, "hours")
    boundary = hour_start(now) - 5 * HOUR
    await insert_rows(
        database_url,
        [
            row("before", "success", boundary - dt.timedelta(microseconds=1), tenant),
            row("at", "success", boundary, tenant),
            row("after", "cache_hit", boundary + HOUR - dt.timedelta(seconds=1), tenant),
        ],
    )

    async with admin_client(settings, session_token) as client:
        response = await client.get("/admin/v1/overview", params={"period": "24h"})

    series = series_by_start(response.json())
    assert series[boundary - HOUR] == {**empty_point(), "requests": 1, "answered": 1}
    assert series[boundary] == {**empty_point(), "requests": 2, "answered": 2, "cache_hits": 1}


async def test_overview_of_an_empty_period(settings: Settings, session_token: str) -> None:
    async with admin_client(settings, session_token) as client:
        response = await client.get("/admin/v1/overview", params={"period": "30d"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["series"]) == 31
    assert all(
        {key: value for key, value in point.items() if key != "start"} == empty_point()
        for point in body["series"]
    )
    assert {key: body[key] for key in body if key not in {"series", "start", "end"}} == {
        "period": "30d",
        "tenant": None,
        "requests": 0,
        "answered": 0,
        "failed": 0,
        "client_error": 0,
        "cancelled": 0,
        "error_rate": 0.0,
        "fallback_rate": 0.0,
        "latency_ms": {"p50": None, "p95": None},
        "time_to_first_token_ms": {"p50": None, "p95": None},
        "cache_hit_latency_ms": {"p50": None},
        "tokens": 0,
        "cost_usd": 0.0,
        "unpriced_requests": 0,
        "cache_requests": 0,
        "cache_hits": 0,
        "cache_hit_rate": 0.0,
        "saved_tokens": 0,
        "saved_cost_usd": 0.0,
    }


async def test_overview_of_an_unknown_tenant_is_404(settings: Settings, session_token: str) -> None:
    async with admin_client(settings, session_token) as client:
        response = await client.get(
            "/admin/v1/overview", params={"period": "24h", "tenant": "nobody-here"}
        )

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "tenant_not_found"
    assert error["param"] == "tenant"
    assert "nobody-here" in error["message"]


@pytest.mark.parametrize("path", ["/admin/v1/overview", "/admin/v1/tenants"])
async def test_statistics_refuse_an_unknown_period(
    settings: Settings, session_token: str, path: str
) -> None:
    async with admin_client(settings, session_token) as client:
        response = await client.get(path, params={"period": "1y"})

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "period"


@pytest.mark.parametrize("path", ["/admin/v1/overview", "/admin/v1/tenants"])
async def test_statistics_need_a_session(settings: Settings, path: str) -> None:
    async with admin_client(settings, None) as client:
        response = await client.get(path, params={"period": "24h"})

    assert response.status_code == 401


async def test_tenants_of_the_last_24_hours(
    settings: Settings, database_url: str, session_token: str
) -> None:
    now = dt.datetime.now(dt.UTC)
    alpha, beta, gamma = await seed_two_tenants(database_url, now)
    names = {tenant: await tenant_name(database_url, tenant) for tenant in (alpha, beta, gamma)}

    async with admin_client(settings, session_token) as client:
        response = await client.get("/admin/v1/tenants", params={"period": "24h"})

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "24h"
    end = parse_time(body["end"])
    assert parse_time(body["start"]) == end - 24 * HOUR
    tenants = body["tenants"]
    # Every other tenant has no request: alpha and beta come first.
    assert tenants[:2] == [
        {
            "tenant": names[alpha],
            "requests": 9,
            "tokens": 113,
            "cost_usd": 0.0035,
            "unpriced_requests": 1,
            "error_rate": 1 / 9,
            "cache_hits": 1,
            "saved_cost_usd": 0.001,
            "quota_refusals": 1,
        },
        {
            "tenant": names[beta],
            "requests": 3,
            "tokens": 300,
            "cost_usd": 0.0101,
            "unpriced_requests": 0,
            "error_rate": 1 / 3,
            "cache_hits": 0,
            "saved_cost_usd": 0.0,
            "quota_refusals": 0,
        },
    ]
    assert {
        "tenant": names[gamma],
        "requests": 0,
        "tokens": 0,
        "cost_usd": 0.0,
        "unpriced_requests": 0,
        "error_rate": 0.0,
        "cache_hits": 0,
        "saved_cost_usd": 0.0,
        "quota_refusals": 0,
    } in tenants[2:]
    assert all(tenant["requests"] == 0 for tenant in tenants[2:])


async def test_tenants_of_7_days_include_older_requests(
    settings: Settings, database_url: str, session_token: str
) -> None:
    now = dt.datetime.now(dt.UTC)
    alpha, _, _ = await seed_two_tenants(database_url, now)
    alpha_name = await tenant_name(database_url, alpha)

    async with admin_client(settings, session_token) as client:
        response = await client.get("/admin/v1/tenants", params={"period": "7d"})

    [alpha_row] = [each for each in response.json()["tenants"] if each["tenant"] == alpha_name]
    assert alpha_row["requests"] == 10
    assert alpha_row["tokens"] == 115
    assert alpha_row["cost_usd"] == 0.0037


@pytest.mark.parametrize("path", ["/admin/v1/overview", "/admin/v1/tenants"])
async def test_statistics_answer_503_when_the_database_is_down(
    write_config: WriteConfig,
    database_url: str,
    database_proxy: DatabaseProxy,
    session_token: str,
    path: str,
) -> None:
    settings = write_config(MINIMAL_CONFIG).model_copy(update={"database_url": database_proxy.url})

    async with admin_client(settings, session_token) as client:
        assert (await client.get("/admin/v1/me")).status_code == 200
        await database_proxy.stop()
        response = await client.get(path, params={"period": "24h"})

    # Sessions are checked in PostgreSQL on every request: the check fails first.
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"


async def test_usage_log_is_indexed_by_date(database_url: str) -> None:
    # The global statistics filter `usage_log` on a time range only.
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.exec_driver_sql(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_usage_log_created_at'"
            )
            definition = result.scalar_one()
    finally:
        await engine.dispose()
    assert definition.endswith("ON public.usage_log USING btree (created_at)")
