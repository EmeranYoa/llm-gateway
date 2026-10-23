"""Tests for the recovery mode of the admin API: with `OPERATOR_RECOVERY` on, a
one-time recovery token printed in the log gives back access to an operator
account whose password is lost, or which is disabled or locked."""

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from tests.conftest import MINIMAL_CONFIG, DatabaseProxy
from tests.test_admin_api import (
    PASSWORD,
    WriteConfig,
    action_rows,
    admin_client,
    new_session,
    run_sql,
    unique_username,
)

NEW_PASSWORD = "a brand new long password"


def recovery_tokens(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The recovery tokens printed in the log: the last word of the recovery log line."""
    return [
        record.getMessage().split()[-1]
        for record in caplog.records
        if record.name == "app.admin_api.recovery" and "recovery token" in record.getMessage()
    ]


@pytest.fixture
def settings(write_config: WriteConfig) -> Settings:
    return write_config(MINIMAL_CONFIG)


@pytest.fixture
def recovery_settings(settings: Settings) -> Settings:
    """Settings with `OPERATOR_RECOVERY=true`."""
    return settings.model_copy(update={"operator_recovery": True})


@pytest.fixture
async def actions(database_url: str) -> None:
    """Empty the history of admin actions."""
    await run_sql(database_url, "TRUNCATE admin_actions")


def test_recovery_mode_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPERATOR_RECOVERY", raising=False)
    assert Settings().operator_recovery is False

    monkeypatch.setenv("OPERATOR_RECOVERY", "true")
    assert Settings().operator_recovery is True


async def test_recovery_is_refused_while_the_mode_is_off(
    settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    username = unique_username()
    await new_session(database_url, username)

    async with admin_client(settings, None) as client:
        status = await client.get("/admin/v1/recovery")
        response = await client.post(
            "/admin/v1/recovery",
            json={"token": "anything", "username": username, "new_password": NEW_PASSWORD},
        )

    assert status.status_code == 200
    assert status.json() == {"enabled": False}
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "recovery_disabled"
    assert recovery_tokens(caplog) == []


async def test_recovery_mode_prints_one_token_with_a_warning(
    recovery_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    async with admin_client(recovery_settings, None) as client:
        status = await client.get("/admin/v1/recovery")

    assert status.json() == {"enabled": True}
    [token] = recovery_tokens(caplog)
    [record] = [r for r in caplog.records if r.name == "app.admin_api.recovery"]
    assert record.levelno == logging.WARNING
    assert "OPERATOR_RECOVERY" in record.getMessage()
    assert "turn it off" in record.getMessage()
    assert len(token) > 40


async def test_recovery_refuses_a_wrong_token(
    recovery_settings: Settings, database_url: str
) -> None:
    username = unique_username()
    await new_session(database_url, username)

    async with admin_client(recovery_settings, None) as client:
        response = await client.post(
            "/admin/v1/recovery",
            json={"token": "not-the-token", "username": username, "new_password": NEW_PASSWORD},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_recovery_token"


async def test_recovery_refuses_an_unknown_username(
    recovery_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    async with admin_client(recovery_settings, None) as client:
        [token] = recovery_tokens(caplog)
        response = await client.post(
            "/admin/v1/recovery",
            json={"token": token, "username": unique_username(), "new_password": NEW_PASSWORD},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "operator_not_found"


async def test_recovery_refuses_an_invalid_password(
    recovery_settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    username = unique_username()
    await new_session(database_url, username)

    async with admin_client(recovery_settings, None) as client:
        [token] = recovery_tokens(caplog)
        response = await client.post(
            "/admin/v1/recovery",
            json={"token": token, "username": username, "new_password": "too short"},
        )
        sign_in = await client.post(
            "/admin/v1/sessions", json={"username": username, "password": PASSWORD}
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_password"
    assert response.json()["error"]["param"] == "new_password"
    assert sign_in.status_code == 201


async def test_recovery_sets_a_new_password_and_opens_the_account_again(
    recovery_settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    username = unique_username()
    old_session = await new_session(database_url, username)
    await run_sql(
        database_url,
        "UPDATE operators SET enabled = false, failed_attempts = 7,"
        " locked_until = now() + interval '1 hour' WHERE username = :u",
        u=username,
    )

    async with admin_client(recovery_settings, None) as client:
        [token] = recovery_tokens(caplog)
        # The username is unique whatever the case: any case finds the account.
        response = await client.post(
            "/admin/v1/recovery",
            json={"token": token, "username": username.upper(), "new_password": NEW_PASSWORD},
        )
        old_password = await client.post(
            "/admin/v1/sessions", json={"username": username, "password": PASSWORD}
        )
        new_password = await client.post(
            "/admin/v1/sessions", json={"username": username, "password": NEW_PASSWORD}
        )
        me = await client.get(
            "/admin/v1/me", headers={"Authorization": f"Bearer {new_password.json()['token']}"}
        )
        old_me = await client.get(
            "/admin/v1/me", headers={"Authorization": f"Bearer {old_session}"}
        )

    assert response.status_code == 200
    assert response.json() == {"username": username}
    assert old_password.status_code == 401
    assert new_password.status_code == 201
    assert me.json()["must_change_password"] is True
    assert old_me.status_code == 401
    [[enabled, failed_attempts, locked_until]] = await rows(
        database_url,
        "SELECT enabled, failed_attempts, locked_until FROM operators WHERE username = :u",
        username,
    )
    assert enabled is True
    assert failed_attempts == 0
    assert locked_until is None


async def test_recovery_token_works_only_once(
    recovery_settings: Settings, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    username = unique_username()
    await new_session(database_url, username)

    async with admin_client(recovery_settings, None) as client:
        [token] = recovery_tokens(caplog)
        body = {"token": token, "username": username, "new_password": NEW_PASSWORD}
        first = await client.post("/admin/v1/recovery", json=body)
        second = await client.post(
            "/admin/v1/recovery", json={**body, "new_password": "yet another long password"}
        )
        status = await client.get("/admin/v1/recovery")

    assert first.status_code == 200
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "recovery_used"
    # Still on, so the dashboard keeps showing its banner until the variable is removed.
    assert status.json() == {"enabled": True}


async def test_recovery_is_recorded_without_secrets(
    recovery_settings: Settings,
    database_url: str,
    actions: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    username = unique_username()
    await new_session(database_url, username)

    async with admin_client(recovery_settings, None) as client:
        [token] = recovery_tokens(caplog)
        response = await client.post(
            "/admin/v1/recovery",
            json={"token": token, "username": username, "new_password": NEW_PASSWORD},
        )

    assert response.status_code == 200
    history = await action_rows(database_url)
    [action] = history
    assert action["actor"] == "recovery"
    assert action["action"] == "recover-operator"
    assert action["target"] == username
    assert action["operator_id"] is None
    [password_hash] = await run_sql(
        database_url, "SELECT password_hash FROM operators WHERE username = :u", u=username
    )
    for secret in (NEW_PASSWORD, token, password_hash):
        assert secret not in str(history)


async def test_recovery_answers_503_when_postgresql_is_down(
    write_config: WriteConfig,
    database_url: str,
    database_proxy: DatabaseProxy,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = write_config(MINIMAL_CONFIG).model_copy(
        update={"database_url": database_proxy.url, "operator_recovery": True}
    )
    username = unique_username()
    await new_session(database_url, username)

    async with admin_client(settings, None) as client:
        [token] = recovery_tokens(caplog)
        await database_proxy.stop()
        body = {"token": token, "username": username, "new_password": NEW_PASSWORD}
        first = await client.post("/admin/v1/recovery", json=body)
        second = await client.post("/admin/v1/recovery", json=body)

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "database_unavailable"
    # The token is consumed only after a successful commit: it still works.
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "database_unavailable"


async def rows(database_url: str, statement: str, username: str) -> list[tuple[object, ...]]:
    """Run a query with the parameter `u` and return its whole rows."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(statement), {"u": username})
            return [tuple(row) for row in result]
    finally:
        await engine.dispose()
