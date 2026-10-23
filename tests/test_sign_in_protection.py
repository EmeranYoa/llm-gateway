"""Tests for the protection of the admin sign-in against password guessing.

Two limits work together: an account is locked for 15 minutes after 5 failed
sign-ins within 15 minutes (stored in PostgreSQL), and a client address may try
20 sign-ins within 15 minutes (in memory). A fake clock moves time forward, so
no test waits 15 minutes.
"""

import asyncio
import datetime as dt
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.admin_api.main import create_admin_app
from app.auth import passwords
from app.config import Settings
from tests.conftest import MINIMAL_CONFIG
from tests.test_admin_api import PASSWORD, new_session, run_sql, unique_username

WRONG_PASSWORD = "not the password at all"


class FakeClock:
    """A clock that only moves when a test says so. Starts at the real time."""

    def __init__(self) -> None:
        self.now = dt.datetime.now(dt.UTC).replace(microsecond=0)

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += dt.timedelta(**delta)


class AdminApi:
    """One admin API process, reached through HTTP from any client address."""

    def __init__(self, app: Any) -> None:
        self._app = app
        self._clients: dict[str, AsyncClient] = {}

    async def sign_in(
        self,
        username: str,
        password: str,
        *,
        ip: str = "203.0.113.1",
        forwarded_for: str | None = None,
    ) -> httpx.Response:
        if ip not in self._clients:
            transport = ASGITransport(app=self._app, client=(ip, 50000))
            self._clients[ip] = AsyncClient(transport=transport, base_url="http://admin-api")
        headers = {} if forwarded_for is None else {"X-Forwarded-For": forwarded_for}
        return await self._clients[ip].post(
            "/admin/v1/sessions",
            json={"username": username, "password": password},
            headers=headers,
        )

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()


@asynccontextmanager
async def admin_api(settings: Settings, clock: FakeClock) -> AsyncIterator[AdminApi]:
    """Start the admin API with `settings` and the fake `clock`."""
    app = create_admin_app(settings, clock=clock)
    api = AdminApi(app)
    async with app.router.lifespan_context(app):
        try:
            yield api
        finally:
            await api.close()


@pytest.fixture
def settings(write_config: Callable[[str], Settings]) -> Settings:
    return write_config(MINIMAL_CONFIG)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def username(database_url: str) -> str:
    """A new operator account whose password is `PASSWORD`."""
    name = unique_username()
    await new_session(database_url, name)
    return name


async def lock_state(database_url: str, username: str) -> tuple[int, dt.datetime | None]:
    """The failure counter and the end of the lock of an account."""
    [failed_attempts] = await run_sql(
        database_url, "SELECT failed_attempts FROM operators WHERE username = :u", u=username
    )
    [locked_until] = await run_sql(
        database_url, "SELECT locked_until FROM operators WHERE username = :u", u=username
    )
    return int(failed_attempts), locked_until


async def fail(api: AdminApi, username: str, times: int, *, ip: str = "203.0.113.1") -> None:
    """Sign in `times` times with a wrong password, one after the other."""
    for _ in range(times):
        response = await api.sign_in(username, WRONG_PASSWORD, ip=ip)
        assert response.status_code == 401


# --- Account lock ---


