"""Tests for the management of operator accounts in the admin API: list, create,
reset a password, disable and enable accounts, change one's own password and
language. Sensitive actions ask for the current password again, and an operator
who must change their password can do nothing else first."""

import asyncio
import re
from collections.abc import Callable
from typing import Any

import pytest

from app.admin_api import operators as operators_routes
from app.admin_api.main import create_admin_app
from app.auth.keys import hash_key
from app.auth.passwords import verify_password
from app.config import Settings
from tests.conftest import MINIMAL_CONFIG, DatabaseProxy
from tests.test_admin_api import (
    PASSWORD,
    action_rows,
    admin_client,
    new_session,
    operator_id,
    run_sql,
    unique_username,
)

WriteConfig = Callable[[str], Settings]

NEW_PASSWORD = "another long enough password"


@pytest.fixture
def settings(write_config: WriteConfig) -> Settings:
    return write_config(MINIMAL_CONFIG)


@pytest.fixture
async def actions(database_url: str) -> None:
    """Empty the history of admin actions."""
    await run_sql(database_url, "TRUNCATE admin_actions")


@pytest.fixture
async def no_operator(database_url: str) -> None:
    """Remove every operator account (and their sessions), as on a new installation."""
    await run_sql(database_url, "DELETE FROM operators")


async def signed_in(database_url: str) -> tuple[str, str]:
    """Create an operator with a session. Returns its username and session token."""
    username = unique_username()
    return username, await new_session(database_url, username)


async def operator_column(database_url: str, username: str, column: str) -> Any:
    [value] = await run_sql(
        database_url, f"SELECT {column} FROM operators WHERE username = :u", u=username
    )
    return value


async def session_count(database_url: str, username: str) -> int:
    [count] = await run_sql(
        database_url,
        "SELECT count(*) FROM operator_sessions s JOIN operators o ON o.id = s.operator_id"
        " WHERE o.username = :u",
        u=username,
    )
    return int(count)


async def must_change_password(database_url: str, username: str) -> None:
    await run_sql(
        database_url,
        "UPDATE operators SET must_change_password = true WHERE username = :u",
        u=username,
    )


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


# --- List and create ---


async def test_list_operators_shows_every_account_without_any_hash(
    settings: Settings, database_url: str
) -> None:
    username, token = await signed_in(database_url)
    other, _ = await signed_in(database_url)
    await run_sql(database_url, "UPDATE operators SET enabled = false WHERE username = :u", u=other)

    async with admin_client(settings, token) as client:
        response = await client.get("/admin/v1/operators")

    assert response.status_code == 200
    operators = {found["username"]: found for found in response.json()["operators"]}
    assert set(operators[username]) == {
        "id",
        "username",
        "enabled",
        "must_change_password",
        "created_at",
        "last_sign_in_at",
    }
    assert operators[username]["id"] == await operator_id(database_url, username)
    assert operators[username]["enabled"] is True
    assert operators[username]["last_sign_in_at"] is not None
    assert operators[other]["enabled"] is False
    assert "scrypt$" not in response.text


async def test_create_operator_must_change_its_password(
    settings: Settings, database_url: str, actions: None
) -> None:
    username, token = await signed_in(database_url)
    new_username = unique_username()

    async with admin_client(settings, token) as client:
        response = await client.post(
            "/admin/v1/operators",
            json={"username": new_username, "password": NEW_PASSWORD, "current_password": PASSWORD},
        )
        signed_in_as_new = await client.post(
            "/admin/v1/sessions", json={"username": new_username, "password": NEW_PASSWORD}
        )

    assert response.status_code == 201
    created = response.json()
    assert created["username"] == new_username
    assert created["must_change_password"] is True
    assert created["enabled"] is True
    assert created["last_sign_in_at"] is None
    assert signed_in_as_new.status_code == 201
    [action] = await action_rows(database_url)
    assert action["action"] == "create-operator"
    assert action["actor"] == username
    assert action["operator_id"] == await operator_id(database_url, username)
    assert action["target"] == new_username


