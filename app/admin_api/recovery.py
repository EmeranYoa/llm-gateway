"""Recovery of an operator account, with a one-time recovery token.

When the only operator forgot their password, or every account is disabled or
locked, nobody can sign in to fix it. The person who runs the gateway then
starts the admin API with `OPERATOR_RECOVERY=true`: it generates a random
recovery token at startup and prints it once in its log, like the setup token
(`setup.py`). With it, the dashboard sets a new password for one account,
enables and unlocks it, and ends all its sessions. The operator then signs in
normally and must choose another password.

The token works once. The mode stays on until the variable is removed and the
admin API restarted, so `GET /admin/v1/recovery` keeps reporting it, and the
dashboard keeps showing a warning, until then.
"""

import asyncio
import logging
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.admin_api.dependencies import Database
from app.admin_api.one_time_tokens import OneTimeToken
from app.admin_api.schemas import RecoveredOperator, RecoveryStatus
from app.admin_api.sessions import Username
from app.api.routes import error_response
from app.auth.passwords import hash_password, password_problem
from app.schemas import ErrorBody
from app.storage.admin_actions import RECOVERY
from app.storage.operators import recover_operator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v1")


class RecoveryMode:
    """The recovery mode of this admin API instance: on or off, and its one-time token."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.token = OneTimeToken()
        # One recovery at a time, so two requests sent at once with the token
        # cannot both use it: the token is consumed only after the commit.
        self.lock = asyncio.Lock()


def announce_recovery_token(recovery: RecoveryMode) -> None:
    """At startup, generate and print a recovery token when the recovery mode is on."""
    if not recovery.enabled:
        return
    token = recovery.token.generate()
    # A secret printed on purpose, like the setup token: the server log is the one
    # channel that only the person who runs the gateway can read, and that person
    # chose to turn this mode on. The token works once and is never stored. It
    # stays the last word of the line, so it is easy to copy.
    logger.warning(
        "Recovery mode is on (OPERATOR_RECOVERY): turn it off once done. To give back"
        " access to an operator account, open the dashboard and enter this one-time"
        " recovery token: %s",
        token,
    )


class RecoveryRequest(BaseModel):
    """Give back access to an operator account with the recovery token printed in the log."""

    model_config = ConfigDict(extra="forbid")

    token: str
    username: Username
    new_password: str
    """12 to 256 characters, and not the username."""


@router.get("/recovery")
async def recovery_status(request: Request) -> RecoveryStatus:
    """Tell whether the recovery mode is on. No session needed."""
    return RecoveryStatus(enabled=_recovery(request).enabled)


@router.post(
    "/recovery",
    response_model=RecoveredOperator,
    responses={
        400: {"model": ErrorBody, "description": "Password refused"},
        401: {"model": ErrorBody, "description": "Wrong recovery token"},
        404: {
            "model": ErrorBody,
            "description": "Recovery mode off, token already used, or unknown username",
        },
    },
)
async def recover(
    body: RecoveryRequest, request: Request, database: Database
) -> RecoveredOperator | JSONResponse:
    """Set a new password for an operator account, and enable and unlock it.

    No session needed: the recovery token is enough. Every session of the account
    ends. No session is opened: the operator signs in with the new password, then
    must choose another one.
    """
    recovery = _recovery(request)
    if not recovery.enabled:
        return error_response(
            404,
            "Recovery mode is off. Set OPERATOR_RECOVERY=true and restart the admin API.",
            "invalid_request_error",
            code="recovery_disabled",
        )
    async with recovery.lock:
        if not recovery.token.available:
            return error_response(
                404,
                "The recovery token was used already. Restart the admin API for a new one.",
                "invalid_request_error",
                code="recovery_used",
            )
        if not recovery.token.matches(body.token):
            client_ip = request.client.host if request.client else "unknown address"
            logger.warning("refused a recovery request from %s: wrong recovery token", client_ip)
            return error_response(
                401, "Wrong recovery token.", "invalid_request_error", code="invalid_recovery_token"
            )
        problem = password_problem(body.new_password, body.username)
        if problem is not None:
            return error_response(
                400, problem, "invalid_request_error", param="new_password", code="invalid_password"
            )
        password_hash = await asyncio.to_thread(hash_password, body.new_password)
        username = await recover_operator(database, body.username, password_hash, actor=RECOVERY)
        if username is None:
            return error_response(
                404,
                "No operator account has this username.",
                "invalid_request_error",
                param="username",
                code="operator_not_found",
            )
        recovery.token.consume()
    logger.warning("recovered the operator account %s: turn OPERATOR_RECOVERY off now", username)
    return RecoveredOperator(username=username)


def _recovery(request: Request) -> RecoveryMode:
    return cast(RecoveryMode, request.app.state.recovery)
