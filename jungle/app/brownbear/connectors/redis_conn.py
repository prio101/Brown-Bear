"""Redis connector (spec 001 §1.3).

Exposes the counters spec 001 §1.5 needs for cache hit/miss analytics, and the
best-effort key/value helpers the embedding cache uses (BB-201).

Until BB-201 this module only ever called ``ping()`` and ``info()``, which meant
``keyspace_hits`` was pinned at zero by construction: the dashboard reported a
metric for work that was never done.
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from brownbear.config import get_settings
from brownbear.connectors.base import ServiceHealth, timed_check

logger = logging.getLogger(__name__)

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


async def cache_get(key: str) -> Any | None:
    """Read a JSON value. Returns None on a miss *or* any failure.

    Best-effort by design (BB-201): a cache that can break the thing it
    accelerates is worse than no cache, and this stack's rule is that Brown Bear
    being unwell degrades work rather than blocking it. Every failure mode —
    Redis down, timeout, corrupt payload — is a miss, and the caller recomputes.
    """
    try:
        raw = await get_redis().get(key)
    except Exception:  # noqa: BLE001 — any Redis failure is a miss, never an error
        logger.debug("cache read failed for %s", key, exc_info=True)
        return None

    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # A value we cannot parse is indistinguishable from absent, and deleting
        # it costs another round trip for no benefit — it will expire.
        logger.debug("cache value for %s was unparseable", key)
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int) -> bool:
    """Write a JSON value with a TTL. False on any failure, never raises.

    The TTL is mandatory: an embedding cache without expiry grows without bound
    on a machine that is also running a model server.
    """
    try:
        await get_redis().set(key, json.dumps(value), ex=max(1, ttl_seconds))
        return True
    except Exception:  # noqa: BLE001 — a failed write must not fail the request
        logger.debug("cache write failed for %s", key, exc_info=True)
        return False


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
