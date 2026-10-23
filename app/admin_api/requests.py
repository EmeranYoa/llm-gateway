"""Requests in the admin API: find a request and see how the gateway routed it.

A request is the group of its usage rows (same `request_id`): one row per target
examined, in `attempt_index` order. Its status follows `request_status.py`; it is
computed in SQL, so that the list can filter and page on it.

The list is paged with a cursor: the date and id of the last request of a page.
Requests are ordered by date, then by id, so two requests received at the same
moment are never skipped or repeated from one page to the next.
"""

import base64
import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import ColumnElement, Select, Subquery, and_, func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import InstrumentedAttribute

from app.admin_api.dependencies import Admin, Database
from app.admin_api.periods import Period
from app.admin_api.request_status import (
    ANSWER_OUTCOMES,
    RequestStatus,
    status_expression,
)
from app.api.routes import error_response
from app.schemas import ErrorBody
from app.storage.tenants import TenantRow
from app.storage.usage import UsageLogRow

router = APIRouter(prefix="/admin/v1")

PAGE_SIZE = 50


# --- Response bodies ---


class _Documented(BaseModel):
    # Attribute docstrings become field descriptions in the OpenAPI schema.
    model_config = ConfigDict(use_attribute_docstrings=True)


class RequestSummary(_Documented):
    """One request to the gateway, summed up from its usage rows."""

    request_id: str
    created_at: dt.datetime
    """When the gateway received the request (UTC)."""
    tenant: str | None
    """Name of the tenant whose key made the request. Null for requests logged before v0.2.0."""
    alias: str
    """The model alias the client asked for."""
    status: RequestStatus
    """`answered`, `failed`, `client_error` or `cancelled` (see the dashboard error rate)."""
    status_code: int | None
    """HTTP status code of the last usage row. Null when the last target was skipped or
    gave no status (timeout, network error, cancelled stream)."""
    provider: str | None
    """Provider of the answer (for a cache hit: of the cached answer). Null when not answered."""
    model: str | None
    """Model of the answer (for a cache hit: of the cached answer). Null when not answered."""
    attempts: int
    """Number of usage rows: targets examined, or 1 for a cache hit or a tenant quota refusal."""
    stream: bool
    """True when the client asked for a streamed answer."""
    latency_ms: int | None
    """Sum of the durations of the attempts. Null when no target was called."""
    cost_usd: float | None
    """What the request cost, in USD. Null when no row has a known cost."""
    cache: str | None
    """What the response cache did: `hit`, `miss`, `bypass` or `unavailable`.
    Null when the alias does not use the cache."""


class RequestPage(_Documented):
    """One page of requests, newest first."""

    items: list[RequestSummary]
    next_cursor: str | None
    """Pass it as `cursor` to get the next, older page. Null on the last page."""


class RoutingStep(_Documented):
    """One usage row of a request: a target examined, a cache hit or a tenant quota refusal."""

    attempt_index: int
    """Position of the row in the routing path, from 0."""
    provider: str | None
    """Null when no target was examined: the request was refused by its tenant quota."""
    model: str | None
    outcome: str
    """What happened, for example `success`, `rate_limited`, `skipped_cooldown`,
    `cache_hit` or `rejected_tenant_quota` (see the usage log in the README)."""
    status_code: int | None
    """HTTP status code of the attempt. Null when the target was skipped or gave no status."""
    latency_ms: int | None
    """Duration of the attempt; for a stream, until its last chunk. Null when not called."""
    first_token_ms: int | None
    """Time to the first content of a streamed answer. Null for any other row."""
    estimated_tokens: int | None
    """Tokens the gateway reserved before the call."""
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    """What the attempt cost, in USD. Null when the price or the token counts are unknown."""
    saved_cost_usd: float | None
    """For a cache hit: what the answer would cost from its original model. Else null."""
    degraded: bool
    """True when the gateway routed without Redis (no quota, cooldown or breaker checks)."""
    cache: str | None
    """What the response cache did for the request. Null when the alias does not use it."""
    cache_similarity: float | None
    """For a cache hit: 1.0 for an identical request, else the similarity of the questions."""
    error_message: str | None
    """Why the target failed or was skipped. Never contains the prompt."""


class RequestDetail(RequestSummary):
    """One request and its routing path."""

    routing_path: list[RoutingStep]
    """Every usage row of the request, in `attempt_index` order."""


# --- Routes ---


