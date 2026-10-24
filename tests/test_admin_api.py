"""Tests for the admin API: a separate application, closed to the public, opened by
operator accounts. The first account is created with a one-time setup token; then
operators sign in with a username and a password and get a session token."""

import asyncio
import datetime as dt
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.admin_api.main import create_admin_app
from app.auth.keys import hash_key
from app.auth.passwords import hash_password
from app.config import Settings
from app.storage.operators import create_operator, open_session
from tests.conftest import MINIMAL_CONFIG, DatabaseProxy, gateway_client, new_api_key
from tests.upstream import CHAT_REQUEST

WriteConfig = Callable[[str], Settings]

PASSWORD = "a long enough password"


@asynccontextmanager
async def admin_client(settings: Settings, token: str | None) -> AsyncIterator[AsyncClient]:
    """Start the admin API with `settings` and yield a client that sends the session `token`."""
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    app = create_admin_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://admin-api", headers=headers
        ) as client,
    ):
        yield client


async def new_session(
    database_url: str, username: str | None = None, password: str = PASSWORD
) -> str:
    """Create an operator and a session for it, without HTTP. Returns the session token."""
    engine = create_async_engine(database_url)
    try:
        operator_id = await create_operator(
            engine, username or unique_username(), hash_password(password)
        )
        session = await open_session(engine, operator_id)
    finally:
        await engine.dispose()
    return session.token


def unique_username() -> str:
    return f"operator-{uuid4().hex[:8]}"


async def run_sql(database_url: str, statement: str, **parameters: Any) -> list[Any]:
    """Run one SQL statement in its own transaction; return the first column of its rows."""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(statement), parameters)
            return list(result.scalars()) if result.returns_rows else []
    finally:
        await engine.dispose()


async def action_rows(database_url: str) -> list[dict[str, Any]]:
    """Every row of `admin_actions`, oldest first."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT * FROM admin_actions ORDER BY id"))
            return [dict(row) for row in result.mappings()]
    finally:
        await engine.dispose()


async def operator_id(database_url: str, username: str) -> int:
    [found] = await run_sql(
        database_url, "SELECT id FROM operators WHERE username = :u", u=username
    )
    return int(found)


def setup_tokens(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The setup tokens printed in the log: the last word of the setup log line."""
    return [
        record.getMessage().split()[-1]
        for record in caplog.records
        if record.name == "app.admin_api.setup" and "one-time setup token" in record.getMessage()
    ]


@pytest.fixture
def settings(write_config: WriteConfig) -> Settings:
    return write_config(MINIMAL_CONFIG)


@pytest.fixture
async def no_operator(database_url: str) -> None:
    """Remove every operator account (and their sessions), as on a new installation."""
    await run_sql(database_url, "DELETE FROM operators")


@pytest.fixture
async def actions(database_url: str) -> None:
    """Empty the history of admin actions."""
    await run_sql(database_url, "TRUNCATE admin_actions")


# --- Setup of the first account ---


async def test_setup_is_open_and_its_token_logged_while_no_operator_exists(
    settings: Settings, no_operator: None, caplog: pytest.LogCaptureFixture
) -> None:
    async with admin_client(settings, None) as client:
        response = await client.get("/admin/v1/setup")

    assert response.status_code == 200
    assert response.json() == {"open": True}
    [token] = setup_tokens(caplog)
    [record] = [r for r in caplog.records if r.name == "app.admin_api.setup"]
    assert record.levelno == logging.WARNING
    assert len(token) > 40


