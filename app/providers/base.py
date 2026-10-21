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


class Provider(ABC):
    """An upstream service that can run chat completions."""

    @abstractmethod
    async def chat_completion(self, model: str, body: dict[str, Any]) -> ProviderResponse:
        """Run a chat completion with `model`.

        `body` is the client request in OpenAI format. It is sent unchanged,
        except for the `model` field, which is replaced by `model`.
        """
