"""The test Redis must be the one the gateway needs: Redis 8, with its vector search."""

from redis.asyncio import Redis


async def test_redis_can_index_vectors(redis_url: str) -> None:
    # The semantic cache stores question embeddings in a Redis vector index.
    redis = Redis.from_url(redis_url)
    try:
        created = await redis.execute_command(
            "FT.CREATE", "test_vectors", "ON", "HASH", "PREFIX", "1", "test_vectors:",
            "SCHEMA", "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", "4", "DISTANCE_METRIC", "COSINE",
        )  # fmt: skip
        await redis.execute_command("FT.DROPINDEX", "test_vectors")
    finally:
        await redis.aclose()

    assert created == b"OK"
