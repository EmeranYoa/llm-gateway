"""Gateway API keys and admin keys: generation and hashing.

A key looks like a prefix + 32 random bytes in URL-safe base64: `gw_` for the
keys of client applications (tenants), `gwa_` for the admin keys of operators.
The two prefixes never overlap, so a key of one kind is never accepted where
the other kind is expected.

Only the SHA-256 hash of a key is stored. A slow hash such as bcrypt is not
needed: the key is a long random secret, not a password a person chose, and a
slow hash would add tens of milliseconds to every request.
"""

import hashlib
import secrets

KEY_PREFIX = "gw_"
ADMIN_KEY_PREFIX = "gwa_"

# Characters shown after the prefix by `list-keys`, to recognise a key without revealing it.
_DISPLAY_CHARS = 6


def generate_key(prefix: str = KEY_PREFIX) -> str:
    """Return a new random key with `prefix`."""
    return prefix + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    """Return the SHA-256 hash of `key`, as stored in the database."""
    return hashlib.sha256(key.encode()).hexdigest()


def display_prefix(key: str) -> str:
    """Return the start of `key`, safe to show and to store in clear."""
    prefix = ADMIN_KEY_PREFIX if key.startswith(ADMIN_KEY_PREFIX) else KEY_PREFIX
    return key[: len(prefix) + _DISPLAY_CHARS]
