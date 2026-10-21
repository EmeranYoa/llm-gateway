"""Provider interface shared by every upstream LLM provider.

The router only talks to this interface. It never depends on details of a
specific provider (URLs, headers, error formats).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderResponse:
    """A successful chat completion returned by a provider."""

    body: dict[str, Any]


class ProviderError(Exception):
    """Base class for the common error types every provider must raise.

    Providers translate upstream failures into these types, so the router can
    decide what to do (fail over or not) without knowing the provider.
    """


class RateLimited(ProviderError):
    """HTTP 429: the provider refuses the call because a limit is reached."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """HTTP 5xx, network error or timeout: the provider cannot answer right now."""


class TargetMisconfigured(ProviderError):
    """HTTP 401, 403 or 404: bad API key or removed model.

    This is a gateway configuration problem, not a client problem.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"misconfigured (HTTP {status_code})")
        self.status_code = status_code


class ContextTooLarge(ProviderError):
    """The request is too large for this target, but may fit a larger one."""

    def __init__(self) -> None:
        super().__init__("request too large for this model")


class InvalidRequest(ProviderError):
    """Any other HTTP 4xx: the client request itself is wrong.

    The router returns it to the client without failover, because every
    provider would refuse it too.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str = "invalid_request_error",
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.param = param
        self.code = code


class Provider(ABC):
    """An upstream service that can run chat completions."""

    @abstractmethod
    async def chat_completion(self, model: str, body: dict[str, Any]) -> ProviderResponse:
        """Run a chat completion with `model`.

        `body` is the client request in OpenAI format. It is sent unchanged,
        except for the `model` field, which is replaced by `model`.

        Raises one of the `ProviderError` subclasses when the call fails.
        """
