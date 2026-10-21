"""Route a chat completion request from an alias to a real provider/model target."""

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.config import Target
from app.providers.base import (
    ContextTooLarge,
    InvalidRequest,
    Provider,
    ProviderError,
    ProviderResponse,
    ProviderTimeout,
    TargetMisconfigured,
)

logger = logging.getLogger(__name__)


class UnknownAlias(Exception):
    """The requested alias is not defined in the gateway config."""

    def __init__(self, alias: str) -> None:
        super().__init__(f"unknown alias '{alias}'")
        self.alias = alias


class NoEnabledTarget(Exception):
    """Every target of the alias belongs to a disabled provider."""

    def __init__(self, alias: str) -> None:
        super().__init__(f"no enabled target for alias '{alias}'")
        self.alias = alias


class AllTargetsFailed(Exception):
    """Every target of the alias was tried and none of them answered."""

    def __init__(self, alias: str, failures: list[tuple[Target, ProviderError]]) -> None:
        super().__init__(f"All targets of alias '{alias}' failed: {_describe(failures)}")
        self.alias = alias


class DeadlineExceeded(Exception):
    """The gateway deadline ran out before a target answered."""

    def __init__(
        self, alias: str, deadline: float, failures: list[tuple[Target, ProviderError]]
    ) -> None:
        super().__init__(
            f"Alias '{alias}' could not be served within the gateway deadline of {deadline:g} s: "
            f"{_describe(failures)}"
        )
        self.alias = alias


class RequestTooLarge(Exception):
    """The request is too large for every target of the alias. Retrying will not help."""

    def __init__(self, alias: str) -> None:
        super().__init__(f"request too large for every target of alias '{alias}'")
        self.alias = alias


class TargetRejectedRequest(Exception):
    """A target refused the client request itself. It is returned without failover."""

    def __init__(self, target: Target, error: InvalidRequest) -> None:
        super().__init__(f"{target.name}: {error.message}")
        self.target = target
        self.error = error


@dataclass(frozen=True)
class RoutedResponse:
    """The response returned to the client, and how it was routed."""

    body: dict[str, Any]
    target: Target
    fallbacks: int
    """Number of targets examined before the one that answered."""


class Router:
    def __init__(
        self,
        routes: Mapping[str, tuple[Target, ...]],
        providers: Mapping[str, Provider],
        *,
        deadline: float,
        min_attempt_time: float,
    ) -> None:
        self._routes = routes
        self._providers = providers
        self._deadline = deadline
        self._min_attempt_time = min_attempt_time

    async def route(self, alias: str, body: dict[str, Any]) -> RoutedResponse:
        """Send the request to the targets of `alias` in order, until one answers.

        An `InvalidRequest` stops the loop: the client request is wrong, and
        every other target would refuse it too. Any other provider error moves
        on to the next target.

        The whole request must finish within the gateway deadline. Each attempt
        gets `min(model timeout, remaining deadline)`, and no new attempt starts
        when less than `min_attempt_time` remains.

        Raises:
            UnknownAlias: the alias is not defined.
            NoEnabledTarget: none of the alias targets can be used.
            TargetRejectedRequest: a target refused the client request.
            DeadlineExceeded: the deadline ran out before a target answered.
            RequestTooLarge: the request is too large for every target.
            AllTargetsFailed: every target failed for another reason.
        """
        targets = self._routes.get(alias)
        if targets is None:
            raise UnknownAlias(alias)
        if not targets:
            raise NoEnabledTarget(alias)
        deadline_at = time.monotonic() + self._deadline
        failures: list[tuple[Target, ProviderError]] = []
        for index, target in enumerate(targets):
            remaining = deadline_at - time.monotonic()
            if remaining < self._min_attempt_time:
                raise DeadlineExceeded(alias, self._deadline, failures)
            provider = self._providers[target.provider.name]
            attempt_timeout = min(target.limits.timeout, remaining)
            try:
                response = await _call_with_timeout(provider, target.model, body, attempt_timeout)
            except InvalidRequest as error:
                raise TargetRejectedRequest(target, error) from error
            except ProviderError as error:
                failures.append((target, error))
                if isinstance(error, ProviderTimeout) and attempt_timeout < target.limits.timeout:
                    # The deadline cut this attempt short, not the model's own timeout.
                    raise DeadlineExceeded(alias, self._deadline, failures) from error
                if isinstance(error, TargetMisconfigured):
                    logger.error(
                        "target %s is misconfigured (HTTP %s): check its API key and model name",
                        target.name,
                        error.status_code,
                    )
                continue
            return RoutedResponse(
                body={**response.body, "model": target.model}, target=target, fallbacks=index
            )
        if all(isinstance(error, ContextTooLarge) for _, error in failures):
            raise RequestTooLarge(alias)
        raise AllTargetsFailed(alias, failures)


async def _call_with_timeout(
    provider: Provider, model: str, body: dict[str, Any], attempt_timeout: float
) -> ProviderResponse:
    """Call the provider, and stop waiting after `attempt_timeout` seconds.

    The provider receives the timeout too, but the router enforces it as well,
    so a provider that ignores it can never make the request exceed its deadline.
    """
    try:
        async with asyncio.timeout(attempt_timeout):
            return await provider.chat_completion(model, body, timeout=attempt_timeout)
    except TimeoutError as error:
        raise ProviderTimeout() from error


def _describe(failures: list[tuple[Target, ProviderError]]) -> str:
    return "; ".join(f"{target.name}: {error}" for target, error in failures)
