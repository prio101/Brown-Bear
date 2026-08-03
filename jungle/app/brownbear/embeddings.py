"""Cached embeddings (BB-201).

Every ``/ext/context`` call embeds the incoming prompt through Ollama, and that is
the only per-request model call in the gateway's hot path. In a coding loop the
same prompt recurs often — a repeated question, a retried turn, two machines
asking the same thing — so the vector is worth keeping.

This is also what gives Redis a job. Before this, the connector only called
``ping()`` and ``info()``: no key was ever written, so ``keyspace_hits`` could
only ever be zero, and the dashboard charted a metric for work that did not
happen.

Two rules make the cache safe to trust:

1. **The model name is part of the key.** A ``nomic-embed-text`` vector is not
   valid for any other model, and serving one silently would corrupt every
   similarity score computed from it — which the gateway then compares to a 0.95
   cutoff. This is the one correctness constraint that matters here.
2. **A cache failure is a miss, never an error.** Redis being down must degrade
   to recomputing, not break retrieval. Spec 005 requires that Brown Bear being
   unwell degrades context rather than blocking work.

Document ingestion deliberately does *not* use this. Chunks are near-unique, so
caching them would spend memory on entries that never repeat, and ingestion is
already idempotent by content id.
"""

import hashlib

from brownbear.config import get_settings
from brownbear.connectors import ollama
from brownbear.connectors import redis_conn

KEY_PREFIX = "bb:emb"


def cache_key(text: str, model: str) -> str:
    """Namespaced, model-scoped, content-addressed.

    The digest rather than the text: prompts run to 32k characters, and a Redis
    key that size is both wasteful and awkward to inspect.
    """
    digest = hashlib.sha256(text.encode()).hexdigest()
    return f"{KEY_PREFIX}:{model}:{digest}"


def _is_vector(value: object, ) -> bool:
    """Guard against a payload that is the right shape but the wrong thing.

    A cached value that is not a list of numbers would otherwise reach Chroma and
    fail there, far from the cause.
    """
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, (int, float)) for item in value)
    )


async def embed_one(text: str, model: str | None = None) -> list[float]:
    """Embed one text, via Redis when possible.

    Falls through to Ollama on a miss, a corrupt entry, or any Redis failure.
    """
    settings = get_settings()
    name = model or settings.embedding_model

    if not settings.embedding_cache_enabled:
        return await ollama.embed_one(text, model=name)

    key = cache_key(text, name)
    cached = await redis_conn.cache_get(key)
    if _is_vector(cached):
        return cached  # type: ignore[return-value]

    vector = await ollama.embed_one(text, model=name)
    await redis_conn.cache_set(key, vector, settings.embedding_cache_ttl_seconds)
    return vector