async def test_create_operator_refuses_a_duplicate_username_whatever_its_case(
    settings: Settings, database_url: str
) -> None:
    existing, token = await signed_in(database_url)

    async with admin_client(settings, token) as client:
        response = await client.post(
            "/admin/v1/operators",
            json={
                "username": existing.upper(),
                "password": NEW_PASSWORD,
                "current_password": PASSWORD,
            },
        )

    assert response.status_code == 409
    assert error_code(response) == "operator_exists"


async def test_create_operator_refuses_an_invalid_password(
    settings: Settings, database_url: str
) -> None:
    _, token = await signed_in(database_url)
    new_username = unique_username()

    async with admin_client(settings, token) as client:
        response = await client.post(
            "/admin/v1/operators",
            json={"username": new_username, "password": "short", "current_password": PASSWORD},
        )

    assert response.status_code == 400
    assert error_code(response) == "invalid_password"
    assert await run_sql(
        database_url, "SELECT count(*) FROM operators WHERE username = :u", u=new_username
    ) == [0]


# --- Re-authentication ---


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/admin/v1/operators", {"username": "someone-new", "password": NEW_PASSWORD}),
        ("POST", "/admin/v1/operators/{target}/reset-password", {"password": NEW_PASSWORD}),
        ("POST", "/admin/v1/operators/{target}/disable", {}),
        ("POST", "/admin/v1/operators/{target}/enable", {}),
        ("PUT", "/admin/v1/me/password", {"new_password": NEW_PASSWORD}),
    ],
    ids=["create", "reset-password", "disable", "enable", "own-password"],
)
async def test_sensitive_actions_need_the_current_password(
    settings: Settings,
    database_url: str,
    actions: None,
    method: str,
    path: str,
    body: dict[str, str],
) -> None:
    _, token = await signed_in(database_url)
    target, target_token = await signed_in(database_url)
    target_id = await operator_id(database_url, target)

    async with admin_client(settings, token) as client:
        response = await client.request(
            method,
            path.format(target=target_id),
            json={**body, "current_password": "not the right password"},
        )
        target_me = await client.get(
            "/admin/v1/me", headers={"Authorization": f"Bearer {target_token}"}
        )

    assert response.status_code == 403
    assert error_code(response) == "reauthentication_failed"
    assert await action_rows(database_url) == []
    assert target_me.status_code == 200
    # A failed re-authentication is not a failed sign-in.
    assert await operator_column(database_url, target, "failed_attempts") == 0


# --- Reset a password ---


async def test_reset_password_forces_a_change_and_closes_the_target_sessions_at_once(
    settings: Settings, database_url: str, actions: None
) -> None:
    username, token = await signed_in(database_url)
    target, target_token = await signed_in(database_url)
    target_id = await operator_id(database_url, target)

    async with admin_client(settings, token) as client:
        response = await client.post(
            f"/admin/v1/operators/{target_id}/reset-password",
            json={"password": NEW_PASSWORD, "current_password": PASSWORD},
        )
        target_me = await client.get(
            "/admin/v1/me", headers={"Authorization": f"Bearer {target_token}"}
        )
        old_password = await client.post(
            "/admin/v1/sessions", json={"username": target, "password": PASSWORD}
        )
        new_password = await client.post(
            "/admin/v1/sessions", json={"username": target, "password": NEW_PASSWORD}
        )

    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert target_me.status_code == 401
    assert old_password.status_code == 401
    assert new_password.status_code == 201
    assert await operator_column(database_url, target, "must_change_password") is True
    [action] = await action_rows(database_url)
    assert action["action"] == "reset-password"
    assert action["actor"] == username
    assert action["operator_id"] == await operator_id(database_url, username)
    assert action["target"] == target


async def test_reset_password_of_oneself_is_refused(settings: Settings, database_url: str) -> None:
    username, token = await signed_in(database_url)

    async with admin_client(settings, token) as client:
        response = await client.post(
            f"/admin/v1/operators/{await operator_id(database_url, username)}/reset-password",
            json={"password": NEW_PASSWORD, "current_password": PASSWORD},
        )

    assert response.status_code == 400
    assert error_code(response) == "use_own_password_change"


