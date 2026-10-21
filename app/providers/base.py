"""Provider interface shared by every upstream LLM provider.

The router only talks to this interface. It never depends on details of a
specific provider (URLs, headers, error formats).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderResponse:
    """A successful chat completion returned by a provider.

    Token counts come from the provider `usage` field, or are None when it is missing.
    """

    body: dict[str, Any]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        """Prompt plus completion tokens, or None when either is unknown."""
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


class ProviderError(Exception):
    """Base class for the common error types every provider must raise.

    Providers translate upstream failures into these types, so the router can
    decide what to do (fail over or not) without knowing the provider.

    `status_code` is the upstream HTTP status, or None when no response came back
    (network error, timeout).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimited(ProviderError):
    """HTTP 429: the provider refuses the call because a limit is reached."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__("rate limited", status_code=429)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """HTTP 5xx, network error or timeout: the provider cannot answer right now."""


class ProviderTimeout(ProviderUnavailable):
    """The provider did not answer within the attempt timeout.

    It is a `ProviderUnavailable` for failover, but kept distinct because a
    timed-out call may still have generated tokens upstream.
    """

    def __init__(self) -> None:
        super().__init__("timeout")


class TargetMisconfigured(ProviderError):
    """HTTP 401, 403 or 404: bad API key or removed model.

    This is a gateway configuration problem, not a client problem.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"misconfigured (HTTP {status_code})", status_code)


class ContextTooLarge(ProviderError):
    """The request is too large for this target, but may fit a larger one."""

    def __init__(self, status_code: int | None = None) -> None:
        super().__init__("request too large for this model", status_code)


class InvalidRequest(ProviderError):
    """Any other HTTP 4xx: the client request itself is wrong.

    The router returns it to the client without failover, because every
    provider would refuse it too.
    """

    status_code: int  # always set: the provider answered with an HTTP error

    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str = "invalid_request_error",
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, status_code)
        self.message = message
        self.error_type = error_type
        self.param = param
        self.code = code


class Provider(ABC):
    """An upstream service that can run chat completions."""

    @abstractmethod
    async def chat_completion(
        self,
        model: str,
        body: dict[str, Any],
        timeout: float,  # noqa: ASYNC109 (needed by the HTTP client, see below)
    ) -> ProviderResponse:
        """Run a chat completion with `model`.

        `body` is the client request in OpenAI format. It is sent unchanged,
        except for the `model` field, which is replaced by `model`.

        `timeout` is the time in seconds the call may take. When it runs out,
        the provider raises `ProviderTimeout`. The router also enforces it with
        `asyncio.timeout`, but the provider needs the value to configure its own
        HTTP client, which otherwise applies its own default timeout.

        Raises one of the `ProviderError` subclasses when the call fails.
        """
