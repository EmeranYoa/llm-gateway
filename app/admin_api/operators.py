"""Operator accounts: list, create, reset a password, disable and enable them, and
let each operator change their own password and the language of the dashboard.

Actions on accounts ask for the current password of the operator again
(`current_password`): a session left open on someone else's screen is not
enough to take over the other accounts. Every change to an account is recorded
in the history of admin actions, never with a password, a hash or a token.

An account created or reset by another operator must change its password
before anything else (see `require_password_changed` in `dependencies.py`).
"""

import asyncio
import dataclasses
import datetime as dt
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin_api.dependencies import Admin, Database, SignedIn
from app.admin_api.schemas import Me
from app.admin_api.sessions import Username
from app.api.routes import error_response
from app.auth import passwords
from app.auth.passwords import hash_password, password_problem, verify_password
from app.schemas import ErrorBody
from app.storage.admin_actions import Actor
from app.storage.operators import (
    LastEnabledOperator,
    OperatorIdentity,
    OperatorInfo,
    change_own_password,
    create_operator,
    disable_operator,
    enable_operator,
    find_operator,
    find_password_hash,
    list_operators,
    reset_password,
    set_language,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v1")

PasswordText = Annotated[str, Field(max_length=passwords.MAX_LENGTH)]
"""No password can be longer: refusing longer ones keeps scrypt fast."""


# --- Request and response bodies ---


class Operator(BaseModel):
    """An operator account. Never its password nor its hash."""

    id: int
    username: str
    enabled: bool
    """A disabled account cannot sign in, and its sessions were closed."""
    must_change_password: bool
    """True when the operator must choose a new password before anything else."""
    created_at: dt.datetime
    last_sign_in_at: dt.datetime | None
    """null until the first sign-in."""


class Operators(BaseModel):
    """Every operator account, in alphabetical order."""

    operators: list[Operator]


class Reauthentication(BaseModel):
    """Confirm an action on accounts with the current password of the operator."""

    model_config = ConfigDict(extra="forbid")

    current_password: PasswordText


class NewOperatorRequest(Reauthentication):
    """Create an operator account. Its owner must change the password at the first sign-in."""

    username: Username
    password: PasswordText
    """12 to 256 characters, and not the username."""


class PasswordResetRequest(Reauthentication):
    """Give another operator a new password, which they must change at the next sign-in."""

    password: PasswordText
    """12 to 256 characters, and not the username."""


class OwnPasswordChange(Reauthentication):
    """Change one's own password."""

    new_password: PasswordText
    """12 to 256 characters, not the username, and not the current password."""


class LanguageChoice(BaseModel):
    """Choose the language of the dashboard."""

    model_config = ConfigDict(extra="forbid")

    language: Literal["en", "fr"] | None
    """null: follow the language of the browser."""


# --- Routes ---
# Errors are returned as `JSONResponse` in OpenAI format, so each route names its
# `response_model` for the OpenAPI schema instead of relying on its return type.


def _errors(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Document error answers in the OpenAPI schema."""
    return {status: {"model": ErrorBody} for status in statuses}


@router.get("/operators")
async def list_accounts(_: Admin, database: Database) -> Operators:
    """Return every operator account, enabled or not."""
    return Operators(operators=[_operator(found) for found in await list_operators(database)])


@router.post(
    "/operators", status_code=201, response_model=Operator, responses=_errors(400, 403, 409)
)
async def create_account(
    body: NewOperatorRequest, admin: Admin, database: Database, request: Request
) -> Operator | JSONResponse:
    """Create an operator account. Its owner must change the password at the first sign-in."""
    if not await reauthenticate(database, admin, body.current_password, request):
        return _reauthentication_failed()
    problem = password_problem(body.password, body.username)
    if problem is not None:
        return _invalid_password(problem, "password")
    password_hash = await asyncio.to_thread(hash_password, body.password)
    try:
        new_id = await create_operator(
            database, body.username, password_hash, must_change_password=True, actor=_actor(admin)
        )
    except IntegrityError:
        return error_response(
            409,
            f"An operator named '{body.username}' exists already.",
            "invalid_request_error",
            param="username",
            code="operator_exists",
        )
    created = await find_operator(database, new_id)
    assert created is not None  # accounts are disabled, never deleted
    return _operator(created)


@router.post(
    "/operators/{operator_id}/reset-password",
    response_model=Operator,
    responses=_errors(400, 403, 404),
)
async def reset_account_password(
    operator_id: int,
    body: PasswordResetRequest,
    admin: Admin,
    database: Database,
    request: Request,
) -> Operator | JSONResponse:
    """Give another operator a new password, and close all their sessions at once.

    They must change it at the next sign-in. To change one's own password, use
    `PUT /admin/v1/me/password` instead.
    """
    if not await reauthenticate(database, admin, body.current_password, request):
        return _reauthentication_failed()
    if operator_id == admin.operator_id:
        return error_response(
            400,
            "To change your own password, use PUT /admin/v1/me/password.",
            "invalid_request_error",
            code="use_own_password_change",
        )
    target = await find_operator(database, operator_id)
    if target is None:
        return _unknown_operator(operator_id)
    problem = password_problem(body.password, target.username)
    if problem is not None:
        return _invalid_password(problem, "password")
    password_hash = await asyncio.to_thread(hash_password, body.password)
    updated = await reset_password(database, operator_id, password_hash, actor=_actor(admin))
    return _unknown_operator(operator_id) if updated is None else _operator(updated)


@router.post(
    "/operators/{operator_id}/disable", response_model=Operator, responses=_errors(400, 403, 404)
)
async def disable_account(
    operator_id: int,
    body: Reauthentication,
    admin: Admin,
    database: Database,
    request: Request,
) -> Operator | JSONResponse:
    """Disable an operator account and close all its sessions at once.

    One cannot disable oneself, nor the last enabled account.
    """
    if not await reauthenticate(database, admin, body.current_password, request):
        return _reauthentication_failed()
    if operator_id == admin.operator_id:
        return error_response(
            400,
            "You cannot disable your own account.",
            "invalid_request_error",
            code="cannot_disable_self",
        )
    try:
        updated = await disable_operator(database, operator_id, actor=_actor(admin))
    except LastEnabledOperator:
        return error_response(
            400,
            "This is the last enabled operator account: it cannot be disabled.",
            "invalid_request_error",
            code="last_enabled_operator",
        )
    return _unknown_operator(operator_id) if updated is None else _operator(updated)


@router.post(
    "/operators/{operator_id}/enable", response_model=Operator, responses=_errors(403, 404)
)
async def enable_account(
    operator_id: int,
    body: Reauthentication,
    admin: Admin,
    database: Database,
    request: Request,
) -> Operator | JSONResponse:
    """Enable an operator account again: it can sign in with its password."""
    if not await reauthenticate(database, admin, body.current_password, request):
        return _reauthentication_failed()
    updated = await enable_operator(database, operator_id, actor=_actor(admin))
    return _unknown_operator(operator_id) if updated is None else _operator(updated)


@router.put("/me/password", response_model=Me, responses=_errors(400, 403))
async def change_password(
    body: OwnPasswordChange, operator: SignedIn, database: Database, request: Request
) -> Me | JSONResponse:
    """Change one's own password. Allowed, and needed, during a forced password change.

    The other sessions of the operator are closed; this one stays open.
    """
    if not await reauthenticate(database, operator, body.current_password, request):
        return _reauthentication_failed()
    problem = password_problem(body.new_password, operator.username)
    if problem is None and body.new_password == body.current_password:
        problem = "The new password must differ from the current one."
    if problem is not None:
        return _invalid_password(problem, "new_password")
    password_hash = await asyncio.to_thread(hash_password, body.new_password)
    await change_own_password(database, operator, password_hash)
    return _me(dataclasses.replace(operator, must_change_password=False))


@router.put("/me/language", response_model=Me)
async def change_language(body: LanguageChoice, operator: SignedIn, database: Database) -> Me:
    """Choose the language of the dashboard. No password needed: it is only a preference."""
    await set_language(database, operator.operator_id, body.language)
    return _me(dataclasses.replace(operator, language=body.language))


# --- Helpers ---


async def reauthenticate(
    database: AsyncEngine, operator: OperatorIdentity, password: str, request: Request
) -> bool:
    """Return True when `password` is the current password of `operator`.

    A failure is logged but never counts towards the sign-in lockout: the
    operator is signed in already. The hash is checked in a thread, like at sign-in.
    """
    password_hash = await find_password_hash(database, operator.operator_id)
    if password_hash is not None and await asyncio.to_thread(
        verify_password, password, password_hash
    ):
        return True
    client_ip = request.client.host if request.client else "unknown address"
    logger.warning("failed re-authentication of operator %s from %s", operator.username, client_ip)
    return False


def _actor(operator: OperatorIdentity) -> Actor:
    return Actor(operator.username, operator.operator_id)


def _operator(found: OperatorInfo) -> Operator:
    return Operator(**dataclasses.asdict(found))


def _me(operator: OperatorIdentity) -> Me:
    return Me(
        username=operator.username,
        must_change_password=operator.must_change_password,
        language=operator.language,
    )


def _reauthentication_failed() -> JSONResponse:
    return error_response(
        403,
        "Wrong current password.",
        "invalid_request_error",
        param="current_password",
        code="reauthentication_failed",
    )


def _invalid_password(problem: str, param: str) -> JSONResponse:
    return error_response(
        400, problem, "invalid_request_error", param=param, code="invalid_password"
    )


def _unknown_operator(operator_id: int) -> JSONResponse:
    return error_response(
        404,
        f"No operator account with id {operator_id}.",
        "invalid_request_error",
        code="operator_not_found",
    )
