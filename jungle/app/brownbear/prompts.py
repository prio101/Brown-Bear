"""Prompt Palace: what was asked, what came back, and what it sits near (spec 012).

The other pages answer "how much" and the graph answers "what is connected to
what". Neither answers the question a shared memory is actually for: *what has
been asked of this thing, from wherever, and would the memory have had an answer
already*. That needs three things beside each prompt — the response, the nearest
other prompts with their scores against the cache cutoff, and the nearest
knowledge chunks, which are what a retrieval lookup would have injected.

Everything here is **reported**, not measured. Brown Bear never sees the model
call: a remote client posts the finished exchange to `/ext/exchange`, and the
prompt, the answer and the machine name are all its claims. The edge authenticates
one shared secret for every machine, so `machine` in particular cannot be checked
against anything — it is displayed the way a file's `extracted_by` is displayed,
as something a client said.

Two hard constraints from the data, both of which shape the API:

  Chroma has no ordering. `get` returns documents in an unspecified order, so
  "newest first" can only ever mean "newest among those read". This module scans
  up to MAX_SCAN of them, sorts that, and reports `scanned` beside the collection's
  true `total` so a partial view can never read as the whole corpus.

  A similarity is only meaningful in cosine space. Anything else scores None and
  must render as "cannot be scored" rather than as zero — a 0 would say "unrelated",
  which is a claim nobody has made.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from brownbear import gateway
from brownbear.config import get_settings
from brownbear.connectors import chroma

logger = logging.getLogger(__name__)

#: Documents per Chroma read while scanning the collection.
PAGE_SIZE = 500

#: Hard ceiling on documents scanned for one listing. Metadata only — the answers
#: are not fetched here — so this is cheap enough to be generous, and it is
#: reported rather than silently applied.
MAX_SCAN = 2000

#: Neighbours returned per collection when one prompt is expanded.
RELATED_LIMIT = 6

#: Floor for calling two memories related. Deliberately far below the cache's 0.95:
#: that cutoff decides whether an answer may be *served*, which is a far stronger
#: claim than whether two prompts are worth showing side by side.
#:
#: 0.50 because it was measured here, not inherited. The graph uses 0.60, taken from
#: a corpus of documents; prompts score lower against each other than documents do —
#: on this stack's 140 conversations and 1642 chunks with nomic-embed-text, a
#: prompt's nearest genuine neighbour lands at 0.52–0.56. At 0.60 the panel reported
#: "nothing else in the corpus resembles this" for prompts that had real neighbours
#: at 0.558, which is the same trap BB-301 records for its own floor: a threshold
#: set too high does not look like a threshold, it looks like an empty corpus.
#:
#: Corpus- and model-dependent, so the caller can override it and every row carries
#: its own score.
RELATED_MIN = 0.50

#: How much of an answer or a chunk a list carries. The full text is one request
#: away; forty full answers in a listing is megabytes nobody scrolls through.
PREVIEW_CHARS = 400


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _newest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest first, with undated rows last rather than first.

    Two passes rather than one clever sort key: `reverse=True` over a combined key
    flips the undated group to the *top*, which is the opposite of what a missing
    date should mean. An exchange stored before `created_at` existed goes to the
    bottom without being handed the epoch and made to claim it is the oldest thing
    in the corpus.

    Sorted on the parsed timestamp rather than the string: every `created_at`
    written here is UTC and would sort lexicographically, but a corpus that has
    travelled between machines is not something to bet a sort order on.
    """
    dated: list[tuple[float, str, dict[str, Any]]] = []
    undated: list[dict[str, Any]] = []
    for row in rows:
        created = ((row.get("metadata") or {}).get("created_at")) or ""
        try:
            when = datetime.fromisoformat(str(created))
        except (TypeError, ValueError):
            undated.append(row)
        else:
            # The id is a stable tiebreaker, so two exchanges stored in the same
            # instant do not swap places between requests.
            dated.append((when.timestamp(), str(row.get("id")), row))
    dated.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _when, _id, row in dated] + undated


