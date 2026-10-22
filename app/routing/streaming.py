"""A streamed answer once it has reached its commit point.

Before the commit point (the first chunk with content), a stream is handled like
any other attempt: the router can still fail over. `CommittedStream` is what the
router returns once a target has sent content: the target is fixed, and the
client receives the chunks already read, then the rest of the stream.

After the commit point the request deadline no longer applies, so long answers
are not cut. Two other limits replace it: the time between two chunks (idle
timeout) and the total time of the stream (maximum duration).

The quotas need the token usage of the stream. The gateway asks the provider for
it even when the client did not (ADR 0005): the usage is then read here and
removed from what the client receives.
"""

import asyncio
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import anyio

from app.config import StreamSection, Target
from app.providers.base import ProviderError, StreamChunk
from app.routing.quotas import estimate_tokens


class StreamInterrupted(Exception):
    """The stream broke after its commit point. The client must be told."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class StreamUsage:
    """The tokens a whole stream used."""

    prompt_tokens: int | None
    """As reported by the provider, or None."""
    completion_tokens: int | None
    """As reported by the provider, or None."""
    used_tokens: int
    """Prompt plus completion. Estimated when the provider did not report them: the
    prompt estimate plus the streamed characters / 4."""


class CommittedStream:
    """The stream of the target that answered, from its first chunk to its end."""

    def __init__(
        self,
        target: Target,
        fallbacks: int,
        read_so_far: Sequence[StreamChunk],
        rest: AsyncGenerator[StreamChunk],
        *,
        limits: StreamSection,
        prompt_estimate: int,
        hide_usage: bool,
        on_end: Callable[[StreamUsage], Awaitable[None]],
        on_interrupted: Callable[[str], Awaitable[None]],
        on_cancelled: Callable[[], Awaitable[None]],
    ) -> None:
        """`hide_usage` removes the usage from the chunks, when the client did not ask for it."""
        self.target = target
        self.fallbacks = fallbacks
        """Number of targets examined before the one that answered."""
        self.usage: StreamUsage | None = None
        """The tokens the stream used, known once it ended normally."""
        self._read_so_far = read_so_far
        self._rest = rest
        self._limits = limits
        self._prompt_estimate = prompt_estimate
        self._hide_usage = hide_usage
        self._on_end = on_end
        self._on_interrupted = on_interrupted
        self._on_cancelled = on_cancelled
        self._prompt_tokens: int | None = None
        self._completion_tokens: int | None = None
        self._output_chars = 0

    async def chunks(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every chunk of the answer, then record the end of the stream.

        Raises `StreamInterrupted` when the provider fails, goes silent for longer
        than the idle timeout, or the stream lasts longer than the maximum duration.

        When the client leaves, the web server cancels this generator: the
        provider call is closed and the cancellation recorded before it goes on.
        The clean-up is shielded, because the cancellation would otherwise hit
        every await of the clean-up too.
        """
        for chunk in self._read_so_far:
            if (data := self._for_client(chunk)) is not None:
                yield data
        ends_at = time.monotonic() + self._limits.max_duration
        while True:
            time_left = ends_at - time.monotonic()
            wait = min(self._limits.idle_timeout, time_left)
            try:
                async with asyncio.timeout(max(wait, 0)):
                    chunk = await anext(self._rest)
            except StopAsyncIteration:
                break
            except asyncio.CancelledError:
                # The client left: stop reading from the provider at once.
                with anyio.CancelScope(shield=True):
                    await self._rest.aclose()
                    await self._on_cancelled()
                raise
            except TimeoutError:
                reason = "idle timeout" if wait < time_left else "maximum stream duration reached"
                await self._interrupt(reason)
            except ProviderError as error:
                await self._interrupt(str(error))
            if (data := self._for_client(chunk)) is not None:
                yield data
        self.usage = self._usage()
        await self._on_end(self.usage)

    def _for_client(self, chunk: StreamChunk) -> dict[str, Any] | None:
        """Count the usage and output of `chunk`, and return what the client gets of it.

        Returns None when nothing is left for the client: a chunk that only
        carried the usage the client did not ask for.
        """
        if chunk.prompt_tokens is not None:
            self._prompt_tokens = chunk.prompt_tokens
        if chunk.completion_tokens is not None:
            self._completion_tokens = chunk.completion_tokens
        self._output_chars += chunk.output_chars
        if not self._hide_usage or "usage" not in chunk.data:
            return chunk.data
        data = {key: value for key, value in chunk.data.items() if key != "usage"}
        return data if data.get("choices") else None

    def _usage(self) -> StreamUsage:
        if self._prompt_tokens is not None and self._completion_tokens is not None:
            used_tokens = self._prompt_tokens + self._completion_tokens
        else:
            used_tokens = self._prompt_estimate + estimate_tokens(self._output_chars)
        return StreamUsage(self._prompt_tokens, self._completion_tokens, used_tokens)

    async def _interrupt(self, reason: str) -> None:
        await self._rest.aclose()
        await self._on_interrupted(reason)
        raise StreamInterrupted(reason)
