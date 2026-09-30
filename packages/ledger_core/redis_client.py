from __future__ import annotations

from redis.asyncio import Redis

_redis: Redis | None = None


def init_redis(url: str) -> Redis:
    global _redis
    _redis = Redis.from_url(url, decode_responses=True)
    return _redis


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialized — call init_redis() first")
    return _redis