async def test_five_failures_lock_the_account_even_for_the_right_password(
    settings: Settings, database_url: str, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        await fail(api, username, 4)
        assert await lock_state(database_url, username) == (4, None)
        await fail(api, username, 1)
        right_password = await api.sign_in(username, PASSWORD)

    assert right_password.status_code == 401
    assert right_password.json()["error"]["code"] == "invalid_credentials"
    assert await lock_state(database_url, username) == (
        5,
        clock.now + dt.timedelta(minutes=15),
    )


async def test_a_locked_account_opens_again_when_the_lock_ends(
    settings: Settings, database_url: str, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        await fail(api, username, 5)
        clock.advance(minutes=14, seconds=59)
        still_locked = await api.sign_in(username, PASSWORD)
        clock.advance(seconds=1)
        unlocked = await api.sign_in(username, PASSWORD)

    assert still_locked.status_code == 401
    assert unlocked.status_code == 201
    assert await lock_state(database_url, username) == (0, None)


async def test_failures_during_the_lock_do_not_extend_it(
    settings: Settings, database_url: str, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        await fail(api, username, 5)
        locked_until = clock.now + dt.timedelta(minutes=15)
        clock.advance(minutes=10)
        await fail(api, username, 3)

    assert await lock_state(database_url, username) == (5, locked_until)


async def test_a_success_resets_the_failure_counter(
    settings: Settings, database_url: str, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        await fail(api, username, 4)
        success = await api.sign_in(username, PASSWORD)
        after_success = await lock_state(database_url, username)
        await fail(api, username, 4)
        again = await api.sign_in(username, PASSWORD)

    assert success.status_code == 201
    assert after_success == (0, None)
    assert again.status_code == 201


async def test_failures_older_than_fifteen_minutes_no_longer_count(
    settings: Settings, database_url: str, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        await fail(api, username, 4)
        clock.advance(minutes=15)
        await fail(api, username, 1)
        after_window = await lock_state(database_url, username)
        success = await api.sign_in(username, PASSWORD)

    assert after_window == (1, None)
    assert success.status_code == 201


async def test_failures_within_fifteen_minutes_add_up(
    settings: Settings, database_url: str, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        await fail(api, username, 4)
        clock.advance(minutes=14, seconds=59)
        await fail(api, username, 1)

    assert await lock_state(database_url, username) == (
        5,
        clock.now + dt.timedelta(minutes=15),
    )


async def test_concurrent_wrong_passwords_are_all_counted(
    settings: Settings, database_url: str, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        responses = await asyncio.gather(
            *(api.sign_in(username, WRONG_PASSWORD) for _ in range(10))
        )
        right_password = await api.sign_in(username, PASSWORD)

    assert [response.status_code for response in responses] == [401] * 10
    assert right_password.status_code == 401
    # Exactly 5: none lost, and the ones after the lock do not count.
    assert await lock_state(database_url, username) == (
        5,
        clock.now + dt.timedelta(minutes=15),
    )


async def test_concurrent_wrong_passwords_below_the_limit_are_all_counted(
    settings: Settings, database_url: str, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        await asyncio.gather(*(api.sign_in(username, WRONG_PASSWORD) for _ in range(4)))

    assert await lock_state(database_url, username) == (4, None)


# --- No account enumeration ---


async def test_every_failure_looks_the_same_and_costs_one_password_hash(
    settings: Settings,
    database_url: str,
    username: str,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled = unique_username()
    locked = unique_username()
    await new_session(database_url, disabled)
    await new_session(database_url, locked)
    await run_sql(
        database_url, "UPDATE operators SET enabled = false WHERE username = :u", u=disabled
    )
    hashes: list[str] = []
    real_scrypt = passwords._scrypt

    def counting_scrypt(*args: Any) -> bytes:
        hashes.append("scrypt")
        return real_scrypt(*args)

    async with admin_api(settings, clock) as api:
        await fail(api, locked, 5)
        passwords.dummy_password_hash()  # computed once, before counting
        monkeypatch.setattr(passwords, "_scrypt", counting_scrypt)
        responses = {}
        for case, name, password in (
            ("wrong password", username, WRONG_PASSWORD),
            ("unknown username", "nobody-at-all", PASSWORD),
            ("disabled account", disabled, PASSWORD),
            ("locked account", locked, PASSWORD),
        ):
            hashes.clear()
            responses[case] = await api.sign_in(name, password)
            assert hashes == ["scrypt"], case

    first = responses["wrong password"]
    assert first.status_code == 401
    assert first.json()["error"]["code"] == "invalid_credentials"
    for case, response in responses.items():
        assert response.status_code == 401, case
        assert response.json() == first.json(), case
        assert "retry-after" not in response.headers, case


def test_the_dummy_hash_uses_the_current_cost_and_is_computed_once() -> None:
    dummy = passwords.dummy_password_hash()

    assert dummy is passwords.dummy_password_hash()
    cost = passwords.SCRYPT_COST
    assert dummy.startswith(f"scrypt${cost.n}${cost.r}${cost.p}$")


# --- Limit per client address ---


async def test_twenty_attempts_per_address_then_429_with_retry_after(
    settings: Settings, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        # Unknown usernames: no account gets locked, only the address limit applies.
        for _ in range(10):
            assert (await api.sign_in(unique_username(), PASSWORD)).status_code == 401
        clock.advance(minutes=5)
        for _ in range(10):
            assert (await api.sign_in(unique_username(), PASSWORD)).status_code == 401
        clock.advance(minutes=5)
        # Counted before the password: even the right one is refused.
        refused = await api.sign_in(username, PASSWORD)
        clock.advance(minutes=5)
        # The first 10 attempts are out of the window: 10 more are allowed.
        for _ in range(9):
            assert (await api.sign_in(unique_username(), PASSWORD)).status_code == 401
        accepted = await api.sign_in(username, PASSWORD)
        refused_again = await api.sign_in(username, PASSWORD)

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "too_many_attempts"
    assert refused.json()["error"]["type"] == "rate_limit_error"
    assert refused.headers["Retry-After"] == "300"
    assert accepted.status_code == 201
    assert refused_again.status_code == 429
    assert refused_again.headers["Retry-After"] == "300"


async def test_the_address_limit_is_counted_per_address(
    settings: Settings, username: str, clock: FakeClock
) -> None:
    async with admin_api(settings, clock) as api:
        for _ in range(20):
            await api.sign_in(unique_username(), PASSWORD, ip="198.51.100.7")
        refused = await api.sign_in(username, PASSWORD, ip="198.51.100.7")
        other_address = await api.sign_in(username, PASSWORD, ip="198.51.100.8")

    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "900"
    assert other_address.status_code == 201


async def test_the_address_limit_counts_the_browser_address_forwarded_by_the_dashboard(
    settings: Settings, username: str, clock: FakeClock
) -> None:
    # Every sign-in reaches the admin API from the dashboard's container: the
    # dashboard forwards the browser's address, which the limit must count.
    dashboard = "172.18.0.5"
    async with admin_api(settings, clock) as api:
        for _ in range(20):
            await api.sign_in(
                unique_username(), PASSWORD, ip=dashboard, forwarded_for="198.51.100.7"
            )
        refused = await api.sign_in(
            username, PASSWORD, ip=dashboard, forwarded_for="198.51.100.7, 172.18.0.5"
        )
        other_browser = await api.sign_in(
            username, PASSWORD, ip=dashboard, forwarded_for="198.51.100.8"
        )

    assert refused.status_code == 429
    assert other_browser.status_code == 201
