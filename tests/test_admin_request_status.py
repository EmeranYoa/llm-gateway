"""Tests for the classification of a request from the outcomes of its usage rows."""

import pytest

from app.admin_api.request_status import RequestStatus, request_status


@pytest.mark.parametrize(
    ("outcomes", "status"),
    [
        (["success"], RequestStatus.ANSWERED),
        (["rate_limited", "skipped_cooldown", "success"], RequestStatus.ANSWERED),
        (["cache_hit"], RequestStatus.ANSWERED),
        (["cancelled"], RequestStatus.CANCELLED),
        (["unavailable", "cancelled"], RequestStatus.CANCELLED),
        (["invalid_request"], RequestStatus.CLIENT_ERROR),
        (["rejected_tenant_quota"], RequestStatus.CLIENT_ERROR),
        (["context_too_large", "context_too_large"], RequestStatus.CLIENT_ERROR),
        (["context_too_large", "rate_limited"], RequestStatus.FAILED),
        (["rate_limited", "unavailable", "timeout"], RequestStatus.FAILED),
        (["skipped_quota", "skipped_breaker"], RequestStatus.FAILED),
        (["interrupted"], RequestStatus.FAILED),
    ],
)
def test_request_status(outcomes: list[str], status: RequestStatus) -> None:
    assert request_status(outcomes) == status