async def test_setup_creates_the_first_operator_and_signs_it_in(
    settings: Settings,
    database_url: str,
    no_operator: None,
    actions: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    username = unique_username()

    async with admin_client(settings, None) as client:
        [token] = setup_tokens(caplog)
        response = await client.post(
            "/admin/v1/setup", json={"token": token, "username": username, "password": PASSWORD}
        )
        session = response.json()
        me = await client.get(
            "/admin/v1/me", headers={"Authorization": f"Bearer {session['token']}"}
        )
        status = await client.get("/admin/v1/setup")
        again = await client.post(
            "/admin/v1/setup",
            json={"token": token, "username": unique_username(), "password": PASSWORD},
        )

    assert response.status_code == 201
    assert set(session) == {"token", "username", "expires_at"}
    assert session["username"] == username
    assert session["token"].startswith("gws_")
    assert me.status_code == 200
    assert me.json() == {"username": username, "must_change_password": False, "language": None}
    assert status.json() == {"open": False}
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "setup_closed"
    rows = await action_rows(database_url)
    [action] = rows
    assert action["actor"] == "setup"
    assert action["action"] == "create-operator"
    assert action["target"] == username
    assert action["operator_id"] is None
    history = str(rows)
    for secret in (PASSWORD, token, session["token"], hash_key(session["token"])):
        assert secret not in history
    [stored_hash] = await run_sql(
        database_url, "SELECT password_hash FROM operators WHERE username = :u", u=username
    )
    assert stored_hash.startswith("scrypt$")
    assert PASSWORD not in stored_hash


async def test_setup_refuses_a_wrong_token(
    settings: Settings, database_url: str, no_operator: None
) -> None:
    async with admin_client(settings, None) as client:
        response = await client.post(
            "/admin/v1/setup",
            json={"token": "not-the-token", "username": "alice", "password": PASSWORD},
        )
        status = await client.get("/admin/v1/setup")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_setup_token"
    assert status.json() == {"open": True}
    assert await run_sql(database_url, "SELECT count(*) FROM operators") == [0]


@pytest.mark.parametrize(
    ("password", "message"),
    [("too short", "at least 12 characters"), ("alice-the-operator", "not be the username")],
    ids=["too-short", "same-as-username"],
)
async def test_setup_refuses_an_invalid_password(
    settings: Settings,
    database_url: str,
    no_operator: None,
    caplog: pytest.LogCaptureFixture,
    password: str,
    message: str,
) -> None:
    async with admin_client(settings, None) as client:
        [token] = setup_tokens(caplog)
        response = await client.post(
            "/admin/v1/setup",
            json={"token": token, "username": "Alice-the-Operator", "password": password},
        )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_password"
    assert error["param"] == "password"
    assert message in error["message"]
    assert password not in error["message"]
    assert await run_sql(database_url, "SELECT count(*) FROM operators") == [0]


async def test_setup_is_closed_when_an_operator_exists(
    settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    await new_session(database_url)

    async with admin_client(settings, None) as client:
        status = await client.get("/admin/v1/setup")
        response = await client.post(
            "/admin/v1/setup",
            json={"token": "any-token", "username": "mallory", "password": PASSWORD},
        )

    assert setup_tokens(caplog) == []
    assert status.json() == {"open": False}
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "setup_closed"


async def test_concurrent_setups_create_exactly_one_operator(
    settings: Settings, database_url: str, no_operator: None, caplog: pytest.LogCaptureFixture
) -> None:
    async with admin_client(settings, None) as client:
        [token] = setup_tokens(caplog)
        responses = await asyncio.gather(
            *(
                client.post(
                    "/admin/v1/setup",
                    json={"token": token, "username": unique_username(), "password": PASSWORD},
                )
                for _ in range(5)
            )
        )

    assert sorted(response.status_code for response in responses) == [201, 404, 404, 404, 404]
    assert await run_sql(database_url, "SELECT count(*) FROM operators") == [1]


async def test_setup_token_is_printed_even_when_postgresql_is_down(
    write_config: WriteConfig,
    database_proxy: DatabaseProxy,
    no_operator: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = write_config(MINIMAL_CONFIG).model_copy(update={"database_url": database_proxy.url})
    await database_proxy.stop()

    async with admin_client(settings, None) as client:
        status = await client.get("/admin/v1/setup")

    assert len(setup_tokens(caplog)) == 1
    assert status.status_code == 503
    assert status.json()["error"]["code"] == "database_unavailable"


# --- Sessions ---


async def test_sign_in_opens_a_session_of_eight_hours(
    settings: Settings, database_url: str
) -> None:
    username = unique_username()
    await new_session(database_url, username)
    started = dt.datetime.now(dt.UTC)

    async with admin_client(settings, None) as client:
        response = await client.post(
            "/admin/v1/sessions", json={"username": username, "password": PASSWORD}
        )
        session = response.json()
        me = await client.get(
            "/admin/v1/me", headers={"Authorization": f"Bearer {session['token']}"}
        )

    assert response.status_code == 201
    assert session["username"] == username
    assert session["token"].startswith("gws_")
    expires_at = dt.datetime.fromisoformat(session["expires_at"])
    assert expires_at.utcoffset() == dt.timedelta(0)
    eight_hours = dt.timedelta(hours=8)
    assert started + eight_hours <= expires_at <= dt.datetime.now(dt.UTC) + eight_hours
    assert me.json()["username"] == username
    # Only the hash of the token is stored.
    stored = await run_sql(database_url, "SELECT token_hash FROM operator_sessions")
    assert hash_key(session["token"]) in stored
    assert session["token"] not in stored
    [last_sign_in] = await run_sql(
        database_url, "SELECT last_sign_in_at FROM operators WHERE username = :u", u=username
    )
    assert last_sign_in >= started


async def test_usernames_are_case_insensitive(settings: Settings, database_url: str) -> None:
    username = f"Alice-{uuid4().hex[:8]}"
    await new_session(database_url, username)

    async with admin_client(settings, None) as client:
        response = await client.post(
            "/admin/v1/sessions", json={"username": username.lower(), "password": PASSWORD}
        )

    assert response.status_code == 201
    assert response.json()["username"] == username  # as typed at creation
    with pytest.raises(IntegrityError):
        await new_session(database_url, username.upper())


async def test_sign_in_failures_all_look_the_same(settings: Settings, database_url: str) -> None:
    username = unique_username()
    disabled = unique_username()
    await new_session(database_url, username)
    await new_session(database_url, disabled)
    await run_sql(
        database_url, "UPDATE operators SET enabled = false WHERE username = :u", u=disabled
    )

    async with admin_client(settings, None) as client:
        wrong_password = await client.post(
            "/admin/v1/sessions", json={"username": username, "password": "not the password"}
        )
        unknown_user = await client.post(
            "/admin/v1/sessions", json={"username": "nobody-at-all", "password": PASSWORD}
        )
        disabled_account = await client.post(
            "/admin/v1/sessions", json={"username": disabled, "password": PASSWORD}
        )

    for response in (wrong_password, unknown_user, disabled_account):
        assert response.status_code == 401
        assert response.json() == wrong_password.json()
    assert wrong_password.json()["error"]["code"] == "invalid_credentials"


async def test_sign_in_deletes_the_expired_sessions_of_the_operator(
    settings: Settings, database_url: str
) -> None:
    username = unique_username()
    old_token = await new_session(database_url, username)
    await new_session(database_url)  # another operator: its sessions stay
    await run_sql(
        database_url,
        "UPDATE operator_sessions SET expires_at = now() - interval '1 minute'"
        " WHERE token_hash = :h",
        h=hash_key(old_token),
    )
    before = await run_sql(database_url, "SELECT count(*) FROM operator_sessions")

    async with admin_client(settings, None) as client:
        await client.post("/admin/v1/sessions", json={"username": username, "password": PASSWORD})

    assert await run_sql(database_url, "SELECT count(*) FROM operator_sessions") == before
    assert await run_sql(
        database_url,
        "SELECT count(*) FROM operator_sessions WHERE token_hash = :h",
        h=hash_key(old_token),
    ) == [0]


async def test_me_describes_the_operator_of_the_session(
    settings: Settings, database_url: str
) -> None:
    username = unique_username()
    token = await new_session(database_url, username)
    await run_sql(
        database_url,
        "UPDATE operators SET must_change_password = true, language = 'fr' WHERE username = :u",
        u=username,
    )

    async with admin_client(settings, token) as client:
        response = await client.get("/admin/v1/me")

    assert response.status_code == 200
    assert response.json() == {"username": username, "must_change_password": True, "language": "fr"}


async def test_sign_out_ends_the_session_at_once(settings: Settings, database_url: str) -> None:
    token = await new_session(database_url)

    async with admin_client(settings, token) as client:
        before = await client.get("/admin/v1/me")
        signed_out = await client.delete("/admin/v1/sessions/current")
        after = await client.get("/admin/v1/me")

    assert before.status_code == 200
    assert signed_out.status_code == 204
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "invalid_session"


async def test_an_expired_session_is_refused(settings: Settings, database_url: str) -> None:
    token = await new_session(database_url)

    async with admin_client(settings, token) as client:
        before = await client.get("/admin/v1/me")
        await run_sql(
            database_url,
            "UPDATE operator_sessions SET expires_at = now() - interval '1 second'"
            " WHERE token_hash = :h",
            h=hash_key(token),
        )
        after = await client.get("/admin/v1/me")

    assert before.status_code == 200
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "invalid_session"


async def test_the_session_of_a_disabled_operator_is_refused_at_once(
    settings: Settings, database_url: str
) -> None:
    username = unique_username()
    token = await new_session(database_url, username)

    async with admin_client(settings, token) as client:
        before = await client.get("/admin/v1/me")
        await run_sql(
            database_url, "UPDATE operators SET enabled = false WHERE username = :u", u=username
        )
        after = await client.get("/admin/v1/me")

    assert before.status_code == 200
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "invalid_session"


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer gws_not-a-real-session", "gws_without-bearer", "Basic abc"],
    ids=["missing", "unknown", "no-scheme", "other-scheme"],
)
async def test_admin_api_refuses_requests_without_a_valid_session(
    settings: Settings, authorization: str | None
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    async with admin_client(settings, None) as client:
        response = await client.get("/admin/v1/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


async def test_tenant_key_does_not_open_the_admin_api(
    settings: Settings, database_url: str
) -> None:
    tenant_key = await new_api_key(database_url)

    async with admin_client(settings, tenant_key) as client:
        response = await client.get("/admin/v1/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


async def test_session_token_does_not_open_the_gateway(
    settings: Settings, database_url: str
) -> None:
    token = await new_session(database_url)

    async with gateway_client(settings, api_key=token) as client:
        response = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


async def test_sessions_cannot_be_checked_when_postgresql_is_down(
    write_config: WriteConfig, database_url: str, database_proxy: DatabaseProxy
) -> None:
    settings = write_config(MINIMAL_CONFIG).model_copy(update={"database_url": database_proxy.url})
    token = await new_session(database_url)

    async with admin_client(settings, token) as client:
        before = await client.get("/admin/v1/me")
        await database_proxy.stop()
        after = await client.get("/admin/v1/me")

    assert before.status_code == 200
    # Fail closed: a session that cannot be checked is never accepted.
    assert after.status_code == 503
    assert after.json()["error"]["code"] == "authentication_unavailable"


async def test_admin_api_health_needs_no_session(settings: Settings) -> None:
    async with admin_client(settings, None) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_api_is_never_published_by_docker_compose() -> None:
    # Defence in depth: even a leaked session token is useless from outside the
    # internal network, because nothing outside can reach the admin API.
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    admin_api = compose["services"]["admin-api"]

    assert "ports" not in admin_api
    assert "8001" in " ".join(admin_api["command"])
    assert "app.admin_api.main:create_admin_app" in " ".join(admin_api["command"])


def test_admin_api_runs_one_worker_only_in_docker_compose() -> None:
    # The setup and recovery tokens and the per-address sign-in limit live in one
    # process. An explicit `--workers` wins over WEB_CONCURRENCY from `.env`.
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    command = compose["services"]["admin-api"]["command"]

    assert "--workers" in command
    assert command[command.index("--workers") + 1] == "1"


def test_gateway_reads_web_concurrency_with_two_workers_by_default() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["gateway"]["environment"]

    assert environment["WEB_CONCURRENCY"] == "${WEB_CONCURRENCY:-2}"
