"""The periods the admin API reports on, and how their time series are cut.

Every period ends now. A 24 h period is cut into hours, longer ones into days.
Days are UTC days, aligned with the daily token budget of the tenants; the
dashboard shows the times in the operator's time zone.
"""

import datetime as dt
from enum import StrEnum


class Period(StrEnum):
    """How far back a report goes. 30 days at most: older rows may be purged."""

    DAY = "24h"
    WEEK = "7d"
    MONTH = "30d"

    @property
    def length(self) -> dt.timedelta:
        return {
            Period.DAY: dt.timedelta(hours=24),
            Period.WEEK: dt.timedelta(days=7),
            Period.MONTH: dt.timedelta(days=30),
        }[self]

    @property
    def bucket(self) -> str:
        """Size of one point of a time series: `hour` or `day` (a PostgreSQL `date_trunc` unit)."""
        return "hour" if self is Period.DAY else "day"

    def start(self, now: dt.datetime) -> dt.datetime:
        """The first moment of the period that ends at `now`."""
        return now - self.length
