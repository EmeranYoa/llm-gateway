"""Turn a question into a vector, with the one embedding model of the cache.

The model runs behind an OpenAI-compatible `/embeddings` endpoint (Ollama, for
example). Its calls skip the quotas, cooldowns and breakers of chat targets: those
exist to fail over between targets, and the cache never fails over to another
embedding model, whose vectors would not be comparable.
"""

from typing import Any

import httpx

from app.config import EmbeddingSettings


class EmbeddingUnavailable(Exception):
    """The embedding model did not return a vector: the request goes on without the cache."""


class EmbeddingClient:
    def __init__(self, settings: EmbeddingSettings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http_client = http_client

    @property
    def model(self) -> str:
        return self._settings.model

    @property
    def max_chars(self) -> int:
        """Longest text embedded: longer questions only get exact hits."""
        return self._settings.max_chars

    async def embed(self, text: str) -> list[float]:
        """Return the vector of `text`, or raise `EmbeddingUnavailable`."""
        provider = self._settings.provider
        headers = {}
        if provider.api_key is not None:
            headers["Authorization"] = f"Bearer {provider.api_key.get_secret_value()}"
        try:
            response = await self._http_client.post(
                f"{provider.base_url}/embeddings",
                json={"model": self._settings.model, "input": text},
                headers=headers,
                timeout=self._settings.timeout,
            )
            response.raise_for_status()
            return _vector(response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise EmbeddingUnavailable(
                f"embedding model {self._settings.model} failed ({type(error).__name__})"
            ) from error


def _vector(body: Any) -> list[float]:
    """The first vector of an OpenAI-format embedding response."""
    try:
        vector = body["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("no embedding in the response") from error
    if not isinstance(vector, list) or not vector:
        raise ValueError("the embedding is not a list of numbers")
    return [float(value) for value in vector]