def _prompt_row(row: dict[str, Any], *, with_response: bool = False) -> dict[str, Any]:
    """One stored exchange, flattened for the API."""
    meta = row.get("metadata") or {}
    document = row.get("document")
    payload: dict[str, Any] = {
        "id": str(row.get("id")),
        # The prompt lives in the metadata; the *answer* is the stored document.
        "prompt": meta.get("prompt") or "",
        "project": meta.get("project"),
        "model": meta.get("model"),
        # None, never "local" or "unknown": nothing here knows where it ran.
        "machine": meta.get("machine"),
        "created_at": meta.get("created_at"),
        # False is why a hit was refused despite a high score, so it travels with
        # the row rather than only appearing in a detail view.
        "cacheable": meta.get("cacheable", True),
        "stale_after": meta.get("stale_after"),
        "embedding_model": meta.get("embedding_model"),
    }
    if with_response:
        payload["response"] = document
        payload["response_chars"] = len(document) if document else 0
    else:
        payload["response_preview"] = _truncate(document, PREVIEW_CHARS)
    return payload


async def _conversations() -> tuple[str | None, str | None]:
    """The conversations collection's id and distance space."""
    settings = get_settings()
    collection = await chroma.get_collection(settings.conversations_collection)
    if not collection:
        return None, None
    return str(collection.get("id")), chroma.collection_space(collection)


