"""Admin actions: manage the keys and limits of tenants, and their cached answers.

They do what the admin CLI does, for the dashboard. Every change is recorded in
the history of admin actions with the operator's admin key (see
`app/storage/admin_actions.py`), and that history is listed here too.

A full key is returned once, by the request that creates it. Admin keys are
never managed here: they are created with the admin CLI only.
"""

import datetime as dt
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError

from app.admin_api.dependencies import Admin, Config, Database, RedisClient
from app.api.routes import error_response
from app.auth.keys import display_prefix
from app.cache.store import ResponseCache
from app.config import TenantLimits
from app.schemas import ErrorBody
from app.storage.admin_actions import Action, Actor, list_actions, record_cache_clear
from app.storage.admin_keys import AdminIdentity
from app.storage.tenants import (
    ApiKeyInfo,
    Revocation,
    create_api_key,
    find_api_key,
    find_tenant,
    list_api_keys,
    revoke_api_key,
    set_tenant_limits,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v1")

RequestsPerMinute = Annotated[int, Field(gt=0, le=2**31 - 1)]
TokensPerDay = Annotated[int, Field(gt=0, le=2**63 - 1)]


# --- Request and response bodies ---


class Limits(BaseModel):
    """Quotas of a tenant: requests per minute, and a daily token budget reset at 00:00 UTC."""

    rpm: int | None
    tokens_per_day: int | None


class TenantLimitsView(BaseModel):
    """The limits of a tenant: its own, and the ones the gateway applies."""

    tenant: str
    limits: Limits
    """The tenant's own limits. null: the tenant uses the default of `gateway.yaml`."""
    effective_limits: Limits
    """Own limits, or the defaults of `gateway.yaml` where it has none. null: no limit."""


class ApiKey(BaseModel):
    """A gateway API key of a tenant. Never the key itself: only its first characters."""

    id: int
    tenant: str
    prefix: str
    created_at: dt.datetime
    last_used_at: dt.datetime | None
    """Updated about once per minute at most, when a gateway checks the key again."""
    revoked_at: dt.datetime | None
    """null while the key is active."""


class TenantKeys(TenantLimitsView):
    """A tenant with its limits and all its keys, oldest first."""

    keys: list[ApiKey]


class NewKeyRequest(BaseModel):
    """Create a key for a tenant, and the tenant itself if it does not exist yet.

    Limits given become the tenant's own limits; limits left out keep their value.
    """

    model_config = ConfigDict(extra="forbid")

    tenant: str = Field(min_length=1)
    rpm: RequestsPerMinute | None = None
    tokens_per_day: TokensPerDay | None = None


class CreatedKey(BaseModel):
    """A key just created. This is the only time the full `key` is shown: store it now."""

    id: int
    tenant: str
    prefix: str
    key: str


class LimitsUpdate(BaseModel):
    """New own limits of a tenant. Give at least one; a limit left out keeps its value."""

    model_config = ConfigDict(extra="forbid")

    rpm: RequestsPerMinute | None = None
    tokens_per_day: TokensPerDay | None = None


class CacheClearRequest(BaseModel):
    """Remove the cached answers of one tenant, or of one of its aliases only."""

    model_config = ConfigDict(extra="forbid")

    tenant: str = Field(min_length=1)
    alias: str | None = Field(default=None, min_length=1)


class CacheClearResult(BaseModel):
    removed: int
    """Number of cached answers removed."""


class AdminAction(BaseModel):
    """A change made by an operator, with the admin API or the admin CLI."""

    id: int
    created_at: dt.datetime
    admin_key_id: int | None
    """The admin key used; null for the admin CLI."""
    actor: str
    """The name of that admin key, or `cli`."""
    action: Action
    target: str | None
    """Tenant name or key id; null when the action concerns every tenant."""
    details: dict[str, Any]
    """What changed, for example the new limits, a key prefix or the answers removed."""


class AdminActionPage(BaseModel):
    """Admin actions, newest first."""

    actions: list[AdminAction]
    next_before: int | None
    """Pass it as `before` to get the next, older page. null on the last page."""


# --- Routes ---
# Errors are returned as `JSONResponse` in OpenAI format, so each route names its
# `response_model` for the OpenAPI schema instead of relying on its return type.


def _errors(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Document error answers in the OpenAPI schema."""
    return {status: {"model": ErrorBody} for status in statuses}


@router.get("/tenants/{name}/keys", response_model=TenantKeys, responses=_errors(404))
async def tenant_keys(
    name: str, _: Admin, database: Database, config: Config
) -> TenantKeys | JSONResponse:
    """Return the limits of a tenant and all its keys."""
    tenant = await find_tenant(database, name)
    if tenant is None:
        return _unknown_tenant(name)
    keys = await list_api_keys(database, name)
    view = _limits_view(name, tenant.limits, config.tenant_default_limits)
    return TenantKeys(**dict(view), keys=[_api_key(key) for key in keys])


@router.post("/keys", status_code=201, response_model=CreatedKey)
async def create_key(body: NewKeyRequest, admin: Admin, database: Database) -> CreatedKey:
    """Create a gateway API key for a tenant, and the tenant if needed."""
    new_key = await create_api_key(
        database,
        body.tenant,
        rpm=body.rpm,
        tokens_per_day=body.tokens_per_day,
        actor=_actor(admin),
    )
    return CreatedKey(
        id=new_key.owner.api_key_id,
        tenant=body.tenant,
        prefix=display_prefix(new_key.key),
        key=new_key.key,
    )


@router.post("/keys/{key_id}/revoke", response_model=ApiKey, responses=_errors(404, 409))
async def revoke_key(key_id: int, admin: Admin, database: Database) -> ApiKey | JSONResponse:
    """Revoke a gateway API key. Gateways refuse it once their key cache expires (60 s)."""
    match await revoke_api_key(database, key_id, actor=_actor(admin)):
        case Revocation.NOT_FOUND:
            return error_response(
                404, f"No API key with id {key_id}.", "invalid_request_error", code="key_not_found"
            )
        case Revocation.ALREADY_REVOKED:
            return error_response(
                409,
                f"API key {key_id} is already revoked.",
                "invalid_request_error",
                code="key_already_revoked",
            )
    revoked = await find_api_key(database, key_id)
    assert revoked is not None  # keys are revoked, never deleted
    return _api_key(revoked)


@router.put("/tenants/{name}/limits", response_model=TenantLimitsView, responses=_errors(400, 404))
async def set_limits(
    name: str, body: LimitsUpdate, admin: Admin, database: Database, config: Config
) -> TenantLimitsView | JSONResponse:
    """Set the own limits of a tenant. Gateways apply them once their key cache expires (60 s)."""
    if body.rpm is None and body.tokens_per_day is None:
        return error_response(
            400, "Give at least one limit: rpm and/or tokens_per_day.", "invalid_request_error"
        )
    limits = await set_tenant_limits(
        database, name, rpm=body.rpm, tokens_per_day=body.tokens_per_day, actor=_actor(admin)
    )
    if limits is None:
        return _unknown_tenant(name)
    return _limits_view(name, limits, config.tenant_default_limits)


@router.post("/cache/clear", response_model=CacheClearResult, responses=_errors(404, 503))
async def clear_cache(
    body: CacheClearRequest, admin: Admin, database: Database, redis: RedisClient
) -> CacheClearResult | JSONResponse:
    """Remove the cached answers of a tenant, or of one of its aliases.

    Redis and PostgreSQL share no transaction, so the action is recorded right
    after the answers are removed. If PostgreSQL fails in between, the answers
    are gone, the action is missing from the history and the request gets 503.
    """
    tenant = await find_tenant(database, body.tenant)
    if tenant is None:
        return _unknown_tenant(body.tenant)
    try:
        # Clearing needs no alias settings: those only matter to store answers.
        removed = await ResponseCache(redis, cached_aliases={}).clear(tenant.id, body.alias)
    except RedisError as error:
        logger.warning("Redis is unavailable (%s): cache not cleared", type(error).__name__)
        return error_response(
            503, "Redis is unavailable. Try again later.", "api_error", code="redis_unavailable"
        )
    await record_cache_clear(database, _actor(admin), body.tenant, body.alias, removed)
    return CacheClearResult(removed=removed)


@router.get("/actions", response_model=AdminActionPage)
async def actions(
    _: Admin,
    database: Database,
    limit: Annotated[int, Query(ge=1, le=1000, description="Actions per page")] = 50,
    before: Annotated[
        int | None, Query(description="`next_before` of the previous page: older actions only")
    ] = None,
) -> AdminActionPage:
    """Return the history of admin actions, newest first, one page at a time."""
    found = await list_actions(database, limit=limit, before=before)
    return AdminActionPage(
        actions=[AdminAction(**vars(action)) for action in found],
        next_before=found[-1].id if len(found) == limit else None,
    )


# --- Helpers ---


def _actor(admin: AdminIdentity) -> Actor:
    return Actor(admin.name, admin.admin_key_id)


def _unknown_tenant(name: str) -> JSONResponse:
    return error_response(
        404, f"Unknown tenant '{name}'.", "invalid_request_error", code="tenant_not_found"
    )


def _limits_view(name: str, own: TenantLimits, defaults: TenantLimits) -> TenantLimitsView:
    """The tenant's own limits, and the limits the gateway applies: own, else the default."""
    return TenantLimitsView(
        tenant=name,
        limits=Limits(rpm=own.rpm, tokens_per_day=own.tokens_per_day),
        effective_limits=Limits(
            rpm=own.rpm if own.rpm is not None else defaults.rpm,
            tokens_per_day=(
                own.tokens_per_day if own.tokens_per_day is not None else defaults.tokens_per_day
            ),
        ),
    )


def _api_key(key: ApiKeyInfo) -> ApiKey:
    return ApiKey(
        id=key.id,
        tenant=key.tenant_name,
        prefix=key.prefix,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )
