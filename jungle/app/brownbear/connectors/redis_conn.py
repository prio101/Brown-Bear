"""Redis connector (spec 001 §1.3).

Exposes the counters spec 001 §1.5 needs for cache hit/miss analytics.
"""

from typing import Any

import redis.asyncio as aioredis

from brownbear.config import get_settings
from brownbear.connectors.base import ServiceHealth, timed_check

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Shared Redis client. The stack requires AUTH — the password is in the URL."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.health_timeout_seconds,
            socket_timeout=settings.health_timeout_seconds,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def info() -> dict[str, Any]:
    return await get_redis().info()


async def check() -> ServiceHealth:
    async def probe() -> dict[str, Any]:
        client = get_redis()
        await client.ping()
        stats = await client.info()
        hits = int(stats.get("keyspace_hits", 0))
        misses = int(stats.get("keyspace_misses", 0))
        total = hits + misses
        return {
            "version": stats.get("redis_version"),
            "used_memory_human": stats.get("used_memory_human"),
            "connected_clients": stats.get("connected_clients"),
            "keyspace_hits": hits,
            "keyspace_misses": misses,
            "hit_rate": round(hits / total, 4) if total else None,
            "evicted_keys": stats.get("evicted_keys"),
        }

    return await timed_check("redis", probe)
