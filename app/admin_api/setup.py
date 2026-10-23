"""Setup of the first operator account, with a one-time setup token.

A new installation has no operator account, so nobody can sign in. While no
operator exists, the admin API generates a random setup token at startup and
prints it once in its log. Whoever can read the server log (the person who
installed the gateway) enters it in the dashboard with a username and a
password, and so creates the first account. The token then stops working.

Only the hash of the token is kept, in memory: it is never stored in the
database, and a restart prints a new one while no account exists. Several
admin API instances each print their own token; the database makes sure that
only one first account is ever created (`create_first_operator`).
"""

import asyncio
import hmac
import logging
import secrets
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin_api.dependencies import Database
from app.admin_api.schemas import Session, SetupStatus
from app.admin_api.sessions import Username
from app.api.routes import error_response
from app.auth.keys import hash_key
from app.auth.passwords import hash_password, password_problem
from app.schemas import ErrorBody
from app.storage.admin_actions import SETUP
from app.storage.operators import any_operator_exists, create_first_operator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v1")


class SetupToken:
    """The one-time setup token of this admin API instance. Only its hash is kept."""

    def __init__(self) -> None:
        self._hash: str | None = None

    @property
    def available(self) -> bool:
        """True from its generation until the first account is created with it."""
        return self._hash is not None

    def generate(self) -> str:
        """Generate a new token, replacing any previous one, and return it."""
        token = secrets.token_urlsafe(32)
        self._hash = hash_key(token)
        return token

    def matches(self, token: str) -> bool:
        """Return True when `token` is the setup token. Constant-time comparison."""
        return self._hash is not None and hmac.compare_digest(self._hash, hash_key(token))

    def consume(self) -> None:
        """Stop accepting the token: the first account exists."""
        self._hash = None


async def announce_setup_token(engine: AsyncEngine, setup_token: SetupToken) -> None:
    """At startup, generate and print a setup token when no operator account exists.

    When PostgreSQL is unavailable, the token is generated and printed anyway:
    the setup itself checks again, atomically, that no account exists.
    """
    try:
        if await any_operator_exists(engine):
            return
    except (SQLAlchemyError, OSError, TimeoutError) as error:
        logger.warning(
            "cannot check for operator accounts, PostgreSQL is unavailable (%s):"
            " printing a setup token anyway",
            type(error).__name__,
        )
    token = setup_token.generate()
    # This is the only secret the project ever prints on purpose: the server log
    # is the one channel that only the person who installed the gateway can read
    # before any account exists. The risk stays small: the token only creates the
    # first account, works once, and is never stored. It stays the last word of
    # the line, so it is easy to copy.
    logger.warning(
        "No operator account exists yet. To create the first one, open the dashboard"
        " and enter this one-time setup token: %s",
        token,
    )


class SetupRequest(BaseModel):
    """Create the first operator account with the setup token printed in the log."""

    model_config = ConfigDict(extra="forbid")

    token: str
    username: Username
    password: str
    """12 to 256 characters, and not the username."""


@router.get("/setup")
async def setup_status(request: Request, database: Database) -> SetupStatus:
    """Tell whether the first operator account can still be created. No session needed."""
    is_open = _setup_token(request).available and not await any_operator_exists(database)
    return SetupStatus(open=is_open)


@router.post(
    "/setup",
    status_code=201,
    response_model=Session,
    responses={
        400: {"model": ErrorBody, "description": "Password refused"},
        401: {"model": ErrorBody, "description": "Wrong setup token"},
        404: {"model": ErrorBody, "description": "An operator account exists already"},
    },
)
async def set_up(
    body: SetupRequest, request: Request, database: Database
) -> Session | JSONResponse:
    """Create the first operator account and sign it in. No session needed: the token is enough.

    Two setups at the same time never create two accounts: exactly one succeeds.
    """
    setup_token = _setup_token(request)
    if not setup_token.available:
        return _setup_closed()
    if not setup_token.matches(body.token):
        client_ip = request.client.host if request.client else "unknown address"
        logger.warning("refused a setup request from %s: wrong setup token", client_ip)
        return error_response(
            401, "Wrong setup token.", "invalid_request_error", code="invalid_setup_token"
        )
    problem = password_problem(body.password, body.username)
    if problem is not None:
        return error_response(
            400, problem, "invalid_request_error", param="password", code="invalid_password"
        )
    password_hash = await asyncio.to_thread(hash_password, body.password)
    session = await create_first_operator(database, body.username, password_hash, actor=SETUP)
    if session is None:
        return _setup_closed()
    setup_token.consume()
    logger.info("created the first operator account, %s", session.username)
    return Session(token=session.token, username=session.username, expires_at=session.expires_at)


def _setup_token(request: Request) -> SetupToken:
    return cast(SetupToken, request.app.state.setup_token)


def _setup_closed() -> JSONResponse:
    return error_response(
        404,
        "An operator account exists already: sign in instead.",
        "invalid_request_error",
        code="setup_closed",
    )
