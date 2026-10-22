"""A streamed answer once it has reached its commit point.

Before the commit point (the first chunk with content), a stream is handled like
any other attempt: the router can still fail over. `CommittedStream` is what the
router returns once a target has sent content: the target is fixed, and the
client receives the chunks already read, then the rest of the stream.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from app.config import Target
from app.providers.base import StreamChunk


class CommittedStream:
    """The stream of the target that answered, from its first chunk to its end."""

    def __init__(
        self,
        target: Target,
        fallbacks: int,
        read_so_far: Sequence[StreamChunk],
        rest: AsyncIterator[StreamChunk],
        on_end: Callable[[], Awaitable[None]],
    ) -> None:
        self.target = target
        self.fallbacks = fallbacks
        """Number of targets examined before the one that answered."""
        self._read_so_far = read_so_far
        self._rest = rest
        self._on_end = on_end

    async def chunks(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every chunk of the answer, then record the end of the stream."""
        for chunk in self._read_so_far:
            yield chunk.data
        async for chunk in self._rest:
            yield chunk.data
        await self._on_end()
