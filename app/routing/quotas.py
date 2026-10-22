"""Python side of quota tracking: token estimates and the daily reset time.

The quota counters themselves live in Redis and are checked by the
`acquire_target` and `acquire_tenant` Lua scripts (see `acquisition.py`). Timezone maths is done
here, because Lua in Redis has no timezone support.
"""

import datetime as dt
import math
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from app.config import DailyReset
from app.schemas import count_prompt_chars

# A common rule of thumb for English text: about 4 characters per token.
CHARS_PER_TOKEN = 4


def estimate_prompt_tokens(body: Mapping[str, Any]) -> int:
    """Estimate the prompt size in tokens, from every string the model reads."""
    return math.ceil(count_prompt_chars(body) / CHARS_PER_TOKEN)


def estimate_call_tokens(
    prompt_tokens: int,
    body: Mapping[str, Any],
    default_completion_tokens: int,
    tpm: int | None,
) -> int:
    """Estimate the tokens one call will use, to reserve them before the call.

    The completion part is the `max_tokens` (or `max_completion_tokens`) the
    client asked for, or `default_completion_tokens` when it asked for none.
    The total is capped at the target TPM: a call can never use more than the
    whole window, and a larger reservation could never fit.
    """
    max_tokens = body.get("max_tokens", body.get("max_completion_tokens"))
    completion = max_tokens if isinstance(max_tokens, int) else default_completion_tokens
    total = prompt_tokens + completion
    return total if tpm is None else min(total, tpm)


def quota_day(daily_reset: DailyReset, now: dt.datetime) -> tuple[dt.date, dt.datetime]:
    """Return the current quota day of a provider, and when it ends.

    A quota day starts at the provider's daily reset time, in the provider's
    timezone. The first value is the local date the current quota day started
    on (it names the Redis counter); the second is the next reset time.
    """
    timezone = ZoneInfo(daily_reset.timezone)
    local_now = now.astimezone(timezone)
    reset_today = dt.datetime.combine(local_now.date(), daily_reset.time, tzinfo=timezone)
    if local_now >= reset_today:
        return local_now.date(), reset_today + dt.timedelta(days=1)
    return local_now.date() - dt.timedelta(days=1), reset_today
