"""HTTP routes of the gateway."""

import datetime as dt
import math
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth.authenticator import Authenticator
from app.config import GatewayConfig
from app.routing.acquisition import TargetGate
from app.routing.router import (
    AllTargetsFailed,
    Attempt,
    DeadlineExceeded,
    NoEnabledTarget,
    RequestTooLarge,
    RoutedResponse,
    Router,
    TargetRejectedRequest,
    UnknownAlias,
)
from app.schemas import ChatCompletionRequest, ErrorBody, ErrorDetail
from app.storage.tenants import KeyOwner
from app.storage.usage import UsageLog

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


def get_authenticator(request: Request) -> Authenticator:
    """Return the API key checker built at startup."""
    return cast(Authenticator, request.app.state.authenticator)


async def authenticate(
    authenticator: Annotated[Authenticator, Depends(get_authenticator)],
    authorization: Annotated[str | None, Header()] = None,
) -> KeyOwner:
    """Check the gateway API key of the request (`Authorization: Bearer <key>`)."""
    return await authenticator.authenticate(authorization)


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


@router.post("/v1/chat/completions", response_model=None, dependencies=[Depends(authenticate)])
async def chat_completions(
    request: ChatCompletionRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    gateway_router: Annotated[Router, Depends(get_router)],
    usage_log: Annotated[UsageLog, Depends(get_usage_log)],
) -> dict[str, Any] | JSONResponse:
    """Route an OpenAI chat completion request to a provider/model target.

    Every examined target is written to the usage log after the response is
    sent, whether the request succeeds or ends in an error.
    """
    request_id = uuid4().hex
    received_at = dt.datetime.now(dt.UTC)
    attempts: list[Attempt] = []
    result = await _route(gateway_router, request, attempts)
    background_tasks.add_task(
        usage_log.write,
        request_id=request_id,
        received_at=received_at,
        alias=request.model,
        prompt_chars=request.prompt_chars(),
        attempts=attempts,
    )
    if isinstance(result, JSONResponse):
        result.headers["X-Gateway-Request-Id"] = request_id
        return result
    response.headers["X-Gateway-Provider"] = result.target.provider.name
    response.headers["X-Gateway-Model"] = result.target.model
    response.headers["X-Gateway-Fallbacks"] = str(result.fallbacks)
    response.headers["X-Gateway-Request-Id"] = request_id
    return result.body


async def _route(
    gateway_router: Router, request: ChatCompletionRequest, attempts: list[Attempt]
) -> RoutedResponse | JSONResponse:
    """Route the request, or build the OpenAI error response that explains why it failed."""
    if request.stream:
        return error_response(
            400,
            "Streaming is not supported yet.",
            "invalid_request_error",
            param="stream",
            code="unsupported_parameter",
        )
    try:
        return await gateway_router.route(
            request.model, request.model_dump(exclude_unset=True), attempts=attempts
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
            # Whole seconds, rounded up, so the client never comes back too early.
            response.headers["Retry-After"] = str(max(1, math.ceil(exc.retry_after)))
        return response
    except DeadlineExceeded as exc:
        return error_response(504, str(exc), "api_error", code="deadline_exceeded")
