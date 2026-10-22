"""A streamed answer once it has reached its commit point.

Before the commit point (the first chunk with content), a stream is handled like
any other attempt: the router can still fail over. `CommittedStream` is what the
router returns once a target has sent content: the target is fixed, and the
client receives the chunks already read, then the rest of the stream.

After the commit point the request deadline no longer applies, so long answers
are not cut. Two other limits replace it: the time between two chunks (idle
timeout) and the total time of the stream (maximum duration).
"""

import asyncio
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import anyio

from app.config import StreamSection, Target
from app.providers.base import ProviderError, StreamChunk


class StreamInterrupted(Exception):
    """The stream broke after its commit point. The client must be told."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
        on_end: Callable[[], Awaitable[None]],
        on_interrupted: Callable[[str], Awaitable[None]],
        on_cancelled: Callable[[], Awaitable[None]],
    ) -> None:
        self.target = target
        self.fallbacks = fallbacks
        """Number of targets examined before the one that answered."""
        self._read_so_far = read_so_far
        self._rest = rest
        self._limits = limits
        self._on_end = on_end
        self._on_interrupted = on_interrupted
        self._on_cancelled = on_cancelled

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
            yield chunk.data
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
            yield chunk.data
        await self._on_end()

    async def _interrupt(self, reason: str) -> None:
        await self._rest.aclose()
        await self._on_interrupted(reason)
        raise StreamInterrupted(reason)
