"""Admin API application factory.

The admin API is a separate application from the gateway. It shares their
configuration, PostgreSQL and Redis, but runs in its own process, on an internal
port that Docker Compose never publishes:

    uvicorn app.admin_api.main:create_admin_app --factory --port 8001

So even a leaked session token is useless from outside the internal network, and
its heavy statistics queries never slow down the chat traffic of the gateway.

Operators sign in with a username and a password (`sessions.py`). The first
account is created with a one-time setup token printed at startup (`setup.py`).
With `OPERATOR_RECOVERY=true`, a one-time recovery token gives back access to an
account whose password is lost (`recovery.py`).
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.admin_api import actions, recovery, requests, sessions, setup, statistics, targets
from app.admin_api.one_time_tokens import OneTimeToken
from app.admin_api.recovery import RecoveryMode, announce_recovery_token
from app.admin_api.routes import router
from app.admin_api.setup import announce_setup_token
from app.api.routes import error_response, validation_error_handler
from app.auth.authenticator import AuthenticationUnavailable
from app.auth.sessions import InvalidSession
from app.config import Settings, load_config
from app.routing.acquisition import TargetGate
from app.storage.db import create_database_engine
from app.storage.redis_client import create_redis_client

logger = logging.getLogger(__name__)


def create_admin_app(settings: Settings | None = None) -> FastAPI:
    """Build the admin API application.

    Raises `ConfigError` when the gateway configuration is invalid, like the gateway.
    """
    settings = settings or Settings()
    config = load_config(settings.gateway_config_path, os.environ)
    database_engine = create_database_engine(settings)
    redis_client = create_redis_client(settings)
    setup_token = OneTimeToken()
    recovery_mode = RecoveryMode(settings.operator_recovery)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await announce_setup_token(database_engine, setup_token)
        announce_recovery_token(recovery_mode)
        yield
        await database_engine.dispose()
        await redis_client.aclose()

    app = FastAPI(title="LLM Gateway admin API", version="0.5.0", lifespan=lifespan)
    app.state.config = config
    app.state.database_engine = database_engine
    app.state.redis = redis_client
    # Only to read the live state of the targets: the admin API never calls a target.
    app.state.gate = TargetGate(redis_client, config.cooldown, config.breaker)
    app.state.setup_token = setup_token
    app.state.recovery = recovery_mode
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(InvalidSession, invalid_session_handler)
    app.add_exception_handler(AuthenticationUnavailable, authentication_unavailable_handler)
    app.add_exception_handler(SQLAlchemyError, database_unavailable_handler)
    app.add_exception_handler(OSError, database_unavailable_handler)
    app.include_router(router)
    app.include_router(setup.router)
    app.include_router(recovery.router)
    app.include_router(sessions.router)
    app.include_router(statistics.router)
    app.include_router(targets.router)
    app.include_router(requests.router)
    app.include_router(actions.router)
    return app


async def invalid_session_handler(_: Request, __: Exception) -> JSONResponse:
    """Refuse a request without a valid session (OpenAI format, 401): sign in again."""
    return error_response(
        401,
        "Missing, invalid or expired session. Sign in again.",
        "invalid_request_error",
        code="invalid_session",
    )


async def authentication_unavailable_handler(_: Request, __: Exception) -> JSONResponse:
    """Refuse a request whose session cannot be checked: never accept an unchecked session."""
    return error_response(
        503,
        "The session cannot be checked right now. Try again later.",
        "api_error",
        code="authentication_unavailable",
    )


async def database_unavailable_handler(_: Request, exc: Exception) -> JSONResponse:
    """Answer 503 when PostgreSQL fails: every report and action needs it."""
    logger.warning("PostgreSQL is unavailable (%s): admin request refused", type(exc).__name__)
    return error_response(
        503,
        "The database is unavailable. Try again later.",
        "api_error",
        code="database_unavailable",
    )