async def _scan(collection_id: str) -> tuple[list[dict[str, Any]], bool]:
    """Metadata for up to MAX_SCAN stored exchanges, and whether more remain."""
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < MAX_SCAN:
        page = await chroma.get_documents(
            collection_id,
            limit=min(PAGE_SIZE, MAX_SCAN - offset),
            offset=offset,
            with_documents=False,
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows, False
        offset += len(page)
    return rows, True


async def listing(
    *,
    limit: int = 25,
    offset: int = 0,
    project: str | None = None,
    model: str | None = None,
    machine: str | None = None,
) -> dict[str, Any]:
    """Stored prompts, newest first among those scanned.

    The response deliberately separates three counts that are easy to conflate:
    `total` is what the collection holds, `scanned` is what this read looked at,
    and `matched` is what survived the filters. A page showing 25 of 25 matched out
    of 400 scanned out of 900 stored is telling the truth in a way that a single
    "total" cannot.
    """
    collection_id, space = await _conversations()
    if collection_id is None:
        # A missing collection is not an error here: nothing has been stored yet.
        return {
            "prompts": [],
            "total": 0,
            "scanned": 0,
            "matched": 0,
            "limit": limit,
            "offset": offset,
            "truncated": False,
            "machines": [],
            "projects": [],
            "models": [],
            "threshold": gateway.threshold(),
            "scorable": space == "cosine",
            "collection": get_settings().conversations_collection,
            "ready": False,
        }

    total = await chroma.collection_count(collection_id)
    rows, truncated = await _scan(collection_id)

    prompts = [_prompt_row(row) for row in _newest_first(rows)]

    # Offered as filters, and derived from what was scanned rather than from a
    # separate query — so the list of machines cannot disagree with the rows.
    machines = sorted({p["machine"] for p in prompts if p["machine"]})
    projects = sorted({p["project"] for p in prompts if p["project"]})
    models = sorted({p["model"] for p in prompts if p["model"]})

    if project:
        prompts = [p for p in prompts if p["project"] == project]
    if model:
        prompts = [p for p in prompts if p["model"] == model]
    if machine:
        # "unattributed" is a real selection: it is how you find what predates the
        # machine field, or a client that is not sending it.
        prompts = (
            [p for p in prompts if not p["machine"]]
            if machine == "unattributed"
            else [p for p in prompts if p["machine"] == machine]
        )

    matched = len(prompts)
    return {
        "prompts": prompts[offset : offset + limit],
        "total": total,
        "scanned": len(rows),
        "matched": matched,
        "limit": limit,
        "offset": offset,
        # True means the newest exchange may not be on this page at all, because
        # Chroma returned an arbitrary window and the sort only saw that window.
        "truncated": truncated,
        "machines": machines,
        "projects": projects,
        "models": models,
        "threshold": gateway.threshold(),
        "scorable": space == "cosine",
        "collection": get_settings().conversations_collection,
        "ready": True,
    }


async def detail(exchange_id: str) -> dict[str, Any] | None:
    """One exchange with the whole answer."""
    collection_id, _space = await _conversations()
    if collection_id is None:
        return None
    rows = await chroma.get_documents(collection_id, ids=[exchange_id], limit=1)
    if not rows:
        return None
    return _prompt_row(rows[0], with_response=True)


def _chunk_row(hit: dict[str, Any], score: float | None) -> dict[str, Any]:
    meta = hit.get("metadata") or {}
    return {
        "id": str(hit.get("id")),
        "score": score,
        "source": meta.get("source"),
        "project": meta.get("project"),
        "chunk_index": meta.get("chunk_index"),
        "chunk_count": meta.get("chunk_count"),
        "file_id": meta.get("file_id"),
        "text": _truncate(hit.get("document"), PREVIEW_CHARS),
    }


async def related(
    exchange_id: str,
    *,
    min_similarity: float = RELATED_MIN,
    limit: int = RELATED_LIMIT,
) -> dict[str, Any] | None:
    """What this prompt is near, in both collections.

    The stored vector is reused rather than re-embedded from the prompt text: it is
    the point every other score in the system was computed against, and re-deriving
    it would compare against a subtly different one.

    Two collections, kept apart in the response for the reason spec 005 split them
    in the first place — a neighbouring *prompt* is a prior answer that the cache
    might have served, and a neighbouring *chunk* is supporting context that would
    have been injected. Presenting them as one ranked list invites exactly the
    confusion the split exists to prevent.
    """
    settings = get_settings()
    collection = await chroma.get_collection(settings.conversations_collection)
    if not collection:
        return None
    cid = str(collection.get("id"))
    space = chroma.collection_space(collection)

    rows = await chroma.get_documents(cid, ids=[exchange_id], with_embeddings=True, limit=1)
    if not rows:
        return None
    embedding = rows[0].get("embedding")
    if not embedding:
        # The row exists but carries no vector: report it rather than returning an
        # empty neighbour list, which would read as "nothing is similar".
        return {
            "id": exchange_id,
            "prompts": [],
            "chunks": [],
            "space": space,
            "scorable": False,
            "threshold": gateway.threshold(),
            "min_similarity": min_similarity,
            "unavailable": "this exchange has no stored embedding, so it cannot be compared",
        }

    def scored(hit: dict[str, Any]) -> float | None:
        return gateway.similarity(hit.get("distance"), space)

    def keep(score: float | None) -> bool:
        # An unscoreable neighbour is kept, not dropped: the floor is a comparison
        # and there is nothing here to compare. It renders as "cannot be scored".
        return score is None or score >= min_similarity

    neighbours: list[dict[str, Any]] = []
    try:
        # limit + 1: the nearest hit is always the prompt itself.
        hits = await chroma.query(cid, embedding=embedding, n_results=limit + 1)
        for hit in hits:
            if str(hit.get("id")) == exchange_id:
                continue
            score = scored(hit)
            if not keep(score):
                continue
            row = _prompt_row(hit)
            row["score"] = score
            # Whether this neighbour would have been served as a cache hit, which
            # needs both a score above the cutoff *and* a cacheable entry.
            row["would_hit"] = (
                score is not None and score >= gateway.threshold() and row["cacheable"] is not False
            )
            neighbours.append(row)
    except Exception:  # noqa: BLE001
        # One collection failing must not blank the other half of the panel.
        logger.exception("similar-prompt lookup failed for %s", exchange_id)

    chunks: list[dict[str, Any]] = []
    knowledge = await chroma.get_collection(settings.knowledge_collection)
    if knowledge:
        kid = str(knowledge.get("id"))
        kspace = chroma.collection_space(knowledge)
        try:
            for hit in await chroma.query(kid, embedding=embedding, n_results=limit):
                score = gateway.similarity(hit.get("distance"), kspace)
                if not keep(score):
                    continue
                chunks.append(_chunk_row(hit, score))
        except Exception:  # noqa: BLE001
            logger.exception("knowledge lookup failed for %s", exchange_id)

    return {
        "id": exchange_id,
        "prompts": neighbours,
        "chunks": chunks,
        "space": space,
        "scorable": space == "cosine",
        "threshold": gateway.threshold(),
        "min_similarity": min_similarity,
    }
