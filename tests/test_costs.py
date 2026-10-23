"""Tests for costs in the usage log: what each row cost, and what each cache hit saved."""

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.config import ConfigError, Settings, load_config
from tests.conftest import FetchUsageRows, gateway_client
from tests.upstream import (
    CHAT_REQUEST,
    GEMINI_KEY,
    GEMINI_URL,
    GROQ_KEY,
    GROQ_URL,
    completion_body,
    error_body,
)

WriteConfig = Callable[[str], Settings]

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.5-flash"

# Groq is priced, Gemini is not. Prices are in USD per million tokens.
PRICED_CONFIG = f"""
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: GROQ_API_KEY
    models:
      {GROQ_MODEL}: {{ price: {{ input: 0.5, output: 1.5 }} }}
  gemini:
    base_url: https://gemini.test/v1beta/openai
    api_key_env: GEMINI_API_KEY
    models:
      {GEMINI_MODEL}: {{}}
routes:
  chat-fast: [ groq/{GROQ_MODEL} ]
  chat-offline: [ gemini/{GEMINI_MODEL} ]
  chat-failover: [ groq/{GROQ_MODEL}, gemini/{GEMINI_MODEL} ]
"""

# Both aliases use the response cache, without embeddings: identical requests only.
CACHED_CONFIG = PRICED_CONFIG + "cache: { aliases: { chat-fast: {}, chat-offline: {} } }\n"

# (1000 * 0.5 + 2000 * 1.5) / 1_000_000
GROQ_COST = Decimal("0.0035")


def body_with_usage(model: str, prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
    body = completion_body(model)
    body["usage"] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    return body


@pytest.fixture(autouse=True)
def provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_KEY)


@pytest.fixture(autouse=True)
def gemini(respx_mock: respx.MockRouter) -> respx.Route:
    return respx_mock.post(GEMINI_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=body_with_usage(GEMINI_MODEL, 1000, 2000))
    )


@pytest.fixture(autouse=True)
def groq(respx_mock: respx.MockRouter) -> respx.Route:
    return respx_mock.post(GROQ_URL).mock(
        side_effect=lambda _: httpx.Response(200, json=body_with_usage(GROQ_MODEL, 1000, 2000))
    )


async def test_success_row_records_its_cost(
    write_config: WriteConfig, usage_rows: FetchUsageRows
) -> None:
    async with gateway_client(write_config(PRICED_CONFIG)) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    [row] = await usage_rows()
    assert row["outcome"] == "success"
    assert row["cost_usd"] == GROQ_COST
    assert row["saved_cost_usd"] is None


async def test_model_without_price_has_no_cost(
    write_config: WriteConfig, usage_rows: FetchUsageRows
) -> None:
    async with gateway_client(write_config(PRICED_CONFIG)) as client:
        await client.post("/v1/chat/completions", json={**CHAT_REQUEST, "model": "chat-offline"})

    [row] = await usage_rows()
    assert row["outcome"] == "success"
    assert (row["cost_usd"], row["saved_cost_usd"]) == (None, None)


async def test_failed_and_skipped_attempts_have_no_cost(
    write_config: WriteConfig, groq: respx.Route, usage_rows: FetchUsageRows
) -> None:
    groq.side_effect = [httpx.Response(429, json=error_body("slow down", code="rate_limit"))]
    config = PRICED_CONFIG.replace(
        f"{GEMINI_MODEL}: {{}}", f"{GEMINI_MODEL}: {{ price: {{ input: 1, output: 1 }} }}"
    )
    request = {**CHAT_REQUEST, "model": "chat-failover"}

    async with gateway_client(write_config(config)) as client:
        await client.post("/v1/chat/completions", json=request)
        # Groq is now in cooldown: this request skips it.
        await client.post("/v1/chat/completions", json=request)

    rows = await usage_rows()
    assert [(row["outcome"], row["cost_usd"]) for row in rows] == [
        ("rate_limited", None),
        ("success", Decimal("0.003")),
        ("skipped_cooldown", None),
        ("success", Decimal("0.003")),
    ]


