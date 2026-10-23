"""Route a chat completion request from an alias to a real provider/model target."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import Any

import anyio

from app.config import StreamSection, Target
from app.providers.base import (
    ContextTooLarge,
    InvalidRequest,
    Provider,
    ProviderError,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    StreamChunk,
    TargetMisconfigured,
)
from app.routing.acquisition import Refusal, Reservation, TargetGate
from app.routing.quotas import estimate_call_tokens, estimate_prompt_tokens
from app.routing.streaming import CommittedStream, StreamUsage
from app.schemas import asks_for_stream_usage

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

    def __init__(
        self,
        alias: str,
        failures: list[tuple[Target, ProviderError | Refusal]],
        retry_after: float | None,
    ) -> None:
        super().__init__(f"All targets of alias '{alias}' failed: {_describe_failures(failures)}")
        self.alias = alias
        self.retry_after = retry_after
        """Smallest known wait before a target can be called again, or None if unknown."""


class DeadlineExceeded(Exception):
    """The gateway deadline ran out before a target answered."""

    def __init__(
        self, alias: str, deadline: float, failures: list[tuple[Target, ProviderError | Refusal]]
    ) -> None:
        super().__init__(
            f"Alias '{alias}' could not be served within the gateway deadline of {deadline:g} s: "
            f"{_describe_failures(failures)}"
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


class Outcome(StrEnum):
    """What happened to one examined target."""

    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    MISCONFIGURED = "misconfigured"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_TOO_LARGE = "context_too_large"
    SKIPPED_COOLDOWN = "skipped_cooldown"
    SKIPPED_BREAKER = "skipped_breaker"
    SKIPPED_QUOTA = "skipped_quota"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Attempt:
    """One target examined for a request, and its outcome. The usage log stores one row each."""

    target: Target
    outcome: Outcome
    latency_ms: int | None = None
    """Total duration of the call. For a stream, until its last chunk."""
    first_token_ms: int | None = None
    """For a streamed answer: time from the start of the call to its first content."""
    status_code: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error_message: str | None = None
    estimated_tokens: int | None = None
    degraded: bool = False
    """True when the call was made without Redis checks (degraded mode)."""

    @classmethod
    def skipped(
        cls, target: Target, outcome: "Outcome", reason: str, estimated_tokens: int
    ) -> "Attempt":
        """Build the attempt of a target that was examined but not called."""
        return cls(target, outcome, error_message=reason, estimated_tokens=estimated_tokens)

    @classmethod
    def succeeded(
        cls,
        target: Target,
        response: ProviderResponse,
        latency_ms: int,
        reservation: Reservation,
    ) -> "Attempt":
        """Build the attempt of a successful provider call."""
        return cls(
            target,
            Outcome.SUCCESS,
            latency_ms=latency_ms,
            # Providers only return a response for a successful upstream call.
            status_code=HTTPStatus.OK,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            estimated_tokens=reservation.tokens,
            degraded=reservation.degraded,
        )

    @classmethod
    def cancelled(cls, call: "_Call", first_token_ms: int | None = None) -> "Attempt":
        """Build the attempt of a call the client left before it ended."""
        return cls(
            call.target,
            Outcome.CANCELLED,
            latency_ms=call.elapsed_ms(),
            first_token_ms=first_token_ms,
            error_message="the client closed the connection",
            estimated_tokens=call.reservation.tokens,
            degraded=call.reservation.degraded,
        )

    @classmethod
    def failed(
        cls, target: Target, error: ProviderError, latency_ms: int, reservation: Reservation
    ) -> "Attempt":
        """Build the attempt of a provider call that raised `error`."""
        return cls(
            target,
            _outcome_of(error),
            latency_ms=latency_ms,
            status_code=error.status_code,
            error_message=_describe(error),
            estimated_tokens=reservation.tokens,
            degraded=reservation.degraded,
        )


def _skip_outcome(refusal: Refusal) -> Outcome:
    """The usage log outcome of a target that `TargetGate.acquire` refused."""
    if refusal.reason == "cooldown":
        return Outcome.SKIPPED_COOLDOWN
    if refusal.reason == "breaker":
        return Outcome.SKIPPED_BREAKER
    return Outcome.SKIPPED_QUOTA


def _outcome_of(error: ProviderError) -> Outcome:
    """Map a common provider error type to its usage log outcome."""
    match error:
        case RateLimited():
            return Outcome.RATE_LIMITED
        case ProviderTimeout():
            return Outcome.TIMEOUT
        case TargetMisconfigured():
            return Outcome.MISCONFIGURED
        case ContextTooLarge():
            return Outcome.CONTEXT_TOO_LARGE
        case InvalidRequest():
            return Outcome.INVALID_REQUEST
        case _:
            return Outcome.UNAVAILABLE


def _describe(error: ProviderError) -> str:
    """Describe a provider error without any text that may come from the prompt.

    The upstream message of a client error is left out: some providers quote
    the invalid input in it. Other error messages are written by the gateway.
    """
    if not isinstance(error, InvalidRequest):
        return str(error)
    details = [f"HTTP {error.status_code}", f"type: {error.error_type}"]
    if error.code:
        details.append(f"code: {error.code}")
    if error.param:
        details.append(f"param: {error.param}")
    return f"invalid request ({', '.join(details)})"


@dataclass(frozen=True)
class RoutedResponse:
    """The response returned to the client, and how it was routed."""

    body: dict[str, Any]
    target: Target
    fallbacks: int
    """Number of targets examined before the one that answered."""
    used_tokens: int | None = None
    """Tokens the target reported using (prompt and completion), or None if it did not say."""


class Router:
    def __init__(
        self,
        routes: Mapping[str, tuple[Target, ...]],
        providers: Mapping[str, Provider],
        gate: TargetGate,
        *,
        deadline: float,
        min_attempt_time: float,
        default_completion_tokens: int,
        stream_limits: StreamSection,
    ) -> None:
        self._routes = routes
        self._providers = providers
        self._gate = gate
        self._deadline = deadline
        self._min_attempt_time = min_attempt_time
        self._default_completion_tokens = default_completion_tokens
        self._stream_limits = stream_limits

    async def route(
        self,
        alias: str,
        body: dict[str, Any],
        *,
        attempts: list[Attempt],
        redis_down: bool = False,
        started: float | None = None,
    ) -> RoutedResponse:
        """Send the request to the targets of `alias` in order, until one answers.

        Each target is skipped without a call when the prompt alone is larger
        than its TPM, or when `TargetGate.acquire` refuses it (cooldown, open
        circuit breaker, or a full RPM/TPM/RPD quota). Otherwise its quota is reserved, the provider
        is called, and the reservation is then corrected or released.

        An `InvalidRequest` stops the loop: the client request is wrong, and
        every other target would refuse it too. Any other provider error moves
        on to the next target. A 429 or a misconfiguration error puts the
        target in cooldown for the next requests.

        The whole request must finish within the gateway deadline. Each attempt
        gets `min(model timeout, remaining deadline)`, and no new attempt starts
        when less than `min_attempt_time` remains.

        Every examined target is appended to `attempts`, whether routing succeeds
        or raises, so the caller can log the full routing path in both cases.

        `redis_down` tells that Redis already failed for this request (during
        the tenant quota check): targets are then called without waiting for it.

        `started` is when the request started (`time.monotonic()`), so that work done
        before routing (the cache lookup) counts in the deadline. Now by default.

        Raises:
            UnknownAlias: the alias is not defined.
            NoEnabledTarget: none of the alias targets can be used.
            TargetRejectedRequest: a target refused the client request.
            DeadlineExceeded: the deadline ran out before a target answered.
            RequestTooLarge: the request is too large for every target.
            AllTargetsFailed: every target failed or was skipped for another reason.
                Its `retry_after` is the smallest known wait among those targets.
        """

        async def answer(call: _Call) -> RoutedResponse:
            response = await _call_with_timeout(
                call.provider, call.target.model, body, call.timeout
            )
            await self._gate.record_success(call.target, call.reservation, response.total_tokens)
            attempts.append(
                Attempt.succeeded(call.target, response, call.elapsed_ms(), call.reservation)
            )
            return RoutedResponse(
                body={**response.body, "model": call.target.model},
                target=call.target,
                fallbacks=call.index,
                used_tokens=response.total_tokens,
            )

        return await self._try_targets(
            alias, body, attempts=attempts, redis_down=redis_down, started=started, answer=answer
        )

    async def route_stream(
        self,
        alias: str,
        body: dict[str, Any],
        *,
        attempts: list[Attempt],
        redis_down: bool = False,
        started: float | None = None,
    ) -> CommittedStream:
        """Like `route`, for a streamed answer: fail over until a target sends content.

        Each target is tried as in `route`, but its answer is read only until its
        first chunk with content: the commit point. Any error before it fails over
        as usual, including an error event sent after a 200. At the commit point,
        the target is fixed, the breaker records a success, and the caller relays
        the stream. The tokens are corrected and the attempt appended to
        `attempts` when the stream ends.

        The provider is always asked for the usage of the stream, which the quotas
        need. When the client did not ask for it, it is removed from the chunks
        the client gets (ADR 0005).

        Raises the same errors as `route`.
        """
        client_asks_usage = asks_for_stream_usage(body)
        upstream_body = body if client_asks_usage else _with_usage(body)

        async def answer(call: _Call) -> CommittedStream:
            stream = call.provider.stream_chat_completion(
                call.target.model, upstream_body, timeout=call.timeout
            )
            try:
                read_so_far = await _read_until_content(stream, call.timeout)
            except BaseException:
                await stream.aclose()
                raise
            # A stream that ended without content (an empty answer) has no first content.
            sent_content = bool(read_so_far) and read_so_far[-1].has_content
            first_token_ms = call.elapsed_ms() if sent_content else None
            await self._gate.record_commit(call.target, call.reservation)

            async def on_end(usage: StreamUsage) -> None:
                await self._gate.record_stream_end(call.target, call.reservation, usage.used_tokens)
                attempts.append(
                    Attempt(
                        call.target,
                        Outcome.SUCCESS,
                        latency_ms=call.elapsed_ms(),
                        first_token_ms=first_token_ms,
                        status_code=HTTPStatus.OK,
                        prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                        estimated_tokens=call.reservation.tokens,
                        degraded=call.reservation.degraded,
                    )
                )

            async def on_cancelled() -> None:
                await self._gate.record_cancelled(call.target, call.reservation)
                attempts.append(Attempt.cancelled(call, first_token_ms))

            async def on_interrupted(reason: str) -> None:
                await self._gate.record_stream_interrupted(call.target, call.reservation)
                attempts.append(
                    Attempt(
                        call.target,
                        Outcome.INTERRUPTED,
                        latency_ms=call.elapsed_ms(),
                        first_token_ms=first_token_ms,
                        # The client did receive a 200 before the stream broke.
                        status_code=HTTPStatus.OK,
                        error_message=reason,
                        estimated_tokens=call.reservation.tokens,
                        degraded=call.reservation.degraded,
                    )
                )

            return CommittedStream(
                call.target,
                call.index,
                read_so_far,
                stream,
                limits=self._stream_limits,
                prompt_estimate=estimate_prompt_tokens(body),
                hide_usage=not client_asks_usage,
                on_end=on_end,
                on_interrupted=on_interrupted,
                on_cancelled=on_cancelled,
            )

        return await self._try_targets(
            alias, body, attempts=attempts, redis_down=redis_down, started=started, answer=answer
        )

    async def _try_targets[T](
        self,
        alias: str,
        body: dict[str, Any],
        *,
        attempts: list[Attempt],
        redis_down: bool,
        started: float | None,
        answer: Callable[["_Call"], Awaitable[T]],
    ) -> T:
        """The failover loop shared by `route` and `route_stream`.

        For each target: skip it or reserve its quota, then call `answer`, which
        talks to the provider, records the success and returns the result. A
        provider error raised by `answer` is recorded here and fails over.
        """
        targets = self._routes.get(alias)
        if targets is None:
            raise UnknownAlias(alias)
        if not targets:
            raise NoEnabledTarget(alias)
        deadline_at = (started if started is not None else time.monotonic()) + self._deadline
        prompt_tokens = estimate_prompt_tokens(body)
        failures: list[tuple[Target, ProviderError | Refusal]] = []
        waits: list[float] = []
        # Once Redis has failed for this request, do not wait for it again.
        for index, target in enumerate(targets):
            remaining = deadline_at - time.monotonic()
            if remaining < self._min_attempt_time:
                raise DeadlineExceeded(alias, self._deadline, failures)
            tpm = target.limits.tpm
            if tpm is not None and prompt_tokens > tpm:
                # Even an empty window could not hold this prompt: skip without a penalty.
                reason = f"prompt estimate of {prompt_tokens} tokens is above the TPM of {tpm}"
                attempts.append(
                    Attempt.skipped(target, Outcome.CONTEXT_TOO_LARGE, reason, prompt_tokens)
                )
                failures.append((target, ContextTooLarge()))
                continue
            estimated_tokens = estimate_call_tokens(
                prompt_tokens, body, self._default_completion_tokens, tpm
            )
            attempt_timeout = min(target.limits.timeout, remaining)
            if redis_down:
                acquired: Reservation | Refusal = Reservation.without_redis(estimated_tokens)
            else:
                acquired = await self._gate.acquire(target, estimated_tokens, attempt_timeout)
                redis_down = isinstance(acquired, Reservation) and acquired.degraded
            if isinstance(acquired, Refusal):
                attempts.append(
                    Attempt.skipped(
                        target, _skip_outcome(acquired), str(acquired), estimated_tokens
                    )
                )
                failures.append((target, acquired))
                waits.append(acquired.wait_seconds)
                continue
            call = _Call(
                index=index,
                target=target,
                provider=self._providers[target.provider.name],
                reservation=acquired,
                timeout=attempt_timeout,
                started=time.perf_counter(),
            )
            try:
                return await answer(call)
            except asyncio.CancelledError:
                # The client left: no more targets, and not the provider's fault.
                attempts.append(Attempt.cancelled(call))
                with anyio.CancelScope(shield=True):
                    await self._gate.record_cancelled(target, acquired)
                raise
            except InvalidRequest as error:
                attempts.append(Attempt.failed(target, error, call.elapsed_ms(), acquired))
                await self._record_failure(target, acquired, error)
                raise TargetRejectedRequest(target, error) from error
            except ProviderError as error:
                attempts.append(Attempt.failed(target, error, call.elapsed_ms(), acquired))
                failures.append((target, error))
                cooldown = await self._record_failure(target, acquired, error)
                if cooldown is not None:
                    waits.append(cooldown)
                if isinstance(error, ProviderTimeout) and attempt_timeout < target.limits.timeout:
                    # The deadline cut this attempt short, not the model's own timeout.
                    raise DeadlineExceeded(alias, self._deadline, failures) from error
                continue
        if all(isinstance(error, ContextTooLarge) for _, error in failures):
            raise RequestTooLarge(alias)
        raise AllTargetsFailed(alias, failures, retry_after=min(waits, default=None))

    async def _record_failure(
        self, target: Target, reservation: Reservation, error: ProviderError
    ) -> float | None:
        """Update the shared state of `target` after a failed call.

        Returns the cooldown the target is now in, in seconds, or None.
        """
        if isinstance(error, RateLimited):
            return await self._gate.record_rate_limited(target, reservation, error.retry_after)
        if isinstance(error, TargetMisconfigured):
            logger.error(
                "target %s is misconfigured (HTTP %s): check its API key and model name",
                target.name,
                error.status_code,
            )
            return await self._gate.record_misconfigured(target, reservation)
        await self._gate.record_failure(
            target,
            reservation,
            keep_tokens=isinstance(error, ProviderTimeout),
            # 5xx, network errors and timeouts: the provider failed. Client errors
            # (invalid request, context too large) mean the provider worked.
            provider_failed=isinstance(error, ProviderUnavailable),
        )
        return None


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


def _describe_failures(failures: list[tuple[Target, ProviderError | Refusal]]) -> str:
    return "; ".join(f"{target.name}: {error}" for target, error in failures)


@dataclass(frozen=True)
class _Call:
    """One call to a target whose quota is reserved."""

    index: int
    """Position of the target in the alias: the number of targets examined before it."""
    target: Target
    provider: Provider
    reservation: Reservation
    timeout: float
    started: float

    def elapsed_ms(self) -> int:
        return _elapsed_ms(self.started)


def _with_usage(body: dict[str, Any]) -> dict[str, Any]:
    """The request with `include_usage` added to its stream options, the others kept."""
    options = body.get("stream_options")
    kept = options if isinstance(options, dict) else {}
    return {**body, "stream_options": {**kept, "include_usage": True}}


async def _read_until_content(
    stream: AsyncGenerator[StreamChunk], attempt_timeout: float
) -> list[StreamChunk]:
    """Read a stream until its first chunk with content (the commit point).

    Gives up with `ProviderTimeout` when no content arrives within `attempt_timeout`.
    A stream that ends without content returns what it sent: an empty answer.
    """
    read_so_far: list[StreamChunk] = []
    try:
        async with asyncio.timeout(attempt_timeout):
            async for chunk in stream:
                read_so_far.append(chunk)
                if chunk.has_content:
                    break
    except TimeoutError as error:
        raise ProviderTimeout() from error
    return read_so_far


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
