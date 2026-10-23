"""HTTP routes of the gateway."""

import asyncio
import contextlib
import datetime as dt
import json
import logging
import math
import time
from collections.abc import AsyncIterator, Coroutine
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth.authenticator import Authenticator
from app.cache.eligibility import answer_can_be_stored, request_can_use_cache
from app.cache.keys import RequestKey, request_key
from app.cache.replay import replayed_chunks
from app.cache.store import CachedAnswer, CacheLookup, CacheUnavailable, ResponseCache
from app.config import GatewayConfig, Target
from app.routing.acquisition import (
    TargetGate,
    TenantAdmission,
    TenantBudgetExceeded,
    TenantGate,
    TenantQuotaExceeded,
    TenantRpmExceeded,
)
from app.routing.router import (
    AllTargetsFailed,
    Attempt,
    DeadlineExceeded,
    NoEnabledTarget,
    Outcome,
    RequestTooLarge,
    RoutedResponse,
    Router,
    TargetRejectedRequest,
    UnknownAlias,
)
from app.routing.streaming import CommittedStream, StreamInterrupted
from app.schemas import ChatCompletionRequest, ErrorBody, ErrorDetail, asks_for_stream_usage
from app.storage.tenants import KeyOwner
from app.storage.usage import LoggedRequest, UsageLog

logger = logging.getLogger(__name__)

router = APIRouter()


def get_config(request: Request) -> GatewayConfig:
    """Return the gateway configuration loaded at startup."""
    return cast(GatewayConfig, request.app.state.config)


def get_router(request: Request) -> Router:
    """Return the router built at startup."""
    return cast(Router, request.app.state.router)


def get_gate(request: Request) -> TargetGate:
    """Return the shared target state (Redis) built at startup."""
    return cast(TargetGate, request.app.state.gate)


def get_tenant_gate(request: Request) -> TenantGate:
    """Return the tenant quotas (Redis) built at startup."""
    return cast(TenantGate, request.app.state.tenant_gate)


def get_authenticator(request: Request) -> Authenticator:
    """Return the API key checker built at startup."""
    return cast(Authenticator, request.app.state.authenticator)


async def authenticate(
    request: Request,
    authenticator: Annotated[Authenticator, Depends(get_authenticator)],
    authorization: Annotated[str | None, Header()] = None,
) -> KeyOwner:
    """Check the gateway API key of the request (`Authorization: Bearer <key>`)."""
    client_ip = request.client.host if request.client else "unknown address"
    return await authenticator.authenticate(authorization, client_ip)


def get_response_cache(request: Request) -> ResponseCache:
    """Return the response cache built at startup."""
    return cast(ResponseCache, request.app.state.response_cache)


def get_usage_log(request: Request) -> UsageLog:
    """Return the usage log built at startup."""
    return cast(UsageLog, request.app.state.usage_log)


@router.get("/health")
async def health(
    gate: Annotated[TargetGate, Depends(get_gate)],
) -> dict[str, str]:
    """Report that the gateway is up and whether Redis answers. Public: no API key needed.

    It reveals nothing about routes or providers. Without Redis the gateway still
    serves requests, without cooldown, breaker or quota checks: its status is then
    "degraded" (ADR 0002).
    """
    redis_up = await gate.is_available()
    return {"status": "ok" if redis_up else "degraded", "redis": "up" if redis_up else "down"}


def error_response(
    status_code: int,
    message: str,
    error_type: str,
    *,
    param: str | None = None,
    code: str | None = None,
) -> JSONResponse:
    """Build an error response in OpenAI format."""
    body = ErrorBody(error=ErrorDetail(message=message, type=error_type, param=param, code=code))
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def invalid_api_key_handler(_: Request, __: Exception) -> JSONResponse:
    """Refuse a request without a valid gateway API key (OpenAI format, 401)."""
    return error_response(
        401, "Missing or invalid API key.", "invalid_request_error", code="invalid_api_key"
    )


