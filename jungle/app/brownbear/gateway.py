"""Context gateway: semantic cache and retrieval (spec 005).

Brown Bear never calls Anthropic. A client asks for context before its own
request, and reports usage afterwards. Two collections do different jobs and
are kept apart deliberately:

  conversations — prior prompt/answer pairs. A cache hit must be a prior
                  *answer*, so only this collection can produce one.
  knowledge     — documents, notes, PDFs. Retrieval only; a paragraph from here
                  must never be served as though it were an answer.

A cache that returns a confidently wrong answer is worse than no cache, so the
rules here are deliberately conservative: strict default threshold, hits scoped
to the same project and model, expiry honoured, and volatile prompts stored but
never served.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio.to_thread

from brownbear import embeddings, settings_store
from brownbear.config import get_settings
from brownbear.connectors import chroma, ollama
from brownbear.db import session_scope
from brownbear.models.monitoring import QueryLog

logger = logging.getLogger(__name__)

# A score this close below the threshold is logged, so the cutoff can be tuned
# from data rather than taste (spec 005).
NEAR_MISS_MARGIN = 0.05

# Prompts whose correct answer depends on when they were asked. These are
# stored — they are still real history — but flagged so they are never served.
VOLATILE_PATTERNS = (
    r"\btoday\b",
    r"\bright now\b",
    r"\bcurrent(ly)?\b",
    r"\bthis (morning|afternoon|evening|week|month|year)\b",
    r"\byesterday\b",
    r"\btomorrow\b",
    r"\bwhat time\b",
    r"\blatest\b",
)
_VOLATILE = re.compile("|".join(VOLATILE_PATTERNS), re.IGNORECASE)

# A prompt carrying a pasted file is effectively unique; caching it wastes
# space and risks matching on the boilerplate rather than the question.
PASTED_CONTENT_CHARS = 4000


def is_volatile(prompt: str) -> bool:
    return bool(_VOLATILE.search(prompt)) or len(prompt) > PASTED_CONTENT_CHARS


def similarity(distance: float | None, space: str | None) -> float | None:
    """Convert a Chroma distance to a similarity in 0..1.

    Only cosine is convertible to the 0.95-style cutoff the cache thresholds
    on. Anything else returns None, which callers treat as "cannot serve a hit"
    rather than guessing.
    """
    if distance is None:
        return None
    if space == "cosine":
        return round(1.0 - float(distance), 6)
    return None


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split on character count with overlap.

    Overlap keeps a sentence that straddles a boundary retrievable from either
    chunk. Paragraph boundaries are preferred when one falls near the end of a
    chunk, so chunks tend to break between ideas rather than mid-sentence.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    step = max(1, size - max(0, overlap))
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer a paragraph, then a sentence, break in the last quarter.
            window = text[start + (size * 3 // 4) : end]
            for marker in ("\n\n", "\n", ". "):
                cut = window.rfind(marker)
                if cut != -1:
                    end = start + (size * 3 // 4) + cut + len(marker)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + step, end - max(0, overlap))
    return chunks


def content_id(project: str, text: str) -> str:
    """Stable id for a chunk, so re-ingesting the same content replaces it."""
    digest = hashlib.sha256(f"{project}\x00{text}".encode()).hexdigest()
    return f"c_{digest[:32]}"


def exchange_id(project: str, model: str, prompt: str) -> str:
    digest = hashlib.sha256(f"{project}\x00{model}\x00{prompt}".encode()).hexdigest()
    return f"x_{digest[:32]}"


_SCOPE_NOISE = re.compile(r"[^a-z0-9]+")


def normalise_project(value: str) -> str:
    """Canonical cache scope for a project name (BB-202).

    Scopes are matched with Chroma `$eq`, so every spelling of a project name is
    a separate, mutually invisible cache. That is what made the semantic cache
    unable to serve a single hit: the client sends the git root's basename
    (``Brown-Bear``), and documents had been stored under ``brownbear`` — three
    of the fifteen scopes in that corpus differed from another only in case or
    punctuation.

    Case and separators are therefore dropped entirely rather than collapsed to a
    single dash: collapsing gives ``brown-bear``, which still does not match
    ``brownbear``, and matching those is the whole point.

      Brown-Bear · brownbear · brown_bear · "Brown Bear" -> brownbear

    Two genuinely different repositories named ``my-app`` and ``myapp`` do
    collapse together. That is the accepted cost: an over-merge inside one user's
    machine is recoverable and visible, whereas the fragmentation it replaces
    silently disabled the feature the stack exists for.
    """
    slug = _SCOPE_NOISE.sub("", value.strip().lower())
    return slug or "default"


def normalise_model(value: str) -> str:
    """Canonical scope for a model id.

    Only case and surrounding whitespace, deliberately: model ids carry meaningful
    punctuation (``smollm2:135m``, ``claude-opus-5``) and stripping it would both
    mangle them for display and merge models that are genuinely different.
    """
    return value.strip().lower() or "unknown"


def _scope_filter(project: str, model: str | None = None) -> dict[str, Any]:
    """Chroma `where` restricting a lookup to one project (and model).

    An answer about one repository must never be served for another, and a
    model's answer is not automatically valid for a different model.

    Callers pass already-normalised values (see `normalise_project`); this does
    not normalise, so that a caller which forgets to fails visibly in a test
    rather than silently widening the scope.
    """
    clauses: list[dict[str, Any]] = [{"project": {"$eq": project}}]
    if model:
        clauses.append({"model": {"$eq": model}})
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _tunable(key: str, config_attr: str) -> float:
    """A runtime-editable setting, falling back to its configured default.

    The overrides live in PostgreSQL, but a cache lookup needs only Chroma and
    Ollama. Losing the database should degrade the gateway to its defaults
    rather than stop it answering — spec 005 requires that Brown Bear being
    unwell degrades context instead of blocking the client's work.
    """
    try:
        return float(settings_store.value_of(key))
    except Exception:  # noqa: BLE001
        fallback = float(getattr(get_settings(), config_attr))
        logger.warning(
            "settings store unavailable for %s; using configured default %s", key, fallback
        )
        return fallback


def threshold() -> float:
    return _tunable("cache_similarity_threshold", "cache_similarity_threshold")


def top_k() -> int:
    return int(_tunable("context_top_k", "context_top_k"))


def ttl_days() -> int:
    return int(_tunable("cache_ttl_days", "cache_ttl_days"))


@dataclass
class Collections:
    conversations: str
    knowledge: str
    conversations_space: str | None
    knowledge_space: str | None


async def ensure_collections() -> Collections:
    """Create both collections if absent, recording their embedding model.

    Dimension and model are recorded because changing the embedding model
    invalidates every vector in a collection — that is spec 004's ReEmbedder,
    and it needs to know what a collection was built with.
    """
    settings = get_settings()
    probe = await ollama.embed_one("dimension probe")
    meta = {"embedding_model": settings.embedding_model, "dimension": len(probe)}

    conversations = await chroma.ensure_collection(
        settings.conversations_collection, metadata={**meta, "role": "cache"}
    )
    knowledge = await chroma.ensure_collection(
        settings.knowledge_collection, metadata={**meta, "role": "retrieval"}
    )
    return Collections(
        conversations=str(conversations.get("id")),
        knowledge=str(knowledge.get("id")),
        conversations_space=chroma.collection_space(conversations),
        knowledge_space=chroma.collection_space(knowledge),
    )


def _log_query_sync(collection: str, text: str, latency_ms: float, results: int) -> None:
    with session_scope() as session:
        session.add(
            QueryLog(
                collection=collection,
                query_text=text[:4000],
                latency_ms=round(latency_ms, 3),
                result_count=results,
            )
        )


async def log_query(collection: str, text: str, latency_ms: float, results: int) -> None:
    """Record a query. Best-effort: logging must not fail a lookup.

    This is the table spec 004's access-based pruning reads, and it has been
    empty since spec 001 because nothing queried through the app until now.
    """
    try:
        await anyio.to_thread.run_sync(
            lambda: _log_query_sync(collection, text, latency_ms, results)
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to log query for collection=%s", collection)


def _is_expired(metadata: dict[str, Any], now: datetime) -> bool:
    raw = metadata.get("stale_after")
    if not raw:
        return False
    try:
        return datetime.fromisoformat(str(raw)) <= now
    except ValueError:
        # An unparseable stamp is treated as expired: refusing to serve is the
        # safe direction for a cache.
        return True


async def lookup_cache(
    collections: Collections,
    *,
    prompt: str,
    embedding: list[float],
    project: str,
    model: str,
) -> dict[str, Any]:
    """Check the conversations collection for a servable prior answer.

    Returns the decision and always the best score and matched prompt, so the
    client can reject a hit it does not like and a human can see why something
    matched.
    """
    started = datetime.now(UTC)
    hits = await chroma.query(
        collections.conversations,
        embedding=embedding,
        n_results=3,
        where=_scope_filter(project, model),
    )
    elapsed = (datetime.now(UTC) - started).total_seconds() * 1000
    await log_query(get_settings().conversations_collection, prompt, elapsed, len(hits))

    cutoff = threshold()
    now = datetime.now(UTC)
    best: dict[str, Any] | None = None

    for hit in hits:
        meta = hit.get("metadata") or {}
        score = similarity(hit.get("distance"), collections.conversations_space)
        if score is None:
            continue
        candidate = {
            "score": score,
            "matched_prompt": meta.get("prompt"),
            "answer": hit.get("document"),
            "cacheable": bool(meta.get("cacheable", True)),
            "expired": _is_expired(meta, now),
            "created_at": meta.get("created_at"),
        }
        if best is None or score > best["score"]:
            best = candidate

    if best is None:
        return {"hit": False, "score": None, "matched_prompt": None, "reason": "no candidates"}

    if best["score"] < cutoff:
        if best["score"] >= cutoff - NEAR_MISS_MARGIN:
            logger.info(
                "cache near-miss: score=%.4f cutoff=%.4f project=%s model=%s prompt=%r",
                best["score"], cutoff, project, model, prompt[:120],
            )
        return {
            "hit": False,
            "score": best["score"],
            "matched_prompt": best["matched_prompt"],
            "reason": "below threshold",
            "near_miss": best["score"] >= cutoff - NEAR_MISS_MARGIN,
        }

    # Above threshold, but the entry itself may be unservable.
    if not best["cacheable"]:
        return {
            "hit": False,
            "score": best["score"],
            "matched_prompt": best["matched_prompt"],
            "reason": "entry flagged non-cacheable",
        }
    if best["expired"]:
        return {
            "hit": False,
            "score": best["score"],
            "matched_prompt": best["matched_prompt"],
            "reason": "entry expired",
        }

    return {
        "hit": True,
        "score": best["score"],
        "matched_prompt": best["matched_prompt"],
        "answer": best["answer"],
        "created_at": best["created_at"],
    }


async def retrieve(
    collections: Collections,
    *,
    prompt: str,
    embedding: list[float],
    project: str | None,
    k: int,
) -> list[dict[str, Any]]:
    """Top-k knowledge chunks with source attribution."""
    started = datetime.now(UTC)
    hits = await chroma.query(
        collections.knowledge,
        embedding=embedding,
        n_results=k,
        where=_scope_filter(project) if project else None,
    )
    elapsed = (datetime.now(UTC) - started).total_seconds() * 1000
    await log_query(get_settings().knowledge_collection, prompt, elapsed, len(hits))

    chunks = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        chunks.append(
            {
                "text": hit.get("document"),
                "score": similarity(hit.get("distance"), collections.knowledge_space),
                "source": meta.get("source"),
                "project": meta.get("project"),
                "chunk_index": meta.get("chunk_index"),
            }
        )
    return chunks


async def ingest(
    collections: Collections,
    *,
    text: str,
    source: str,
    project: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chunk, embed and store a document in the knowledge collection."""
    settings = get_settings()
    chunks = chunk_text(text, settings.chunk_chars, settings.chunk_overlap_chars)
    if not chunks:
        return {"chunks_stored": 0, "ids": [], "source": source}

    vectors = await ollama.embed(chunks)
    now = datetime.now(UTC).isoformat()
    extra = metadata or {}

    ids = [content_id(project, chunk) for chunk in chunks]
    metadatas = [
        {
            **extra,
            "project": project,
            "source": source,
            "chunk_index": index,
            "chunk_count": len(chunks),
            "created_at": now,
            "embedding_model": settings.embedding_model,
        }
        for index in range(len(chunks))
    ]

    await chroma.upsert(
        collections.knowledge,
        ids=ids,
        embeddings=vectors,
        documents=chunks,
        metadatas=metadatas,
    )
    return {"chunks_stored": len(chunks), "ids": ids, "source": source}


