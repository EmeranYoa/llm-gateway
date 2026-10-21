"""OpenAI-compatible request and response models."""

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


class ErrorDetail(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class ErrorBody(BaseModel):
    """An error in OpenAI format, so the OpenAI SDK raises its usual typed exceptions."""

    error: ErrorDetail