async def test_answer_without_usage_has_no_cost(
    write_config: WriteConfig, groq: respx.Route, usage_rows: FetchUsageRows
) -> None:
    body = completion_body(GROQ_MODEL)
    del body["usage"]
    groq.side_effect = [httpx.Response(200, json=body)]

    async with gateway_client(write_config(PRICED_CONFIG)) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    [row] = await usage_rows()
    assert row["outcome"] == "success"
    assert row["cost_usd"] is None


async def test_cache_hit_costs_nothing_and_records_what_it_saved(
    write_config: WriteConfig, usage_rows: FetchUsageRows
) -> None:
    async with gateway_client(write_config(CACHED_CONFIG)) as client:
        await client.post("/v1/chat/completions", json=CHAT_REQUEST)
        hit = await client.post("/v1/chat/completions", json=CHAT_REQUEST)

    assert hit.headers["X-Gateway-Cache"] == "hit"
    miss_row, hit_row = await usage_rows()
    assert (miss_row["cost_usd"], miss_row["saved_cost_usd"]) == (GROQ_COST, None)
    assert hit_row["outcome"] == "cache_hit"
    assert hit_row["cost_usd"] == Decimal(0)
    assert hit_row["saved_cost_usd"] == GROQ_COST


async def test_cache_hit_of_a_model_without_price_saves_an_unknown_amount(
    write_config: WriteConfig, usage_rows: FetchUsageRows
) -> None:
    request = {**CHAT_REQUEST, "model": "chat-offline"}

    async with gateway_client(write_config(CACHED_CONFIG)) as client:
        await client.post("/v1/chat/completions", json=request)
        hit = await client.post("/v1/chat/completions", json=request)

    assert hit.headers["X-Gateway-Cache"] == "hit"
    hit_row = (await usage_rows())[-1]
    assert hit_row["outcome"] == "cache_hit"
    assert hit_row["cost_usd"] == Decimal(0)
    assert hit_row["saved_cost_usd"] is None


def test_prices_of_every_declared_model_are_loaded(write_config: WriteConfig) -> None:
    settings = write_config(PRICED_CONFIG)

    # Gemini is disabled, and has no price anyway.
    config = load_config(settings.gateway_config_path, environ={"GROQ_API_KEY": GROQ_KEY})

    assert set(config.prices) == {("groq", GROQ_MODEL)}
    price = config.prices[("groq", GROQ_MODEL)]
    assert (price.input, price.output) == (Decimal("0.5"), Decimal("1.5"))


@pytest.mark.parametrize(
    "price",
    [
        "{ input: -0.1, output: 1 }",
        "{ input: 1 }",
        "{ output: 1 }",
        "{ input: free, output: 1 }",
        "{ input: .nan, output: 1 }",
        "{ input: 1, output: 1, currency: EUR }",
        "0.5",
    ],
    ids=["negative", "no-output", "no-input", "not-a-number", "nan", "unknown-field", "no-mapping"],
)
def test_invalid_price_stops_the_gateway(write_config: WriteConfig, price: str) -> None:
    settings = write_config(
        PRICED_CONFIG.replace("{ price: { input: 0.5, output: 1.5 } }", f"{{ price: {price} }}")
    )

    with pytest.raises(ConfigError, match="price"):
        load_config(settings.gateway_config_path, environ={"GROQ_API_KEY": GROQ_KEY})


def test_example_config_loads_with_a_price_for_every_model() -> None:
    path = Path(__file__).parent.parent / "config" / "gateway.yaml"
    environ = {
        "GROQ_API_KEY": "key",
        "GEMINI_API_KEY": "key",
        "OPENROUTER_API_KEY": "key",
    }

    config = load_config(path, environ)

    models = {
        (target.provider.name, target.model)
        for targets in config.routes.values()
        for target in targets
    }
    assert set(config.prices) == models
