"""Tests for operator passwords: the password rules, and hashing with scrypt."""

import pytest

from app.auth import passwords
from app.auth.passwords import ScryptCost, hash_password, password_problem, verify_password
from tests.conftest import DEFAULT_SCRYPT_COST


@pytest.mark.parametrize(
    ("password", "username"),
    [("a" * 12, "alice"), ("é" * 12, "alice"), ("x" * 256, "alice"), ("alice-password", "alice")],
    ids=["12-characters", "12-non-ascii-characters", "256-characters", "contains-username"],
)
def test_valid_passwords_have_no_problem(password: str, username: str) -> None:
    assert password_problem(password, username) is None


@pytest.mark.parametrize(
    ("password", "username", "problem"),
    [
        ("a" * 11, "alice", "at least 12 characters"),
        ("", "alice", "at least 12 characters"),
        ("x" * 257, "alice", "at most 256 characters"),
        ("operator-alice", "operator-alice", "must not be the username"),
        ("Operator-ALICE", "operator-alice", "must not be the username"),
    ],
    ids=["too-short", "empty", "too-long", "username", "username-other-case"],
)
def test_invalid_passwords_are_explained(password: str, username: str, problem: str) -> None:
    found = password_problem(password, username)

    assert found is not None
    assert problem in found
    assert password not in found or password == ""


def test_hash_verifies_the_right_password_only() -> None:
    stored = hash_password("correct horse battery")

    assert verify_password("correct horse battery", stored)
    assert not verify_password("correct horse battery!", stored)
    assert not verify_password("", stored)
    assert "correct horse battery" not in stored


def test_each_hash_has_its_own_salt() -> None:
    first = hash_password("the same password")
    second = hash_password("the same password")

    assert first != second
    assert first.split("$")[4] != second.split("$")[4]
    assert verify_password("the same password", first)
    assert verify_password("the same password", second)


def test_hash_names_its_algorithm_and_parameters() -> None:
    algorithm, n, r, p, _, _ = hash_password("a long enough password").split("$")

    cost = passwords.SCRYPT_COST
    assert (algorithm, int(n), int(r), int(p)) == ("scrypt", cost.n, cost.r, cost.p)


def test_a_hash_made_with_other_parameters_still_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    # Parameters are read from the stored string, so they can change later.
    monkeypatch.setattr(passwords, "SCRYPT_COST", ScryptCost(n=2**5, r=4, p=2))
    old = hash_password("an older password")
    monkeypatch.setattr(passwords, "SCRYPT_COST", ScryptCost(n=2**6, r=8, p=1))

    assert old.startswith("scrypt$32$4$2$")
    assert verify_password("an older password", old)
    assert not verify_password("another password", old)


@pytest.mark.parametrize("stored", ["", "bcrypt$abc", "scrypt$x$8$1$AAAA$AAAA", "scrypt$16$8$1$"])
def test_a_malformed_hash_never_verifies(stored: str) -> None:
    assert not verify_password("any password at all", stored)


def test_default_parameters_are_the_owasp_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    # The test suite hashes with cheap parameters (see `tests/conftest.py`). This
    # test checks the real ones: N=2**17, r=8, p=1, and that they fit in `maxmem`.
    assert ScryptCost(n=2**17, r=8, p=1) == DEFAULT_SCRYPT_COST
    monkeypatch.setattr(passwords, "SCRYPT_COST", DEFAULT_SCRYPT_COST)

    stored = hash_password("a real production password")

    assert stored.startswith("scrypt$131072$8$1$")
    assert verify_password("a real production password", stored)
