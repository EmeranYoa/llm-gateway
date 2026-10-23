"""Operator accounts and their sessions, stored in PostgreSQL.

Operators sign in to the admin API (and the dashboard) with a username and a
password. Only a scrypt hash of the password is stored (`app/auth/passwords.py`),
and only the SHA-256 hash of a session token. A username is stored as typed but
is unique whatever the case: "Alice" and "alice" are the same account.

Sessions are looked up on every admin request, with no cache: signing out,
disabling an account or the end of a session takes effect at once.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    delete,
    exists,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.keys import hash_key
from app.auth.sessions import SESSION_LIFETIME, generate_session_token
from app.storage.admin_actions import Action, Actor, record_action
from app.storage.db import Base


class OperatorRow(Base):
    """An operator account. Only the hash of the password is stored."""

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(Text)
    """As typed at creation. Unique whatever the case (index below)."""
    password_hash: Mapped[str] = mapped_column(Text)
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default="false")
    language: Mapped[str | None] = mapped_column(Text)
    """Language of the dashboard chosen by the operator; NULL: the browser's language."""
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    failed_attempts: Mapped[int] = mapped_column(server_default="0")
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_sign_in_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


Index("operators_username_lower_key", func.lower(OperatorRow.username), unique=True)


class OperatorSessionRow(Base):
    """A session of an operator. Only the hash of its token is stored."""

    __tablename__ = "operator_sessions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class OperatorIdentity:
    """Who a valid session belongs to: what every admin route knows about its caller."""

    operator_id: int
    username: str
    must_change_password: bool
    language: str | None
    session_id: int


@dataclass(frozen=True)
class OperatorCredentials:
    """What signing in needs to know about an account."""

    operator_id: int
    username: str
    password_hash: str
    enabled: bool


@dataclass(frozen=True)
class NewSession:
    """A session just opened. `token` is the only time the full token is available."""

    token: str
    username: str
    expires_at: dt.datetime


@dataclass(frozen=True)
class OperatorInfo:
    """An operator account as the admin API lists it. Never its password hash."""

    id: int
    username: str
    enabled: bool
    must_change_password: bool
    created_at: dt.datetime
    last_sign_in_at: dt.datetime | None


_INFO_COLUMNS = (
    OperatorRow.id,
    OperatorRow.username,
    OperatorRow.enabled,
    OperatorRow.must_change_password,
    OperatorRow.created_at,
    OperatorRow.last_sign_in_at,
)


class LastEnabledOperator(Exception):
    """Disabling this account would leave no enabled operator: nobody could sign in."""


async def any_operator_exists(engine: AsyncEngine) -> bool:
    """Return True when at least one operator account exists, enabled or not."""
    async with engine.connect() as connection:
        return bool(await connection.scalar(select(exists().select_from(OperatorRow))))


async def create_operator(
    engine: AsyncEngine,
    username: str,
    password_hash: str,
    *,
    must_change_password: bool = False,
    actor: Actor | None = None,
) -> int:
    """Create an operator account and return its id. With `actor`, record the action.

    Raises `IntegrityError` when the username exists already, whatever its case.
    """
    async with engine.begin() as connection:
        return await _insert_operator(
            connection, username, password_hash, must_change_password, actor
        )


async def create_first_operator(
    engine: AsyncEngine, username: str, password_hash: str, *, actor: Actor
) -> NewSession | None:
    """Create the first operator account and open a session for it.

    Returns None, and creates nothing, when an operator exists already. The check
    and the creation are atomic: the table is locked against every other write
    until the transaction ends, so two concurrent setups can never both find it
    empty. Exactly one of them creates an account.
    """
    async with engine.begin() as connection:
        # SHARE ROW EXCLUSIVE conflicts with itself and with every insert, update
        # and delete. It is released at the end of the transaction.
        await connection.execute(text("LOCK TABLE operators IN SHARE ROW EXCLUSIVE MODE"))
        if await connection.scalar(select(exists().select_from(OperatorRow))):
            return None
        operator_id = await _insert_operator(connection, username, password_hash, False, actor)
        return await _open_session(connection, operator_id, username)


async def find_credentials(engine: AsyncEngine, username: str) -> OperatorCredentials | None:
    """Return the account named `username` (whatever the case), or None when there is none."""
    query = select(
        OperatorRow.id, OperatorRow.username, OperatorRow.password_hash, OperatorRow.enabled
    ).where(func.lower(OperatorRow.username) == func.lower(username))
    async with engine.connect() as connection:
        row = (await connection.execute(query)).first()
    return None if row is None else OperatorCredentials(*row)


