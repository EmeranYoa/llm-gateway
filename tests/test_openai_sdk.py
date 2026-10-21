"""The official OpenAI Python SDK works against the gateway by changing only base_url."""

import openai
import pytest
import respx
from httpx import AsyncClient

from tests.upstream import GROQ_URL, completion_body


@pytest.fixture
def sdk(chat_client: AsyncClient) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        base_url="http://gateway/v1", api_key="not-checked-by-the-gateway", http_client=chat_client
    )


async def test_sdk_gets_a_chat_completion(
    sdk: openai.AsyncOpenAI, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).respond(json=completion_body("llama-3.3-70b-versatile"))

    completion = await sdk.chat.completions.create(
        model="chat-fast", messages=[{"role": "user", "content": "Hi"}]
    )

    assert completion.choices[0].message.content == "Hello!"
    assert completion.model == "llama-3.3-70b-versatile"


async def test_sdk_raises_typed_error_for_unknown_alias(sdk: openai.AsyncOpenAI) -> None:
    with pytest.raises(openai.NotFoundError) as error:
        await sdk.chat.completions.create(
            model="no-such-alias", messages=[{"role": "user", "content": "Hi"}]
        )

    assert error.value.code == "model_not_found"
