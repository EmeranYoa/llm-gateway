"""Statistics of the admin API: the overview of a period, and the table of tenants.

Every number is exact: PostgreSQL computes it from all the usage rows of the
period. The usage log has one row per examined target, so the queries first
summarise each request from its rows (`_request_summaries`), then aggregate
the requests. A request belongs to the period when it was received in it.
"""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    ColumnElement,
    DateTime,
    Interval,
    Subquery,
    and_,
    cast,
    func,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.admin_api.dependencies import Admin, Database
from app.admin_api.periods import Period
from app.admin_api.request_status import (
    RequestStatus,
    status_expression,
)
from app.api.routes import error_response
from app.routing.router import Outcome
from app.schemas import ErrorBody
from app.storage.tenants import TenantRow, find_tenant_id
from app.storage.usage import CACHE_HIT, REJECTED_TENANT_QUOTA, UsageLogRow

router = APIRouter(prefix="/admin/v1")

PeriodQuery = Annotated[Period, Query(description="How far back the report goes, until now.")]

# --- Response bodies ---


class LatencyPercentiles(BaseModel):
    """Median and 95th percentile of a duration, in milliseconds. Null when nothing was measured."""

    p50: float | None
    p95: float | None


class LatencyMedian(BaseModel):
    """Median of a duration, in milliseconds. Null when nothing was measured."""

    p50: float | None


class SeriesPoint(BaseModel):
    """The requests received in one bucket of the period: one hour (24h) or one UTC day."""

    start: dt.datetime = Field(description="First moment of the bucket (UTC).")
    requests: int
    answered: int
    failed: int
    cost_usd: float
    cache_hits: int


class Overview(BaseModel):
    """Totals of a period, for every tenant or for one, and their time series.

    Each request has one status (see `request_status.py`): answered, failed,
    client_error or cancelled.
    """

    period: Period
    tenant: str | None = Field(description="The tenant reported on, or null for every tenant.")
    start: dt.datetime = Field(description="Start of the period (UTC).")
    end: dt.datetime = Field(description="End of the period: when the report was made (UTC).")
    requests: int = Field(description="Requests received, tenant quota refusals included.")
    answered: int
    failed: int
    client_error: int
    cancelled: int
    error_rate: float = Field(description="failed / requests. 0 when there is no request.")
    fallback_rate: float = Field(
        description="Share of the requests answered by a provider (not from the cache) "
        "whose answer came from a fallback target, not from the first one."
    )
    latency_ms: LatencyPercentiles = Field(
        description="Duration of the requests answered by a provider: all their attempts."
    )
    time_to_first_token_ms: LatencyPercentiles = Field(
        description="Time to the first content of the streamed answers."
    )
    cache_hit_latency_ms: LatencyMedian = Field(description="Duration of the cache hits.")
    tokens: int = Field(description="Prompt and completion tokens of the answers of providers.")
    cost_usd: float = Field(description="Cost of every attempt that has a price.")
    unpriced_requests: int = Field(
        description="Requests answered by a provider whose answer has no cost: "
        "the model has no price, or the provider sent no token counts."
    )
    cache_requests: int = Field(description="Requests to an alias that uses the cache.")
    cache_hits: int
    cache_hit_rate: float = Field(
        description="cache_hits / cache_requests. 0 when no request used the cache."
    )
    saved_tokens: int = Field(description="Tokens the cache hits did not spend.")
    saved_cost_usd: float = Field(description="What the cache hits would have cost.")
    series: list[SeriesPoint] = Field(
        description="One point per bucket of the period, oldest first, empty buckets included."
    )


class TenantStatistics(BaseModel):
    """What one tenant did in the period."""

    tenant: str = Field(description="Name of the tenant.")
    requests: int = Field(description="Requests received, tenant quota refusals included.")
    tokens: int = Field(description="Prompt and completion tokens of the answers of providers.")
    cost_usd: float
    error_rate: float = Field(description="failed / requests. 0 when there is no request.")
    cache_hits: int
    saved_cost_usd: float = Field(description="What the cache hits would have cost.")
    quota_refusals: int = Field(description="Requests refused by the tenant's own quota.")


class TenantStatisticsList(BaseModel):
    """Every tenant, even without any request in the period, most requests first."""

    period: Period
    start: dt.datetime = Field(description="Start of the period (UTC).")
    end: dt.datetime = Field(description="End of the period: when the report was made (UTC).")
    tenants: list[TenantStatistics]


# --- Routes ---