async def open_session(engine: AsyncEngine, operator_id: int) -> NewSession:
    """Open a session for an operator whose password was checked: a sign-in.

    The expired sessions of the operator are deleted at the same time, so they
    never pile up.
    """
    async with engine.begin() as connection:
        await connection.execute(
            delete(OperatorSessionRow).where(
                OperatorSessionRow.operator_id == operator_id,
                OperatorSessionRow.expires_at <= dt.datetime.now(dt.UTC),
            )
        )
        username = await connection.scalar(
            select(OperatorRow.username).where(OperatorRow.id == operator_id)
        )
        assert username is not None
        return await _open_session(connection, operator_id, username)


async def find_session_operator(engine: AsyncEngine, token: str) -> OperatorIdentity | None:
    """Return who owns the session `token`, or None.

    None when the token is unknown, the session has expired or the account is disabled.
    """
    query = (
        select(
            OperatorRow.id,
            OperatorRow.username,
            OperatorRow.must_change_password,
            OperatorRow.language,
            OperatorSessionRow.id,
        )
        .join(OperatorRow, OperatorRow.id == OperatorSessionRow.operator_id)
        .where(
            OperatorSessionRow.token_hash == hash_key(token),
            OperatorSessionRow.expires_at > dt.datetime.now(dt.UTC),
            OperatorRow.enabled,
        )
    )
    async with engine.connect() as connection:
        row = (await connection.execute(query)).first()
    return None if row is None else OperatorIdentity(*row)


async def close_session(engine: AsyncEngine, session_id: int) -> None:
    """Delete a session: its token is refused from now on (sign-out)."""
    async with engine.begin() as connection:
        await connection.execute(
            delete(OperatorSessionRow).where(OperatorSessionRow.id == session_id)
        )


async def recover_operator(
    engine: AsyncEngine, username: str, password_hash: str, *, actor: Actor
) -> str | None:
    """Give back access to the account named `username` (whatever the case): recovery mode.

    In one transaction: set the new password, to be changed at the next sign-in,
    enable the account, clear its failed sign-ins and its lock, end all its
    sessions and record the action. Returns the username as stored, or None,
    changing nothing, when there is no such account.
    """
    async with engine.begin() as connection:
        row = (
            await connection.execute(
                update(OperatorRow)
                .where(func.lower(OperatorRow.username) == func.lower(username))
                .values(
                    password_hash=password_hash,
                    must_change_password=True,
                    enabled=True,
                    failed_attempts=0,
                    locked_until=None,
                )
                .returning(OperatorRow.id, OperatorRow.username)
            )
        ).first()
        if row is None:
            return None
        recovered_id, recovered_username = row
        await _close_sessions(connection, recovered_id)
        # Never the password nor its hash: the username is enough to know who was recovered.
        await record_action(connection, actor, Action.RECOVER_OPERATOR, recovered_username, {})
        return str(recovered_username)


async def list_operators(engine: AsyncEngine) -> list[OperatorInfo]:
    """Return every operator account, enabled or not, in alphabetical order."""
    query = select(*_INFO_COLUMNS).order_by(func.lower(OperatorRow.username))
    async with engine.connect() as connection:
        rows = (await connection.execute(query)).all()
    return [OperatorInfo(*row) for row in rows]


async def find_operator(engine: AsyncEngine, operator_id: int) -> OperatorInfo | None:
    """Return the operator account `operator_id`, or None when there is none."""
    async with engine.connect() as connection:
        row = (
            await connection.execute(select(*_INFO_COLUMNS).where(OperatorRow.id == operator_id))
        ).first()
    return None if row is None else OperatorInfo(*row)


async def find_password_hash(engine: AsyncEngine, operator_id: int) -> str | None:
    """Return the password hash of the operator `operator_id`, or None when there is none."""
    async with engine.connect() as connection:
        found = await connection.scalar(
            select(OperatorRow.password_hash).where(OperatorRow.id == operator_id)
        )
    return None if found is None else str(found)


async def reset_password(
    engine: AsyncEngine, operator_id: int, password_hash: str, *, actor: Actor
) -> OperatorInfo | None:
    """Give an operator a new password set by another operator, and record the action.

    The operator must change it at the next sign-in, and all its sessions are
    closed at once. Returns None, and changes nothing, when the account does not exist.
    """
    async with engine.begin() as connection:
        operator = await _update_operator(
            connection, operator_id, password_hash=password_hash, must_change_password=True
        )
        if operator is None:
            return None
        await _close_sessions(connection, operator_id)
        await record_action(connection, actor, Action.RESET_PASSWORD, operator.username, {})
        return operator