async def test_reset_password_refuses_an_invalid_password(
    settings: Settings, database_url: str
) -> None:
    _, token = await signed_in(database_url)
    target, _ = await signed_in(database_url)

    async with admin_client(settings, token) as client:
        response = await client.post(
            f"/admin/v1/operators/{await operator_id(database_url, target)}/reset-password",
            json={"password": target, "current_password": PASSWORD},
        )

    assert response.status_code == 400
    assert error_code(response) == "invalid_password"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("reset-password", {"password": NEW_PASSWORD, "current_password": PASSWORD}),
        ("disable", {"current_password": PASSWORD}),
        ("enable", {"current_password": PASSWORD}),
    ],
)
async def test_actions_on_an_unknown_operator_are_refused(
    settings: Settings, database_url: str, path: str, body: dict[str, str]
) -> None:
    _, token = await signed_in(database_url)

    async with admin_client(settings, token) as client:
        response = await client.post(f"/admin/v1/operators/999999999/{path}", json=body)

    assert response.status_code == 404
    assert error_code(response) == "operator_not_found"


# --- Disable and enable ---


async def test_disable_closes_the_target_sessions_at_once_and_enable_lets_it_sign_in(
    settings: Settings, database_url: str, actions: None
) -> None:
    username, token = await signed_in(database_url)
    target, target_token = await signed_in(database_url)
    target_id = await operator_id(database_url, target)

    async with admin_client(settings, token) as client:
        disabled = await client.post(
            f"/admin/v1/operators/{target_id}/disable", json={"current_password": PASSWORD}
        )
        target_me = await client.get(
            "/admin/v1/me", headers={"Authorization": f"Bearer {target_token}"}
        )
        refused_sign_in = await client.post(
            "/admin/v1/sessions", json={"username": target, "password": PASSWORD}
        )
        enabled = await client.post(
            f"/admin/v1/operators/{target_id}/enable", json={"current_password": PASSWORD}
        )
        sign_in = await client.post(
            "/admin/v1/sessions", json={"username": target, "password": PASSWORD}
        )

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert target_me.status_code == 401
    assert refused_sign_in.status_code == 401
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert sign_in.status_code == 201
    rows = await action_rows(database_url)
    assert [row["action"] for row in rows] == ["disable-operator", "enable-operator"]
    current_id = await operator_id(database_url, username)
    for row in rows:
        assert row["actor"] == username
        assert row["operator_id"] == current_id
        assert row["target"] == target


async def test_disabling_oneself_is_refused(settings: Settings, database_url: str) -> None:
    username, token = await signed_in(database_url)

    async with admin_client(settings, token) as client:
        response = await client.post(
            f"/admin/v1/operators/{await operator_id(database_url, username)}/disable",
            json={"current_password": PASSWORD},
        )

    assert response.status_code == 400
    assert error_code(response) == "cannot_disable_self"
    assert await operator_column(database_url, username, "enabled") is True


