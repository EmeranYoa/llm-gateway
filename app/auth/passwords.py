"""Passwords of operator accounts: the rules they follow, and how they are stored.

A password is never stored nor logged in clear. It is hashed with scrypt, from
the standard library, with a random salt per password and the parameters that
OWASP recommends (N=2**17, r=8, p=1). scrypt is slow and needs 128 MiB of memory
on purpose: it makes guessing passwords from a stolen database very costly.
Unlike API keys, passwords are chosen by people, so a fast hash such as SHA-256
would not be enough.

A hash is stored as one self-describing string:

    scrypt$<N>$<r>$<p>$<salt, base64>$<hash, base64>

so the parameters can be raised later: old hashes keep their own parameters
and still verify.

One hash takes from a few hundred milliseconds to more than a second of CPU,
depending on the machine. Async code runs it in a thread (`asyncio.to_thread`),
so other requests are served in the meantime.
"""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

MIN_LENGTH = 12
MAX_LENGTH = 256
"""The upper limit stops very long inputs from making each hash slower."""

_SALT_BYTES = 16
_HASH_BYTES = 32
_ALGORITHM = "scrypt"


@dataclass(frozen=True)
class ScryptCost:
    """The cost parameters of scrypt: CPU and memory cost `n`, block size `r`, parallelism `p`."""

    n: int
    r: int
    p: int

    @property
    def max_memory(self) -> int:
        """Bytes scrypt may use: what it needs (about 128 * n * r * p), with room to spare."""
        return 2 * 128 * self.n * self.r * self.p


OWASP_SCRYPT_COST = ScryptCost(n=2**17, r=8, p=1)

SCRYPT_COST = OWASP_SCRYPT_COST
"""The cost of new hashes. The test suite lowers it to stay fast (`tests/conftest.py`)."""


def password_problem(password: str, username: str) -> str | None:
    """Return why `password` is refused for `username`, or None when it is accepted.

    The message never repeats the password.
    """
    if len(password) < MIN_LENGTH:
        return f"The password must be at least {MIN_LENGTH} characters long."
    if len(password) > MAX_LENGTH:
        return f"The password must be at most {MAX_LENGTH} characters long."
    if password.casefold() == username.casefold():
        return "The password must not be the username."
    return None


def hash_password(password: str) -> str:
    """Hash `password` with a new random salt, as stored in the database."""
    cost = SCRYPT_COST
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(password, salt, cost, _HASH_BYTES)
    return "$".join((_ALGORITHM, str(cost.n), str(cost.r), str(cost.p), _b64(salt), _b64(digest)))


def verify_password(password: str, stored: str) -> bool:
    """Return True when `password` matches the `stored` hash.

    The parameters come from `stored` itself. A malformed hash never matches.
    The comparison takes the same time wherever the first difference is.
    """
    try:
        algorithm, n, r, p, salt, digest = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        expected = base64.b64decode(digest, validate=True)
        cost = ScryptCost(n=int(n), r=int(r), p=int(p))
        found = _scrypt(password, base64.b64decode(salt, validate=True), cost, len(expected))
    except ValueError:
        return False
    return len(expected) > 0 and hmac.compare_digest(found, expected)


def _scrypt(password: str, salt: bytes, cost: ScryptCost, length: int) -> bytes:
    return hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=cost.n,
        r=cost.r,
        p=cost.p,
        maxmem=cost.max_memory,
        dklen=length,
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
