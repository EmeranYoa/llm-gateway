"""The limit of sign-in attempts per client address, and the clock of the sign-in.

A client address may try to sign in 20 times within 15 minutes (a sliding
window), whatever the usernames and whether the password is right. Above that,
the sign-in answers 429 until the oldest attempt leaves the window. With the
lock of accounts (`app/storage/operators.py`), it slows down password guessing.

The attempts are kept in memory, per admin API process: each process counts
on its own, and a restart forgets them. One admin API process is the normal
setup, so this is enough, and it needs neither Redis nor a new table.
"""

import datetime as dt
import math
from collections import deque
from collections.abc import Callable

MAX_ATTEMPTS_PER_ADDRESS = 20
ADDRESS_WINDOW = dt.timedelta(minutes=15)

Clock = Callable[[], dt.datetime]
"""Gives the current time. The admin API takes one, so tests can move time forward."""


def utc_now() -> dt.datetime:
    """The real clock, in UTC."""
    return dt.datetime.now(dt.UTC)


class AddressLimiter:
    """Counts the sign-in attempts of each client address in a sliding window."""

    def __init__(
        self, max_attempts: int = MAX_ATTEMPTS_PER_ADDRESS, window: dt.timedelta = ADDRESS_WINDOW
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window
        self._attempts: dict[str, deque[dt.datetime]] = {}
        self._next_sweep: dt.datetime | None = None

    def attempt(self, address: str, now: dt.datetime) -> int | None:
        """Count an attempt from `address` at `now`.

        Returns None when it is allowed. Otherwise returns the seconds to wait
        (for `Retry-After`), and the refused attempt is not counted.
        """
        self._sweep(now)
        attempts = self._attempts.setdefault(address, deque())
        while attempts and attempts[0] <= now - self._window:
            attempts.popleft()
        if len(attempts) >= self._max_attempts:
            wait = (attempts[0] + self._window - now).total_seconds()
            return max(1, math.ceil(wait))
        attempts.append(now)
        return None

    def _sweep(self, now: dt.datetime) -> None:
        """Forget the addresses with no attempt in the window, once per window.

        So addresses that stopped trying never pile up in memory.
        """
        if self._next_sweep is not None and now < self._next_sweep:
            return
        self._next_sweep = now + self._window
        for address, attempts in list(self._attempts.items()):
            if not attempts or attempts[-1] <= now - self._window:
                del self._attempts[address]
