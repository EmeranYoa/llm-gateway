"""Which requests and answers are safe to replay from the response cache.

A cached answer is sent again without calling any model. That is only correct
when the same request would be expected to give the same kind of answer, and
when the stored answer is complete.
"""

from collections.abc import Mapping
from typing import Any

# Fields whose presence (even empty or null) means a replayed answer could be wrong.
_UNSAFE_FIELDS = frozenset({"tools", "functions", "seed"})


def request_can_use_cache(body: Mapping[str, Any]) -> bool:
    """True when the request `body` may read and write the response cache.

    - `tools` and `functions`: the answer may call a tool whose result changes
      over time, so an old answer is not safe to replay.
    - `n > 1`: the client asks for several different answers, not a stored one.
    - `seed`: the client controls sampling itself and expects it to be applied.
    - non-text content parts (images, audio, ...): an image URL can point to
      new content while the request stays identical, and the cache only
      compares text.
    """
    if _UNSAFE_FIELDS & body.keys():
        return False
    if body.get("n") not in (None, 1):
        return False
    return all(_is_text_only(message) for message in body.get("messages") or [])


def answer_can_be_stored(body: Mapping[str, Any]) -> bool:
    """True when the answer `body` is complete: every choice ended with `finish_reason: "stop"`.

    A cut answer (`length`, `content_filter`), a tool call or an unknown ending
    would be replayed as if it were a normal answer, so it is not stored.
    """
    choices = body.get("choices") or []
    return bool(choices) and all(
        isinstance(choice, Mapping) and choice.get("finish_reason") == "stop" for choice in choices
    )


def _is_text_only(message: Mapping[str, Any]) -> bool:
    """True when `message` has plain string content or a list of text parts only."""
    content = message.get("content")
    if not isinstance(content, list):
        return True
    return all(isinstance(part, Mapping) and part.get("type") == "text" for part in content)
