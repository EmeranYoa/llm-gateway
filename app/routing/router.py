"""Route a chat completion request from an alias to a real provider/model target."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.config import Target
from app.providers.base import Provider


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
        """Send the request to the first target of `alias`.

        Raises `UnknownAlias` when the alias is not defined, and
        `NoEnabledTarget` when none of its targets can be used.
        """
        targets = self._routes.get(alias)
        if targets is None:
            raise UnknownAlias(alias)
        if not targets:
            raise NoEnabledTarget(alias)
        target = targets[0]
        provider = self._providers[target.provider.name]
        response = await provider.chat_completion(target.model, body)
        return RoutedResponse(
            body={**response.body, "model": target.model}, target=target, fallbacks=0
        )