@router.get(
    "/overview",
    response_model=Overview,
    responses={404: {"model": ErrorBody, "description": "Unknown tenant."}},
)
async def overview(
    _: Admin,
    database: Database,
    period: PeriodQuery = Period.DAY,
    tenant: Annotated[str | None, Query(description="Name of a tenant. All when omitted.")] = None,
) -> Overview | JSONResponse:
    """Totals and time series of a period, for every tenant or for one."""
    end = dt.datetime.now(dt.UTC)
    start = period.start(end)
    tenant_id = None
    if tenant is not None:
        tenant_id = await find_tenant_id(database, tenant)
        if tenant_id is None:
            return error_response(
                404,
                f"Unknown tenant '{tenant}'.",
                "invalid_request_error",
                param="tenant",
                code="tenant_not_found",
            )
    requests = _request_summaries(start, end, tenant_id)
    async with database.connect() as connection:
        totals = await _totals(connection, requests)
        series = await _series(connection, requests, period, start, end)
    return Overview(period=period, tenant=tenant, start=start, end=end, **totals, series=series)


@router.get("/tenants")
async def tenants(
    _: Admin, database: Database, period: PeriodQuery = Period.DAY
) -> TenantStatisticsList:
    """One row per tenant for the period, most requests first."""
    end = dt.datetime.now(dt.UTC)
    start = period.start(end)
    requests = _request_summaries(start, end)
    per_tenant = (
        select(
            requests.c.tenant_id,
            func.count().label("requests"),
            func.sum(requests.c.tokens).label("tokens"),
            func.sum(requests.c.cost_usd).label("cost_usd"),
            func.count().filter(requests.c.status == RequestStatus.FAILED).label("failed"),
            func.count().filter(requests.c.cache_hit).label("cache_hits"),
            func.sum(requests.c.saved_cost_usd).label("saved_cost_usd"),
            func.count().filter(requests.c.quota_refused).label("quota_refusals"),
        )
        .group_by(requests.c.tenant_id)
        .subquery()
    )
    query = (
        select(TenantRow.name, per_tenant)
        .outerjoin(per_tenant, per_tenant.c.tenant_id == TenantRow.id)
        .order_by(func.coalesce(per_tenant.c.requests, 0).desc(), TenantRow.name)
    )
    async with database.connect() as connection:
        rows = (await connection.execute(query)).mappings().all()
    return TenantStatisticsList(
        period=period,
        start=start,
        end=end,
        tenants=[
            TenantStatistics(
                tenant=row["name"],
                requests=row["requests"] or 0,
                tokens=int(row["tokens"] or 0),
                cost_usd=_usd(row["cost_usd"]),
                error_rate=_share(row["failed"], row["requests"]),
                cache_hits=row["cache_hits"] or 0,
                saved_cost_usd=_usd(row["saved_cost_usd"]),
                quota_refusals=row["quota_refusals"] or 0,
            )
            for row in rows
        ],
    )


# --- Queries ---


def _request_summaries(
    start: dt.datetime, end: dt.datetime, tenant_id: int | None = None
) -> Subquery:
    """One row per request received in [start, end], summarising all its usage rows.

    Every row of a request has the same `created_at` and `tenant_id`. A request
    has at most one `success` row (the answer of a provider) or one `cache_hit` row.
    """
    log = UsageLogRow
    answer_row = log.outcome == Outcome.SUCCESS
    cache_hit_row = log.outcome == CACHE_HIT
    row_tokens = func.coalesce(log.prompt_tokens, 0) + func.coalesce(log.completion_tokens, 0)
    query = (
        select(
            log.request_id,
            func.min(log.created_at).label("created_at"),
            func.min(log.tenant_id).label("tenant_id"),
            status_expression().label("status"),
            func.bool_or(cache_hit_row).label("cache_hit"),
            func.bool_or(log.cache.is_not(None)).label("uses_cache"),
            func.bool_or(log.outcome == REJECTED_TENANT_QUOTA).label("quota_refused"),
            func.max(log.attempt_index).filter(answer_row).label("answer_index"),
            func.sum(log.latency_ms).label("latency_ms"),
            func.max(log.first_token_ms).filter(answer_row & log.stream).label("first_token_ms"),
            func.bool_or(answer_row & log.cost_usd.is_(None)).label("unpriced"),
            func.coalesce(func.sum(row_tokens).filter(answer_row), 0).label("tokens"),
            func.coalesce(func.sum(row_tokens).filter(cache_hit_row), 0).label("saved_tokens"),
            func.sum(log.cost_usd).label("cost_usd"),
            func.sum(log.saved_cost_usd).label("saved_cost_usd"),
        )
        .where(log.created_at >= start, log.created_at <= end)
        .group_by(log.request_id)
    )
    if tenant_id is not None:
        query = query.where(log.tenant_id == tenant_id)
    return query.subquery("requests")