async def store_exchange(
    collections: Collections,
    *,
    prompt: str,
    response: str,
    project: str,
    model: str,
    stale_after: str | None = None,
) -> dict[str, Any]:
    """Store a prompt/answer pair in the conversations collection.

    The *prompt* is embedded, not the answer: a later lookup matches on what was
    asked. The answer rides along as the stored document.
    """
    settings = get_settings()
    # Cached (BB-201), and this is the highest-value hit in the system: the client
    # calls /ext/context and then /ext/exchange with the *same* prompt, so the
    # vector this needs was computed moments ago by the lookup.
    embedding = await embeddings.embed_one(prompt)
    now = datetime.now(UTC)
    cacheable = not is_volatile(prompt)

    expiry = stale_after
    if expiry is None and ttl_days() > 0:
        expiry = (now + timedelta(days=ttl_days())).isoformat()

    identifier = exchange_id(project, model, prompt)
    await chroma.upsert(
        collections.conversations,
        ids=[identifier],
        embeddings=[embedding],
        documents=[response],
        metadatas=[
            {
                "prompt": prompt[:4000],
                "project": project,
                "model": model,
                "created_at": now.isoformat(),
                "cacheable": cacheable,
                "embedding_model": settings.embedding_model,
                **({"stale_after": expiry} if expiry else {}),
            }
        ],
    )
    return {"id": identifier, "cacheable": cacheable, "stale_after": expiry}
