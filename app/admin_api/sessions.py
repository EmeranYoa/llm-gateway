"""Sign-in and sign-out of operators.

An operator signs in with a username and a password, and gets a session token
valid for 8 hours. Every other admin request sends it (see `dependencies.py`).

Two limits slow down password guessing: 20 attempts per client address within
15 minutes (`sign_in_limits.py`, checked before the password), and a lock of the
account for 15 minutes after 5 failed sign-ins within 15 minutes
(`app/storage/operators.py`).
"""

import asyncio
import datetime as dt
import logging
from typing import Annotated, cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin_api.dependencies import Database, SignedIn
from app.admin_api.schemas import Session
from app.admin_api.sign_in_limits import AddressLimiter, Clock
from app.api.routes import error_response
from app.auth import passwords
from app.auth.passwords import dummy_password_hash, verify_password
from app.schemas import ErrorBody
from app.storage.operators import (
    LOCK_DURATION,
    MAX_FAILED_SIGN_INS,
    clear_failed_sign_ins,
    close_session,
    find_credentials,
    open_session,
    record_failed_sign_in,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v1")

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
"""A username: 1 to 64 characters, surrounding spaces removed. Unique whatever the case."""


class SignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Username
    # No password can be longer: refusing longer ones keeps scrypt fast.
    password: str = Field(max_length=passwords.MAX_LENGTH)


@router.post(
    "/sessions",
    status_code=201,
    response_model=Session,
    responses={
        401: {"model": ErrorBody, "description": "Wrong username or password"},
        429: {"model": ErrorBody, "description": "Too many sign-in attempts from this address"},
    },
)
async def sign_in(
    body: SignInRequest, request: Request, database: Database
) -> Session | JSONResponse:
    """Open a session with a username and a password.

    A wrong password, an unknown username, a disabled account and a locked
    account all get the same answer, so the answer never tells which usernames exist.
    """
    now = cast(Clock, request.app.state.clock)()
    limiter = cast(AddressLimiter, request.app.state.sign_in_limiter)
    client_ip = request.client.host if request.client else "unknown address"
    retry_after = limiter.attempt(client_ip, now)
    if retry_after is not None:
        logger.warning("too many sign-in attempts to the admin API from %s", client_ip)
        response = error_response(
            429,
            "Too many sign-in attempts from this address. Try again later.",
            "rate_limit_error",
            code="too_many_attempts",
        )
        response.headers["Retry-After"] = str(retry_after)
        return response
    operator_id = await check_credentials(database, body.username, body.password, now)
    if operator_id is None:
        # Never log the username typed: people sometimes type their password there.
        logger.warning("failed sign-in to the admin API from %s", client_ip)
        return error_response(
            401, "Wrong username or password.", "invalid_request_error", code="invalid_credentials"
        )
    session = await open_session(database, operator_id)
    return Session(token=session.token, username=session.username, expires_at=session.expires_at)


@router.delete("/sessions/current", status_code=204)
async def sign_out(admin: SignedIn, database: Database) -> Response:
    """End the session of the request: its token is refused from now on.

    Allowed during a forced password change.
    """
    await close_session(database, admin.session_id)
    return Response(status_code=204)


async def check_credentials(
    database: AsyncEngine, username: str, password: str, now: dt.datetime
) -> int | None:
    """Return the id of the operator when `password` is right, else None.

    None for an unknown username, a disabled account or an account locked at
    `now` too. A wrong password counts as a failed sign-in of the account.

    Every case checks one password hash, a dummy one when there is no account to
    check, so they all take about the same time. The check runs in a thread:
    scrypt is slow on purpose and must not block other requests.
    """
    credentials = await find_credentials(database, username)
    if credentials is None or not credentials.enabled or credentials.locked_at(now):
        await asyncio.to_thread(_verify_dummy_password, password)
        return None
    if not await asyncio.to_thread(verify_password, password, credentials.password_hash):
        locked_until = await record_failed_sign_in(database, credentials.operator_id, now)
        if locked_until is not None:
            logger.warning(
                "operator account %d locked for %d minutes after %d failed sign-ins",
                credentials.operator_id,
                LOCK_DURATION // dt.timedelta(minutes=1),
                MAX_FAILED_SIGN_INS,
            )
        return None
    # Fails when concurrent failures locked the account during the check.
    if not await clear_failed_sign_ins(database, credentials.operator_id, now):
        return None
    return credentials.operator_id


def _verify_dummy_password(password: str) -> None:
    """Spend the time of a password check, for an account that cannot sign in."""
    verify_password(password, dummy_password_hash())
