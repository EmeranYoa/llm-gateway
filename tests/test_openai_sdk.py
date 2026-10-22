"""The official OpenAI Python SDK works against the gateway by changing only base_url."""

import openai
import pytest
import respx
from httpx import AsyncClient

from tests.conftest import new_api_key
from tests.upstream import GROQ_URL, chunk, completion_body, stream_response


@pytest.fixture
async def sdk(chat_client: AsyncClient, database_url: str) -> openai.AsyncOpenAI:
    """The official SDK, with a gateway API key as `api_key` and the gateway as `base_url`."""
    return openai.AsyncOpenAI(
        base_url="http://gateway/v1",
        api_key=await new_api_key(database_url),
        http_client=chat_client,
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


async def test_sdk_streams_a_chat_completion(
    sdk: openai.AsyncOpenAI, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(GROQ_URL).mock(
        return_value=stream_response(
            chunk(role="assistant", content=""), chunk("Hel"), chunk("lo"), "[DONE]"
        )
    )

    stream = await sdk.chat.completions.create(
        model="chat-fast", messages=[{"role": "user", "content": "Hi"}], stream=True
    )
    text = "".join([part.choices[0].delta.content or "" async for part in stream])

    assert text == "Hello"
