"""Route a chat completion request from an alias to a real provider/model target."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.config import Target
from app.providers.base import (
    ContextTooLarge,
    InvalidRequest,
    Provider,
    ProviderError,
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
        reasons = "; ".join(f"{target.name}: {error}" for target, error in failures)
        super().__init__(f"All targets of alias '{alias}' failed: {reasons}")
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
    ) -> None:
        self._routes = routes
        self._providers = providers

    async def route(self, alias: str, body: dict[str, Any]) -> RoutedResponse:
        """Send the request to the targets of `alias` in order, until one answers.

        An `InvalidRequest` stops the loop: the client request is wrong, and
        every other target would refuse it too. Any other provider error moves
        on to the next target.

        Raises:
            UnknownAlias: the alias is not defined.
            NoEnabledTarget: none of the alias targets can be used.
            TargetRejectedRequest: a target refused the client request.
            RequestTooLarge: the request is too large for every target.
            AllTargetsFailed: every target failed for another reason.
        """
        targets = self._routes.get(alias)
        if targets is None:
            raise UnknownAlias(alias)
        if not targets:
            raise NoEnabledTarget(alias)
        failures: list[tuple[Target, ProviderError]] = []
        for index, target in enumerate(targets):
            provider = self._providers[target.provider.name]
            try:
                response = await provider.chat_completion(target.model, body)
            except InvalidRequest as error:
                raise TargetRejectedRequest(target, error) from error
            except ProviderError as error:
                if isinstance(error, TargetMisconfigured):
                    logger.error(
                        "target %s is misconfigured (HTTP %s): check its API key and model name",
                        target.name,
                        error.status_code,
                    )
                failures.append((target, error))
                continue
            return RoutedResponse(
                body={**response.body, "model": target.model}, target=target, fallbacks=index
            )
        if all(isinstance(error, ContextTooLarge) for _, error in failures):
            raise RequestTooLarge(alias)
        raise AllTargetsFailed(alias, failures)
