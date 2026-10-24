"""Tests for the token counter kept next to the TPM window of each target (ADR 0009).

The counter holds the total tokens of the window, so a call no longer sums the
whole window. These tests check that it always matches the window, on a real Redis.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from redis.asyncio import Redis

from app.config import GatewayConfig, Target, load_config
from app.routing.acquisition import Refusal, Reservation, TargetGate

MODEL = "llama-3.3-70b-versatile"
WINDOW = f"tpm:groq:{MODEL}"
COUNTER = f"tpm_used:groq:{MODEL}"

CONFIG = f"""
providers:
  groq:
    base_url: https://groq.test/openai/v1
    api_key_env: null
    models:
      {MODEL}: {{ tpm: 1000 }}
routes:
  chat-fast: [ groq/{MODEL} ]
"""


@pytest.fixture
def config(tmp_path: Path) -> GatewayConfig:
    path = tmp_path / "gateway.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return load_config(path, os.environ)


@pytest.fixture
def groq(config: GatewayConfig) -> Target:
    [target] = config.routes["chat-fast"]
    return target


@pytest.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url)
    yield client
    await client.aclose()


@pytest.fixture
def gate(config: GatewayConfig, redis: Redis) -> TargetGate:
    return TargetGate(redis, config.cooldown, config.breaker)


async def reserve(gate: TargetGate, target: Target, tokens: int) -> Reservation:
    result = await gate.acquire(target, estimated_tokens=tokens, attempt_timeout=30)
    assert isinstance(result, Reservation), result
    return result


async def counter(redis: Redis) -> int | None:
    value = await redis.get(COUNTER)
    return None if value is None else int(value)


async def window_total(redis: Redis) -> int:
    """Tokens of the window, summed member by member as v0.5.1 did."""
    members = await redis.zrange(WINDOW, 0, -1)
    return sum(int(member.rsplit(b":", 1)[1]) for member in members)


async def age(redis: Redis, reservation: Reservation, seconds: float) -> None:
    """Move a reservation `seconds` into the past, as if it had been made then."""
    member = f"{reservation.id}:{reservation.tokens}"
    now_s, now_us = await redis.time()
    now_ms = now_s * 1000 + now_us // 1000
    await redis.zadd(WINDOW, {member: now_ms - seconds * 1000}, xx=True)


async def test_reservations_add_their_tokens_to_the_counter(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    await reserve(gate, groq, 100)
    await reserve(gate, groq, 250)

    assert await counter(redis) == 350
    assert await window_total(redis) == 350


async def test_a_refused_call_changes_nothing(gate: TargetGate, groq: Target, redis: Redis) -> None:
    await reserve(gate, groq, 600)

    refusal = await gate.acquire(groq, estimated_tokens=600, attempt_timeout=30)

    assert isinstance(refusal, Refusal) and refusal.reason == "tpm"
    assert 59 <= refusal.wait_seconds <= 60
    assert await counter(redis) == 600
    assert await redis.zcard(WINDOW) == 1


async def test_refusal_waits_for_the_oldest_reservations_that_free_enough_tokens(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    oldest = await reserve(gate, groq, 400)
    await age(redis, oldest, 30)
    await reserve(gate, groq, 400)

    refusal = await gate.acquire(groq, estimated_tokens=400, attempt_timeout=30)

    # Once the oldest reservation leaves the window (in 30 s), 400 tokens fit again.
    assert isinstance(refusal, Refusal) and refusal.reason == "tpm"
    assert 29 <= refusal.wait_seconds <= 30


async def test_released_tokens_leave_the_counter_once(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    kept = await reserve(gate, groq, 100)
    released = await reserve(gate, groq, 250)

    await gate.record_failure(groq, released, keep_tokens=False, provider_failed=True)
    await gate.record_failure(groq, released, keep_tokens=False, provider_failed=True)

    assert await counter(redis) == kept.tokens
    assert await window_total(redis) == kept.tokens


async def test_kept_tokens_stay_in_the_counter(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    reservation = await reserve(gate, groq, 300)

    await gate.record_failure(groq, reservation, keep_tokens=True, provider_failed=True)

    assert await counter(redis) == 300


async def test_correction_replaces_the_estimate_with_the_real_usage(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    other = await reserve(gate, groq, 100)
    overestimated = await reserve(gate, groq, 600)
    underestimated = await reserve(gate, groq, 50)

    await gate.record_success(groq, overestimated, used_tokens=40)
    await gate.record_success(groq, underestimated, used_tokens=200)

    assert await counter(redis) == other.tokens + 40 + 200
    assert await window_total(redis) == other.tokens + 40 + 200


async def test_correction_without_usage_keeps_the_estimate(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    reservation = await reserve(gate, groq, 300)

    await gate.record_success(groq, reservation, used_tokens=None)

    assert await counter(redis) == 300


async def test_expired_reservations_leave_the_counter(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    expired = await reserve(gate, groq, 700)
    await age(redis, expired, 61)

    await reserve(gate, groq, 600)  # fits only once the expired reservation is gone

    assert await counter(redis) == 600
    assert await window_total(redis) == 600


async def test_late_correction_of_an_expired_reservation_keeps_the_counter_right(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    # A long stream: its reservation leaves the window before the stream ends.
    stream = await reserve(gate, groq, 300)
    await age(redis, stream, 61)
    await gate.record_stream_end(groq, stream, used_tokens=900)

    await reserve(gate, groq, 100)

    assert await counter(redis) == 100
    assert await window_total(redis) == 100


async def test_concurrent_reservations_never_over_book_the_counter(
    config: GatewayConfig, groq: Target, redis_url: str, redis: Redis
) -> None:
    # One connection per call, so the calls really reach Redis concurrently.
    clients = [Redis.from_url(redis_url) for _ in range(20)]
    gates = [TargetGate(client, config.cooldown, config.breaker) for client in clients]

    results = await asyncio.gather(
        *(gate.acquire(groq, estimated_tokens=300, attempt_timeout=30) for gate in gates)
    )
    for client in clients:
        await client.aclose()

    assert sum(isinstance(result, Reservation) for result in results) == 3
    assert await counter(redis) == 900
    assert await window_total(redis) == 900


async def test_missing_counter_is_rebuilt_from_the_window(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    # A window left by v0.5.1, which kept no counter.
    for tokens in (300, 300, 300):
        await reserve(gate, groq, tokens)
    await redis.delete(COUNTER)

    refusal = await gate.acquire(groq, estimated_tokens=300, attempt_timeout=30)

    assert isinstance(refusal, Refusal) and refusal.reason == "tpm"
    # Rebuilt once, with the TTL of the window.
    assert await counter(redis) == 900
    assert abs(await redis.pttl(COUNTER) - await redis.pttl(WINDOW)) < 50


async def test_outcome_without_a_counter_leaves_the_rebuild_to_the_next_call(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    kept = await reserve(gate, groq, 100)
    released = await reserve(gate, groq, 250)
    await redis.delete(COUNTER)

    await gate.record_failure(groq, released, keep_tokens=False, provider_failed=True)
    assert await counter(redis) is None

    await reserve(gate, groq, 50)
    assert await counter(redis) == kept.tokens + 50


async def test_counter_is_reset_when_the_window_is_empty(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    # A drifted counter, with nothing left in the window.
    expired = await reserve(gate, groq, 100)
    await age(redis, expired, 61)
    await redis.set(COUNTER, 5000, px=60_000)

    await reserve(gate, groq, 600)

    assert await counter(redis) == 600
    assert await window_total(redis) == 600


async def test_counter_has_the_ttl_of_the_window(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    await reserve(gate, groq, 100)

    window_ttl = await redis.pttl(WINDOW)
    counter_ttl = await redis.pttl(COUNTER)

    assert 59_000 < window_ttl <= 60_000
    assert abs(counter_ttl - window_ttl) < 50


async def test_no_counter_without_a_tpm_limit(tmp_path: Path, redis: Redis) -> None:
    path = tmp_path / "gateway.yaml"
    path.write_text(CONFIG.replace("{ tpm: 1000 }", "{ rpm: 10 }"), encoding="utf-8")
    config = load_config(path, os.environ)
    gate = TargetGate(redis, config.cooldown, config.breaker)

    await reserve(gate, config.routes["chat-fast"][0], 100)

    assert await redis.exists(COUNTER, WINDOW) == 0


async def test_live_state_reports_the_tokens_of_the_window(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    expired = await reserve(gate, groq, 200)
    corrected = await reserve(gate, groq, 300)
    released = await reserve(gate, groq, 150)
    await gate.record_success(groq, corrected, used_tokens=40)
    await gate.record_failure(groq, released, keep_tokens=False, provider_failed=True)
    await age(redis, expired, 61)  # not removed yet: no call since
    before = await counter(redis)

    state = await gate.state(groq)

    assert state.tpm_used == 40
    assert await counter(redis) == before  # read-only


async def test_live_state_without_a_counter_sums_the_window(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    await reserve(gate, groq, 200)
    await reserve(gate, groq, 300)
    await redis.delete(COUNTER)

    state = await gate.state(groq)

    assert state.tpm_used == 500
    assert await counter(redis) is None  # read-only: nothing rebuilt


async def test_live_state_ignores_a_drifted_counter_when_the_window_is_empty(
    gate: TargetGate, groq: Target, redis: Redis
) -> None:
    expired = await reserve(gate, groq, 100)
    await age(redis, expired, 61)
    await redis.set(COUNTER, 5000, px=60_000)

    state = await gate.state(groq)

    assert state.tpm_used == 0
