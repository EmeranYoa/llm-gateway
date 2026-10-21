"""HTTP routes of the gateway."""

from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import GatewayConfig
from app.routing.router import (
    AllTargetsFailed,
    DeadlineExceeded,
    NoEnabledTarget,
    RequestTooLarge,
    Router,
    TargetRejectedRequest,
    UnknownAlias,
)
from app.schemas import ChatCompletionRequest, ErrorBody, ErrorDetail

router = APIRouter()


def get_config(request: Request) -> GatewayConfig:
    """Return the gateway configuration loaded at startup."""
    return cast(GatewayConfig, request.app.state.config)


def get_router(request: Request) -> Router:
    """Return the router built at startup."""
    return cast(Router, request.app.state.router)


@router.get("/health")
async def health(config: Annotated[GatewayConfig, Depends(get_config)]) -> dict[str, Any]:
    """Report that the gateway is up and which providers are usable."""
    return {
        "status": "ok",
        "providers": {
            "enabled": list(config.enabled_providers),
            "disabled": list(config.disabled_providers),
        },
        "routes": {
            alias: [target.name for target in targets] for alias, targets in config.routes.items()
        },
    }


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
    response: Response,
    gateway_router: Annotated[Router, Depends(get_router)],
) -> dict[str, Any] | JSONResponse:
    """Route an OpenAI chat completion request to a provider/model target."""
    request_id = uuid4().hex
    if request.stream:
        return error_response(
            400,
            "Streaming is not supported yet.",
            "invalid_request_error",
            param="stream",
            code="unsupported_parameter",
        )
    try:
        routed = await gateway_router.route(request.model, request.model_dump(exclude_unset=True))
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
        return error_response(503, str(exc), "api_error", code="all_targets_failed")
    except DeadlineExceeded as exc:
        return error_response(504, str(exc), "api_error", code="deadline_exceeded")
    response.headers["X-Gateway-Provider"] = routed.target.provider.name
    response.headers["X-Gateway-Model"] = routed.target.model
    response.headers["X-Gateway-Fallbacks"] = str(routed.fallbacks)
    response.headers["X-Gateway-Request-Id"] = request_id
    return routed.body