@router.get(
    "/requests",
    response_model=RequestPage,
    responses={400: {"model": ErrorBody, "description": "Invalid filter or cursor"}},
)
async def list_requests(
    _: Admin,
    database: Database,
    period: Period = Period.DAY,
    tenant: Annotated[str | None, Query(description="Only the requests of this tenant")] = None,
    alias: Annotated[str | None, Query(description="Only the requests for this alias")] = None,
    status: Annotated[
        RequestStatus | None, Query(description="Only requests with this status")
    ] = None,
    cursor: Annotated[str | None, Query(description="`next_cursor` of the previous page")] = None,
) -> RequestPage | JSONResponse:
    """List the requests of the period, newest first, 50 per page.

    An unknown tenant or alias gives an empty list.
    """
    after: tuple[dt.datetime, str] | None = None
    if cursor is not None:
        try:
            after = _decode_cursor(cursor)
        except ValueError:
            return error_response(
                400,
                "Invalid cursor: pass the next_cursor of a previous page.",
                "invalid_request_error",
                param="cursor",
                code="invalid_cursor",
            )

    row_filters: list[ColumnElement[bool]] = [
        UsageLogRow.created_at >= period.start(dt.datetime.now(dt.UTC))
    ]
    if tenant is not None:
        tenant_id = select(TenantRow.id).where(TenantRow.name == tenant).scalar_subquery()
        row_filters.append(UsageLogRow.tenant_id == tenant_id)
    if alias is not None:
        row_filters.append(UsageLogRow.alias == alias)
    requests = _requests(row_filters)

    query = _with_tenant_names(requests)
    if status is not None:
        query = query.where(requests.c.status == status.value)
    if after is not None:
        created_at, request_id = after
        query = query.where(
            or_(
                requests.c.created_at < created_at,
                and_(requests.c.created_at == created_at, requests.c.request_id < request_id),
            )
        )
    # One more than a page, to know whether another page follows.
    query = query.order_by(requests.c.created_at.desc(), requests.c.request_id.desc()).limit(
        PAGE_SIZE + 1
    )
    async with database.connect() as connection:
        rows = (await connection.execute(query)).mappings().all()

    items = [RequestSummary.model_validate(dict(row)) for row in rows[:PAGE_SIZE]]
    next_cursor = _encode_cursor(items[-1]) if len(rows) > PAGE_SIZE else None
    return RequestPage(items=items, next_cursor=next_cursor)


@router.get(
    "/requests/{request_id}",
    response_model=RequestDetail,
    responses={404: {"model": ErrorBody, "description": "Unknown request"}},
)
async def get_request(
    _: Admin, database: Database, request_id: str
) -> RequestDetail | JSONResponse:
    """Return one request and its routing path, whatever its age."""
    summary_query = _with_tenant_names(_requests([UsageLogRow.request_id == request_id]))
    # Only the columns the routing path shows.
    usage_columns = UsageLogRow.__table__.c
    path_query = (
        select(*(usage_columns[name] for name in RoutingStep.model_fields))
        .where(UsageLogRow.request_id == request_id)
        .order_by(UsageLogRow.attempt_index)
    )
    async with database.connect() as connection:
        summary = (await connection.execute(summary_query)).mappings().first()
        path = (await connection.execute(path_query)).mappings().all() if summary else []
    if summary is None:
        return error_response(
            404,
            "No request with this id.",
            "invalid_request_error",
            param="request_id",
            code="request_not_found",
        )
    return RequestDetail.model_validate({**summary, "routing_path": [dict(row) for row in path]})


# --- Queries ---


def _requests(row_filters: list[ColumnElement[bool]]) -> Subquery:
    """One row per request, summed up from its usage rows that match `row_filters`."""
    row = UsageLogRow
    return (
        select(
            row.request_id,
            # Every row of a request records the same date, tenant, alias and cache.
            func.min(row.created_at).label("created_at"),
            func.min(row.tenant_id).label("tenant_id"),
            func.min(row.alias).label("alias"),
            func.min(row.cache).label("cache"),
            status_expression().label("status"),
            # The status code of the last row; the provider and model of the answer.
            func.array_agg(aggregate_order_by(row.status_code, row.attempt_index.desc()))[1].label(
                "status_code"
            ),
            _of_answer(row.provider).label("provider"),
            _of_answer(row.model).label("model"),
            func.count().label("attempts"),
            func.bool_or(row.stream).label("stream"),
            func.sum(row.latency_ms).label("latency_ms"),
            func.sum(row.cost_usd).label("cost_usd"),
        )
        .where(*row_filters)
        .group_by(row.request_id)
        .subquery("requests")
    )


def _of_answer(column: InstrumentedAttribute[str | None]) -> ColumnElement[str | None]:
    """`column` of the row that answered the request, or NULL when it was not answered."""
    answered = UsageLogRow.outcome.in_(sorted(ANSWER_OUTCOMES))
    return func.array_agg(aggregate_order_by(column, UsageLogRow.attempt_index)).filter(answered)[1]


def _with_tenant_names(requests: Subquery) -> Select[Any]:
    """Select the requests with the name of their tenant (NULL before v0.2.0)."""
    return select(requests, TenantRow.name.label("tenant")).outerjoin(
        TenantRow, TenantRow.id == requests.c.tenant_id
    )


# --- Cursor ---


def _encode_cursor(last: RequestSummary) -> str:
    """An opaque cursor that points after `last`: its date and id, in URL-safe base64."""
    position = f"{last.created_at.isoformat()} {last.request_id}"
    return base64.urlsafe_b64encode(position.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[dt.datetime, str]:
    """Read a cursor made by `_encode_cursor`. Raises ValueError for any other value."""
    # Every error here is a ValueError: base64, text encoding, split and date parsing.
    position = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
    created_at, request_id = position.decode().split(" ", 1)
    after = dt.datetime.fromisoformat(created_at)
    if after.tzinfo is None or not request_id:
        raise ValueError("incomplete cursor")
    return after, request_id