async def test_two_operators_disabling_each_other_at_once_leave_one_enabled_account(
    settings: Settings, database_url: str, no_operator: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice, alice_token = await signed_in(database_url)
    bob, bob_token = await signed_in(database_url)
    alice_id = await operator_id(database_url, alice)
    bob_id = await operator_id(database_url, bob)
    # Both requests pass their session check and their re-authentication before
    # either disable runs: the guard in the database is then the only thing
    # between them and zero enabled accounts.
    both_checked = asyncio.Barrier(2)
    reauthenticate = operators_routes.reauthenticate

    async def reauthenticate_then_wait(*args: Any) -> bool:
        result = await reauthenticate(*args)
        await both_checked.wait()
        return result

    monkeypatch.setattr(operators_routes, "reauthenticate", reauthenticate_then_wait)

    async with admin_client(settings, None) as client:
        responses = await asyncio.gather(
            client.post(
                f"/admin/v1/operators/{bob_id}/disable",
                json={"current_password": PASSWORD},
                headers={"Authorization": f"Bearer {alice_token}"},
            ),
            client.post(
                f"/admin/v1/operators/{alice_id}/disable",
                json={"current_password": PASSWORD},
                headers={"Authorization": f"Bearer {bob_token}"},
            ),
        )

    assert sorted(response.status_code for response in responses) == [200, 400]
    [refused] = [response for response in responses if response.status_code == 400]
    assert error_code(refused) == "last_enabled_operator"
    assert await run_sql(database_url, "SELECT count(*) FROM operators WHERE enabled") == [1]


# --- Own password and language ---


async def test_own_password_change_keeps_the_current_session_and_closes_the_others(
    settings: Settings, database_url: str, actions: None
) -> None:
    username, token = await signed_in(database_url)
    other_token = await new_other_session(settings, username)
    await must_change_password(database_url, username)

    async with admin_client(settings, token) as client:
        response = await client.put(
            "/admin/v1/me/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        me = await client.get("/admin/v1/me")
        other_me = await client.get(
            "/admin/v1/me", headers={"Authorization": f"Bearer {other_token}"}
        )

    assert response.status_code == 200
    assert response.json()["must_change_password"] is False
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False
    assert other_me.status_code == 401
    assert await session_count(database_url, username) == 1
    stored_hash = await operator_column(database_url, username, "password_hash")
    assert verify_password(NEW_PASSWORD, stored_hash)
    [action] = await action_rows(database_url)
    assert action["action"] == "change-own-password"
    assert action["actor"] == username
    assert action["operator_id"] == await operator_id(database_url, username)
    assert action["target"] == username


async def new_other_session(settings: Settings, username: str) -> str:
    """Sign `username` in once more, through HTTP: a second session of the same operator."""
    async with admin_client(settings, None) as client:
        response = await client.post(
            "/admin/v1/sessions", json={"username": username, "password": PASSWORD}
        )
    return str(response.json()["token"])


@pytest.mark.parametrize(
    ("new_password", "reason"),
    [("short", "too short"), (PASSWORD, "same as the current one")],
    ids=["too-short", "unchanged"],
)
async def test_own_password_change_refuses_an_invalid_password(
    settings: Settings, database_url: str, new_password: str, reason: str
) -> None:
    _, token = await signed_in(database_url)

    async with admin_client(settings, token) as client:
        response = await client.put(
            "/admin/v1/me/password",
            json={"current_password": PASSWORD, "new_password": new_password},
        )

    assert response.status_code == 400, reason
    assert error_code(response) == "invalid_password"


async def test_language_is_stored_and_returned_by_me(settings: Settings, database_url: str) -> None:
    _, token = await signed_in(database_url)

    async with admin_client(settings, token) as client:
        french = await client.put("/admin/v1/me/language", json={"language": "fr"})
        me_french = await client.get("/admin/v1/me")
        browser = await client.put("/admin/v1/me/language", json={"language": None})
        me_browser = await client.get("/admin/v1/me")
        unknown = await client.put("/admin/v1/me/language", json={"language": "de"})

    assert french.status_code == 200
    assert french.json()["language"] == "fr"
    assert me_french.json()["language"] == "fr"
    assert browser.status_code == 200
    assert me_browser.json()["language"] is None
    assert unknown.status_code == 400


# --- Forced password change ---


ALLOWED_DURING_FORCED_CHANGE = {
    ("GET", "/admin/v1/me"),
    ("PUT", "/admin/v1/me/password"),
    ("PUT", "/admin/v1/me/language"),
    ("DELETE", "/admin/v1/sessions/current"),
}
NO_SESSION_NEEDED = {
    ("GET", "/admin/v1/setup"),
    ("POST", "/admin/v1/setup"),
    ("POST", "/admin/v1/sessions"),
    ("GET", "/admin/v1/recovery"),
    ("POST", "/admin/v1/recovery"),
}


def session_routes(settings: Settings) -> list[tuple[str, str]]:
    """Every admin route that needs a session and is closed during a forced change."""
    found = []
    for path, methods in create_admin_app(settings).openapi()["paths"].items():
        for method in methods:
            key = (method.upper(), path)
            if path.startswith("/admin/v1") and key not in (
                ALLOWED_DURING_FORCED_CHANGE | NO_SESSION_NEEDED
            ):
                found.append(key)
    return sorted(found)


async def test_forced_change_closes_every_other_route_until_the_password_changes(
    settings: Settings, database_url: str
) -> None:
    username, token = await signed_in(database_url)
    await must_change_password(database_url, username)
    routes = session_routes(settings)
    assert ("GET", "/admin/v1/operators") in routes
    assert ("GET", "/admin/v1/actions") in routes

    async with admin_client(settings, token) as client:
        refused = {
            (method, path): await client.request(method, re.sub(r"\{\w+\}", "1", path), json={})
            for method, path in routes
        }
        me = await client.get("/admin/v1/me")
        language = await client.put("/admin/v1/me/language", json={"language": "en"})
        changed = await client.put(
            "/admin/v1/me/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        after = await client.get("/admin/v1/operators")
        signed_out = await client.delete("/admin/v1/sessions/current")

    for route, response in refused.items():
        assert response.status_code == 403, route
        assert error_code(response) == "password_change_required", route
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True
    assert language.status_code == 200
    assert changed.status_code == 200
    assert after.status_code == 200
    assert signed_out.status_code == 204


async def test_sign_out_works_during_a_forced_change(settings: Settings, database_url: str) -> None:
    username, token = await signed_in(database_url)
    await must_change_password(database_url, username)

    async with admin_client(settings, token) as client:
        signed_out = await client.delete("/admin/v1/sessions/current")
        after = await client.get("/admin/v1/me")

    assert signed_out.status_code == 204
    assert after.status_code == 401


# --- Secrets and outages ---


async def test_no_secret_is_ever_recorded_in_admin_actions(
    settings: Settings, database_url: str, actions: None
) -> None:
    username, token = await signed_in(database_url)
    new_username = unique_username()

    async with admin_client(settings, token) as client:
        await client.post(
            "/admin/v1/operators",
            json={"username": new_username, "password": NEW_PASSWORD, "current_password": PASSWORD},
        )
        new_id = await operator_id(database_url, new_username)
        await client.post(
            f"/admin/v1/operators/{new_id}/reset-password",
            json={"password": NEW_PASSWORD + "!", "current_password": PASSWORD},
        )
        await client.post(
            f"/admin/v1/operators/{new_id}/disable", json={"current_password": PASSWORD}
        )
        await client.post(
            f"/admin/v1/operators/{new_id}/enable", json={"current_password": PASSWORD}
        )
        await client.put(
            "/admin/v1/me/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )

    rows = await action_rows(database_url)
    assert [row["action"] for row in rows] == [
        "create-operator",
        "reset-password",
        "disable-operator",
        "enable-operator",
        "change-own-password",
    ]
    hashes = await run_sql(
        database_url,
        "SELECT password_hash FROM operators WHERE username IN (:a, :b)",
        a=username,
        b=new_username,
    )
    history = str(rows)
    for secret in (PASSWORD, NEW_PASSWORD, NEW_PASSWORD + "!", token, hash_key(token), *hashes):
        assert secret not in history
    assert "scrypt" not in history


async def test_operator_management_answers_503_when_postgresql_is_down(
    write_config: WriteConfig, database_url: str, database_proxy: DatabaseProxy
) -> None:
    settings = write_config(MINIMAL_CONFIG).model_copy(update={"database_url": database_proxy.url})
    _, token = await signed_in(database_url)

    async with admin_client(settings, token) as client:
        await database_proxy.stop()
        listed = await client.get("/admin/v1/operators")
        language = await client.put("/admin/v1/me/language", json={"language": "fr"})

    assert listed.status_code == 503
    assert language.status_code == 503
