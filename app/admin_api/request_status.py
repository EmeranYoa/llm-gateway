"""How the admin API classifies a request, from the usage rows of its attempts.

The usage log has one row per examined target. A request is classified from all
its rows (grouped by `request_id`), in this order:

1. **answered**: one row is `success` or `cache_hit`: the client got an answer.
2. **cancelled**: no answer, and one row is `cancelled`: the client left.
3. **client_error**: no answer, and the request itself was refused: one row is
   `invalid_request` (a 4xx the provider sent back) or `rejected_tenant_quota`
   (429 of the tenant's own quota), or every row is `context_too_large` (400: the
   request fits no target). These are not failures of the gateway.
4. **failed**: no answer for any other reason (503 when every target failed or was
   skipped, 504 deadline, or a stream `interrupted` after its first token). The
   error rate of the dashboard counts these only.
"""

from enum import StrEnum

from sqlalchemy import ColumnElement, case, func, or_

from app.storage.usage import UsageLogRow


class RequestStatus(StrEnum):
    ANSWERED = "answered"
    CANCELLED = "cancelled"
    CLIENT_ERROR = "client_error"
    FAILED = "failed"


ANSWER_OUTCOMES = frozenset({"success", "cache_hit"})
"""A row with one of these outcomes means the request was answered."""

CANCELLED_OUTCOMES = frozenset({"cancelled"})

CLIENT_ERROR_OUTCOMES = frozenset({"invalid_request", "rejected_tenant_quota"})
"""A row with one of these outcomes means the request itself was refused."""

TOO_LARGE_OUTCOME = "context_too_large"
"""When every row of a request has this outcome, the request fits no target: a client error."""


def request_status(outcomes: list[str]) -> RequestStatus:
    """Classify a request from the outcomes of all its usage rows (see the module docstring)."""
    found = set(outcomes)
    if found & ANSWER_OUTCOMES:
        return RequestStatus.ANSWERED
    if found & CANCELLED_OUTCOMES:
        return RequestStatus.CANCELLED
    if found & CLIENT_ERROR_OUTCOMES or found == {TOO_LARGE_OUTCOME}:
        return RequestStatus.CLIENT_ERROR
    return RequestStatus.FAILED


def status_expression() -> ColumnElement[str]:
    """The status of a request in SQL: `request_status()` as a CASE, rule by rule.

    For a query on `usage_log` grouped by `request_id`: each condition looks at
    all the rows of the request.
    """
    outcome = UsageLogRow.outcome

    def any_row(outcomes: frozenset[str]) -> ColumnElement[bool]:
        return func.bool_or(outcome.in_(sorted(outcomes)))

    return case(
        (any_row(ANSWER_OUTCOMES), RequestStatus.ANSWERED.value),
        (any_row(CANCELLED_OUTCOMES), RequestStatus.CANCELLED.value),
        (
            or_(any_row(CLIENT_ERROR_OUTCOMES), func.bool_and(outcome == TOO_LARGE_OUTCOME)),
            RequestStatus.CLIENT_ERROR.value,
        ),
        else_=RequestStatus.FAILED.value,
    )