async def disable_operator(
    engine: AsyncEngine, operator_id: int, *, actor: Actor
) -> OperatorInfo | None:
    """Disable an operator account, close all its sessions and record the action.

    Returns None, and changes nothing, when the account does not exist. Raises
    `LastEnabledOperator`, and changes nothing, when no other enabled account
    would remain. The check and the change are atomic: the table is locked
    against every other write until the transaction ends, so two operators who
    disable each other at the same time can never leave zero enabled accounts.
    """
    async with engine.begin() as connection:
        # SHARE ROW EXCLUSIVE conflicts with itself and with every insert, update
        # and delete. It is released at the end of the transaction.
        await connection.execute(text("LOCK TABLE operators IN SHARE ROW EXCLUSIVE MODE"))
        operator = await _update_operator(connection, operator_id, enabled=False)
        if operator is None:
            return None
        if not await connection.scalar(select(exists().where(OperatorRow.enabled))):
            raise LastEnabledOperator  # leaving the block rolls the change back
        await _close_sessions(connection, operator_id)
        await record_action(connection, actor, Action.DISABLE_OPERATOR, operator.username, {})
        return operator


async def enable_operator(
    engine: AsyncEngine, operator_id: int, *, actor: Actor
) -> OperatorInfo | None:
    """Enable an operator account again and record the action.

    Returns None, and changes nothing, when the account does not exist.
    """
    async with engine.begin() as connection:
        operator = await _update_operator(connection, operator_id, enabled=True)
        if operator is not None:
            await record_action(connection, actor, Action.ENABLE_OPERATOR, operator.username, {})
        return operator


async def change_own_password(
    engine: AsyncEngine, operator: OperatorIdentity, password_hash: str
) -> None:
    """Change the password of the operator signed in, and record the action.

    The forced change, if any, is done. The other sessions of the operator are
    closed; the session of the request stays open.
    """
    async with engine.begin() as connection:
        await _update_operator(
            connection,
            operator.operator_id,
            password_hash=password_hash,
            must_change_password=False,
        )
        await connection.execute(
            delete(OperatorSessionRow).where(
                OperatorSessionRow.operator_id == operator.operator_id,
                OperatorSessionRow.id != operator.session_id,
            )
        )
        actor = Actor(operator.username, operator.operator_id)
        await record_action(connection, actor, Action.CHANGE_OWN_PASSWORD, operator.username, {})


async def set_language(engine: AsyncEngine, operator_id: int, language: str | None) -> None:
    """Store the language of the dashboard chosen by an operator. None: the browser's language.

    A preference, not an admin action: it is not recorded in the history.
    """
    async with engine.begin() as connection:
        await _update_operator(connection, operator_id, language=language)


async def _update_operator(
    connection: AsyncConnection, operator_id: int, **values: object
) -> OperatorInfo | None:
    row = (
        await connection.execute(
            update(OperatorRow)
            .where(OperatorRow.id == operator_id)
            .values(**values)
            .returning(*_INFO_COLUMNS)
        )
    ).first()
    return None if row is None else OperatorInfo(*row)


async def _close_sessions(connection: AsyncConnection, operator_id: int) -> None:
    """Delete every session of an operator: their tokens are refused from now on."""
    await connection.execute(
        delete(OperatorSessionRow).where(OperatorSessionRow.operator_id == operator_id)
    )


async def _insert_operator(
    connection: AsyncConnection,
    username: str,
    password_hash: str,
    must_change_password: bool,
    actor: Actor | None,
) -> int:
    operator_id = await connection.scalar(
        insert(OperatorRow)
        .values(
            username=username,
            password_hash=password_hash,
            must_change_password=must_change_password,
            created_at=dt.datetime.now(dt.UTC),
        )
        .returning(OperatorRow.id)
    )
    assert operator_id is not None
    if actor is not None:
        # Never the password nor its hash: the username is enough to know who was created.
        await record_action(connection, actor, Action.CREATE_OPERATOR, username, {})
    return int(operator_id)


async def _open_session(connection: AsyncConnection, operator_id: int, username: str) -> NewSession:
    token = generate_session_token()
    now = dt.datetime.now(dt.UTC)
    expires_at = now + SESSION_LIFETIME
    await connection.execute(
        insert(OperatorSessionRow).values(
            token_hash=hash_key(token),
            operator_id=operator_id,
            created_at=now,
            expires_at=expires_at,
        )
    )
    await connection.execute(
        update(OperatorRow).where(OperatorRow.id == operator_id).values(last_sign_in_at=now)
    )
    return NewSession(token=token, username=username, expires_at=expires_at)
