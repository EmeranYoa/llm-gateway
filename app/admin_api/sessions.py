"""Sign-in and sign-out of operators.

An operator signs in with a username and a password, and gets a session token
valid for 8 hours. Every other admin request sends it (see `dependencies.py`).
"""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin_api.dependencies import Admin, Database
from app.admin_api.schemas import Session
from app.api.routes import error_response
from app.auth import passwords
from app.auth.passwords import verify_password
from app.schemas import ErrorBody
from app.storage.operators import close_session, find_credentials, open_session

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
    responses={401: {"model": ErrorBody, "description": "Wrong username or password"}},
)
async def sign_in(
    body: SignInRequest, request: Request, database: Database
) -> Session | JSONResponse:
    """Open a session with a username and a password.

    A wrong password, an unknown username and a disabled account all get the
    same answer, so the answer never tells which usernames exist.
    """
    operator_id = await check_credentials(database, body.username, body.password)
    if operator_id is None:
        client_ip = request.client.host if request.client else "unknown address"
        # Never log the username typed: people sometimes type their password there.
        logger.warning("failed sign-in to the admin API from %s", client_ip)
        return error_response(
            401, "Wrong username or password.", "invalid_request_error", code="invalid_credentials"
        )
    session = await open_session(database, operator_id)
    return Session(token=session.token, username=session.username, expires_at=session.expires_at)


@router.delete("/sessions/current", status_code=204)
async def sign_out(admin: Admin, database: Database) -> Response:
    """End the session of the request: its token is refused from now on."""
    await close_session(database, admin.session_id)
    return Response(status_code=204)


async def check_credentials(database: AsyncEngine, username: str, password: str) -> int | None:
    """Return the id of the operator when `password` is right, else None.

    None for an unknown username or a disabled account too. The password is
    checked in a thread: scrypt is slow on purpose and must not block other requests.
    """
    credentials = await find_credentials(database, username)
    if credentials is None or not credentials.enabled:
        return None
    if not await asyncio.to_thread(verify_password, password, credentials.password_hash):
        return None
    return credentials.operator_id