async def _totals(connection: AsyncConnection, requests: Subquery) -> dict[str, Any]:
    """The totals of the overview, by field name."""
    r = requests.c
    answered = r.status == RequestStatus.ANSWERED
    by_provider = and_(answered, ~r.cache_hit)  # answered by a provider, not from the cache
    query = select(
        func.count().label("requests"),
        *(func.count().filter(r.status == status).label(status) for status in RequestStatus),
        func.count().filter(by_provider).label("provider_answers"),
        func.count().filter(by_provider, r.answer_index > 0).label("fallback_answers"),
        _percentile(0.5, r.latency_ms, by_provider).label("latency_p50"),
        _percentile(0.95, r.latency_ms, by_provider).label("latency_p95"),
        # Only streamed answers have a first token time: other requests have NULL.
        _percentile(0.5, r.first_token_ms).label("first_token_p50"),
        _percentile(0.95, r.first_token_ms).label("first_token_p95"),
        _percentile(0.5, r.latency_ms, r.cache_hit).label("cache_hit_p50"),
        func.sum(r.tokens).label("tokens"),
        func.sum(r.cost_usd).label("cost_usd"),
        func.count().filter(r.unpriced).label("unpriced_requests"),
        func.count().filter(r.uses_cache).label("cache_requests"),
        func.count().filter(r.cache_hit).label("cache_hits"),
        func.sum(r.saved_tokens).label("saved_tokens"),
        func.sum(r.saved_cost_usd).label("saved_cost_usd"),
    )
    row = (await connection.execute(query)).mappings().one()
    return {
        "requests": row["requests"],
        **{status.value: row[status.value] for status in RequestStatus},
        "error_rate": _share(row[RequestStatus.FAILED], row["requests"]),
        "fallback_rate": _share(row["fallback_answers"], row["provider_answers"]),
        "latency_ms": LatencyPercentiles(p50=row["latency_p50"], p95=row["latency_p95"]),
        "time_to_first_token_ms": LatencyPercentiles(
            p50=row["first_token_p50"], p95=row["first_token_p95"]
        ),
        "cache_hit_latency_ms": LatencyMedian(p50=row["cache_hit_p50"]),
        "tokens": int(row["tokens"] or 0),
        "cost_usd": _usd(row["cost_usd"]),
        "unpriced_requests": row["unpriced_requests"],
        "cache_requests": row["cache_requests"],
        "cache_hits": row["cache_hits"],
        "cache_hit_rate": _share(row["cache_hits"], row["cache_requests"]),
        "saved_tokens": int(row["saved_tokens"] or 0),
        "saved_cost_usd": _usd(row["saved_cost_usd"]),
    }


async def _series(
    connection: AsyncConnection,
    requests: Subquery,
    period: Period,
    start: dt.datetime,
    end: dt.datetime,
) -> list[SeriesPoint]:
    """One point per bucket from `start` to `end`, empty buckets included.

    Buckets are cut in UTC, whatever the time zone of the database session.
    """
    r = requests.c

    def bucket_of(moment: ColumnElement[dt.datetime]) -> ColumnElement[dt.datetime]:
        """The start of the bucket of `moment`, as a UTC time without time zone."""
        return func.date_trunc(period.bucket, func.timezone("UTC", moment))

    buckets = (
        func.generate_series(
            bucket_of(literal(start, DateTime(timezone=True))),
            bucket_of(literal(end, DateTime(timezone=True))),
            cast(literal(f"1 {period.bucket}"), Interval),
        )
        .table_valued("start")
        .render_derived(name="buckets")
    )
    bucket = bucket_of(r.created_at).label("start")
    per_bucket = (
        select(
            bucket,
            func.count().label("requests"),
            func.count().filter(r.status == RequestStatus.ANSWERED).label("answered"),
            func.count().filter(r.status == RequestStatus.FAILED).label("failed"),
            func.sum(r.cost_usd).label("cost_usd"),
            func.count().filter(r.cache_hit).label("cache_hits"),
        )
        .group_by(bucket)  # by label: the unit is a bound parameter
        .subquery()
    )
    query = (
        select(buckets.c.start, per_bucket.c.requests, per_bucket.c.answered)
        .add_columns(per_bucket.c.failed, per_bucket.c.cost_usd, per_bucket.c.cache_hits)
        .select_from(buckets.outerjoin(per_bucket, per_bucket.c.start == buckets.c.start))
        .order_by(buckets.c.start)
    )
    rows = (await connection.execute(query)).mappings().all()
    return [
        SeriesPoint(
            start=row["start"].replace(tzinfo=dt.UTC),
            requests=row["requests"] or 0,
            answered=row["answered"] or 0,
            failed=row["failed"] or 0,
            cost_usd=_usd(row["cost_usd"]),
            cache_hits=row["cache_hits"] or 0,
        )
        for row in rows
    ]


def _percentile(
    fraction: float, value: ColumnElement[int], *conditions: ColumnElement[bool]
) -> ColumnElement[float]:
    """Continuous percentile of `value` over the rows matching `conditions`. NULLs are ignored."""
    percentile = func.percentile_cont(fraction).within_group(value)
    return percentile.filter(*conditions) if conditions else percentile


def _share(part: int | None, whole: int | None) -> float:
    """`part / whole`, or 0 when `whole` is 0."""
    return part / whole if part and whole else 0.0


def _usd(amount: Decimal | None) -> float:
    """A sum of USD amounts as a JSON number. PostgreSQL sums them exactly, as NUMERIC."""
    return float(amount) if amount is not None else 0.0