async def authentication_unavailable_handler(_: Request, __: Exception) -> JSONResponse:
    """Refuse a request whose key cannot be checked: never accept an unchecked key."""
    return error_response(
        503,
        "The API key cannot be checked right now. Try again later.",
        "api_error",
        code="authentication_unavailable",
    )


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Return request validation errors in OpenAI format (400) instead of FastAPI's 422.

    The submitted values are never echoed back: they may contain the prompt.
    """
    first_error = cast(RequestValidationError, exc).errors()[0]
    param = ".".join(str(part) for part in first_error["loc"][1:]) or None
    return error_response(
        400,
        f"Invalid value for '{param}': {first_error['msg']}",
        "invalid_request_error",
        param=param,
    )


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    owner: Annotated[KeyOwner, Depends(authenticate)],
    tenant_gate: Annotated[TenantGate, Depends(get_tenant_gate)],
    gateway_router: Annotated[Router, Depends(get_router)],
    response_cache: Annotated[ResponseCache, Depends(get_response_cache)],
    usage_log: Annotated[UsageLog, Depends(get_usage_log)],
    x_gateway_cache: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | Response:
    """Route an OpenAI chat completion request to a provider/model target.

    The tenant quotas are checked first: a tenant over its quota gets a 429 and
    no provider is called. Every examined target is written to the usage log
    after the response is sent, whether the request succeeds or ends in an error.
    A request refused by its tenant quota is logged as one row without a target.

    With `stream: true`, the answer is a Server-Sent Events stream in OpenAI
    format, sent once a target has produced its first content (the commit point).

    On an alias that uses the response cache, an identical earlier request of the
    same tenant is answered from the cache, without calling any provider. Otherwise
    the complete answer is stored after the response. With the request header
    `X-Gateway-Cache: bypass`, a provider is called and its answer replaces the
    stored one.
    """
    request_id = uuid4().hex
    received_at = dt.datetime.now(dt.UTC)
    # The deadline covers everything after authentication, the cache lookup included.
    started = time.monotonic()
    logged_request = LoggedRequest(
        request_id=request_id,
        received_at=received_at,
        owner=owner,
        alias=request.model,
        prompt_chars=request.prompt_chars(),
        stream=request.stream,
    )
    try:
        admission = await tenant_gate.acquire(
            owner.tenant_id, owner.limits, request.model_dump(exclude_unset=True)
        )
    except TenantQuotaExceeded as exc:
        background_tasks.add_task(usage_log.write_tenant_rejection, logged_request, str(exc))
        refused = _tenant_quota_response(exc)
        refused.headers["X-Gateway-Request-Id"] = request_id
        return refused
    cache_key = _cache_key(response_cache, request)
    cache_status, cache_lookup = None, CacheLookup(None, vector=None)
    if cache_key is not None:
        lookup_started = time.perf_counter()
        cache_status, cache_lookup = await _consult_cache(
            response_cache,
            owner.tenant_id,
            request.model,
            cache_key,
            bypass=(x_gateway_cache or "").strip().lower() == "bypass",
            redis_down=admission.degraded,
        )
        if cache_lookup.answer is not None:
            # No provider is called: the tenant budget gets its reserved tokens back.
            await tenant_gate.release(admission)
            background_tasks.add_task(
                usage_log.write_cache_hit,
                logged_request,
                cache_lookup.answer,
                latency_ms=round((time.perf_counter() - lookup_started) * 1000),
            )
            return _cached_response(cache_lookup.answer, request, request_id)
    attempts: list[Attempt] = []
    # Written after the response, with every attempt the routing appends below.
    background_tasks.add_task(usage_log.write, logged_request, attempts, cache=cache_status)
    routing = _route(
        gateway_router, request, attempts, redis_down=admission.degraded, started=started
    )
    try:
        # A streamed request may wait long for its first content: stop if the client leaves.
        result = (
            await _unless_client_leaves(raw_request, routing) if request.stream else await routing
        )
    except ClientLeft:
        # Nobody reads this response; the usage log still records the cancelled attempt.
        return Response(status_code=CLIENT_CLOSED_REQUEST)
    if not isinstance(result, CommittedStream):
        await _record_tenant_outcome(tenant_gate, admission, result, attempts)
    cache_headers = {"X-Gateway-Cache": cache_status} if cache_status is not None else {}
    if cache_key is not None and cache_status in ("miss", "bypass"):
        # Stored after the response: the client does not wait for the cache.
        vector = cache_lookup.vector
        bypass = cache_status == "bypass"
        if isinstance(result, RoutedResponse) and answer_can_be_stored(result.body):
            background_tasks.add_task(
                response_cache.store,
                owner.tenant_id,
                request.model,
                cache_key,
                result.body,
                result.target,
                vector,
                replace=bypass,
            )
        elif isinstance(result, CommittedStream):
            background_tasks.add_task(
                _store_streamed_answer,
                response_cache,
                result,
                owner.tenant_id,
                request.model,
                cache_key,
                vector,
                replace=bypass,
            )
    if isinstance(result, JSONResponse):
        result.headers.update(cache_headers)
        result.headers["X-Gateway-Request-Id"] = request_id
        return result
    if isinstance(result, CommittedStream):
        # The usage log and cache tasks run once the whole stream has been sent.
        return StreamingResponse(
            _sse_events(result, tenant_gate, admission),
            media_type="text/event-stream",
            headers={
                **_routing_headers(result.target, result.fallbacks, request_id),
                **cache_headers,
            },
        )
    response.headers.update(cache_headers)
    response.headers["X-Gateway-Provider"] = result.target.provider.name
    response.headers["X-Gateway-Model"] = result.target.model
    response.headers["X-Gateway-Fallbacks"] = str(result.fallbacks)
    response.headers["X-Gateway-Request-Id"] = request_id
    return result.body


def _cache_key(response_cache: ResponseCache, request: ChatCompletionRequest) -> RequestKey | None:
    """The cache key of the request, or None when the request does not use the cache."""
    if not response_cache.covers(request.model):
        return None
    body = request.model_dump(exclude_unset=True)
    if not request_can_use_cache(body):
        return None
    return request_key(body)


async def _consult_cache(
    response_cache: ResponseCache,
    tenant_id: int,
    alias: str,
    key: RequestKey,
    *,
    bypass: bool,
    redis_down: bool,
) -> tuple[str, CacheLookup]:
    """Look the request up in the cache. Returns the `X-Gateway-Cache` status and the result.

    The status is `hit`, `miss`, `bypass` (the client wants a fresh answer: no
    lookup), or `unavailable` (Redis or the embedding model failed). The cache never
    makes a request fail: when it is unavailable, the request is routed without it.
    """
    if redis_down:
        # Degraded mode (ADR 0002): Redis failed for this request, do not wait for it again.
        return "unavailable", CacheLookup(None, vector=None)
    try:
        if bypass:
            # No lookup, but the fresh answer needs the vector of its question to be stored.
            return "bypass", CacheLookup(None, await response_cache.vector_for(key))
        lookup = await response_cache.lookup(tenant_id, alias, key)
    except CacheUnavailable as error:
        logger.warning("the response cache is unavailable (%s): routing without it", error)
        return "unavailable", CacheLookup(None, vector=None)
    return ("hit" if lookup.answer is not None else "miss"), lookup


def _cached_response(
    cached: CachedAnswer, request: ChatCompletionRequest, request_id: str
) -> Response:
    """Answer from the cache, with the headers of the target that generated the answer.

    A streamed request gets the answer as a stream, sent at once.
    """
    headers = {
        "X-Gateway-Provider": cached.provider,
        "X-Gateway-Model": cached.model,
        "X-Gateway-Fallbacks": "0",
        "X-Gateway-Request-Id": request_id,
        "X-Gateway-Cache": "hit",
    }
    if not request.stream:
        return JSONResponse(cached.body, headers=headers)
    with_usage = asks_for_stream_usage(request.model_dump(exclude_unset=True))
    return StreamingResponse(
        _replayed_events(replayed_chunks(cached.body, with_usage=with_usage)),
        media_type="text/event-stream",
        headers=headers,
    )


async def _replayed_events(chunks: list[dict[str, Any]]) -> AsyncIterator[str]:
    for chunk in chunks:
        yield _sse(chunk)
    yield "data: [DONE]\n\n"


async def _store_streamed_answer(
    response_cache: ResponseCache,
    stream: CommittedStream,
    tenant_id: int,
    alias: str,
    key: RequestKey,
    vector: list[float] | None,
    *,
    replace: bool,
) -> None:
    """Store the answer of a stream that ended complete.

    It runs after the stream: an interrupted or cancelled stream has no answer.
    """
    if stream.answer is not None and answer_can_be_stored(stream.answer):
        await response_cache.store(
            tenant_id, alias, key, stream.answer, stream.target, vector, replace=replace
        )


# Status for a request the client abandoned (a convention from nginx): never read.
CLIENT_CLOSED_REQUEST = 499


class ClientLeft(Exception):
    """The client closed its connection before the gateway answered."""


async def _unless_client_leaves[T](raw_request: Request, work: Coroutine[Any, Any, T]) -> T:
    """Run `work`, but cancel it if the client disconnects first (then raise `ClientLeft`)."""
    working = asyncio.ensure_future(work)
    watching = asyncio.ensure_future(_client_disconnects(raw_request))
    try:
        await asyncio.wait({working, watching}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        watching.cancel()
    if working.done():
        return working.result()
    working.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await working
    raise ClientLeft


async def _client_disconnects(raw_request: Request) -> None:
    """Return when the client closes its connection (the body is already read)."""
    while (await raw_request.receive())["type"] != "http.disconnect":
        pass


def _routing_headers(target: Target, fallbacks: int, request_id: str) -> dict[str, str]:
    return {
        "X-Gateway-Provider": target.provider.name,
        "X-Gateway-Model": target.model,
        "X-Gateway-Fallbacks": str(fallbacks),
        "X-Gateway-Request-Id": request_id,
    }


async def _sse_events(
    stream: CommittedStream, tenant_gate: TenantGate, admission: TenantAdmission
) -> AsyncIterator[str]:
    """Send each chunk as a Server-Sent Event, with `model` set to the real model.

    A stream that breaks after its first content ends with an error event and no
    `[DONE]`, so the client never takes a truncated answer for a complete one.

    A complete stream corrects the tenant budget with its usage. A broken or
    cancelled one keeps the estimate: the provider may have used those tokens.
    """
    try:
        async for chunk in stream.chunks():
            yield _sse({**chunk, "model": stream.target.model})
    except StreamInterrupted as exc:
        error = ErrorDetail(
            message=f"The stream was interrupted: {exc.reason}.",
            type="api_error",
            code="stream_interrupted",
        )
        yield _sse(ErrorBody(error=error).model_dump())
        return
    if stream.usage is not None:
        await tenant_gate.record_success(admission, stream.usage.used_tokens)
    yield "data: [DONE]\n\n"


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _tenant_quota_response(exc: TenantQuotaExceeded) -> JSONResponse:
    """Build the 429 of a tenant over its own quota, distinct from the 503 of busy providers."""
    match exc:
        case TenantRpmExceeded():
            message = (
                f"You exceeded your requests-per-minute limit for this gateway ({exc.rpm} "
                "requests per minute). This is your own tenant quota, not a provider limit."
            )
        case TenantBudgetExceeded():
            message = (
                f"This request would exceed your daily token budget for this gateway "
                f"({exc.budget} tokens per day, {exc.remaining} left, about {exc.needed} "
                "needed). This is your own tenant quota, not a provider limit. Lower "
                "max_tokens, or wait until the budget resets at midnight UTC."
            )
        case _:
            message = f"You exceeded your quota for this gateway: {exc}."
    response = error_response(429, message, "rate_limit_error", code="tenant_quota_exceeded")
    response.headers["Retry-After"] = _retry_after_header(exc.retry_after)
    return response


async def _record_tenant_outcome(
    tenant_gate: TenantGate,
    admission: TenantAdmission,
    result: RoutedResponse | JSONResponse,
    attempts: list[Attempt],
) -> None:
    """Settle the tokens reserved in the tenant's daily budget, now that the request is over.

    Success: the real usage replaces the estimate. Failure: the tokens are given
    back, unless the last attempt timed out, as the provider may have used them.
    """
    if isinstance(result, RoutedResponse):
        await tenant_gate.record_success(admission, result.used_tokens)
        return
    timed_out = bool(attempts) and attempts[-1].outcome == Outcome.TIMEOUT
    await tenant_gate.record_failure(admission, keep_tokens=timed_out)


def _retry_after_header(seconds: float) -> str:
    """Whole seconds, rounded up, so the client never comes back too early."""
    return str(max(1, math.ceil(seconds)))


async def _route(
    gateway_router: Router,
    request: ChatCompletionRequest,
    attempts: list[Attempt],
    *,
    redis_down: bool,
    started: float,
) -> RoutedResponse | CommittedStream | JSONResponse:
    """Route the request, or build the OpenAI error response that explains why it failed."""
    route = gateway_router.route_stream if request.stream else gateway_router.route
    try:
        return await route(
            request.model,
            request.model_dump(exclude_unset=True),
            attempts=attempts,
            redis_down=redis_down,
            started=started,
        )
    except UnknownAlias as exc:
        return error_response(
            404,
            f"The model '{exc.alias}' does not exist.",
            "invalid_request_error",
            param="model",
            code="model_not_found",
        )
    except NoEnabledTarget as exc:
        return error_response(
            503,
            f"No enabled provider for alias '{exc.alias}'. Check the gateway API keys.",
            "api_error",
            code="no_enabled_target",
        )
    except TargetRejectedRequest as exc:
        return error_response(
            exc.error.status_code,
            str(exc),
            exc.error.error_type,
            param=exc.error.param,
            code=exc.error.code,
        )
    except RequestTooLarge as exc:
        return error_response(
            400,
            f"The request is too large for every target of alias '{exc.alias}'. "
            "Reduce the prompt or max_tokens.",
            "invalid_request_error",
            param="messages",
            code="context_length_exceeded",
        )
    except AllTargetsFailed as exc:
        response = error_response(503, str(exc), "api_error", code="all_targets_failed")
        if exc.retry_after is not None:
            response.headers["Retry-After"] = _retry_after_header(exc.retry_after)
        return response
    except DeadlineExceeded as exc:
        return error_response(504, str(exc), "api_error", code="deadline_exceeded")
