"""OpenAI-compatible request and response models."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatCompletionRequest(BaseModel):
    """A chat completion request in OpenAI format.

    Only the fields the gateway needs are validated. Every other field
    (`tools`, `response_format`, `temperature`, ...) is kept and sent to the
    provider unchanged.
    """

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]] = Field(min_length=1)
    stream: bool = False

    def prompt_chars(self) -> int:
        """Size of the prompt in characters, so it can be logged instead of the prompt.

        Counts every string value the model reads in `messages`, `tools` and
        `response_format`. JSON keys and punctuation are not counted.
        """
        return count_prompt_chars(self.model_dump(exclude_unset=True))


def count_prompt_chars(body: Mapping[str, Any]) -> int:
    """Count every string value the model reads in `messages`, `tools` and `response_format`."""
    return _count_chars([body.get("messages"), body.get("tools"), body.get("response_format")])


def _count_chars(value: object) -> int:
    """Sum the lengths of every string found in nested lists and dicts."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_count_chars(item) for item in value.values())
    if isinstance(value, list):
        return sum(_count_chars(item) for item in value)
    return 0


class ErrorDetail(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class ErrorBody(BaseModel):
    """An error in OpenAI format, so the OpenAI SDK raises its usual typed exceptions."""

    error: ErrorDetail
