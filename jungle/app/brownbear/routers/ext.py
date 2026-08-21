"""External context gateway (spec 005 §5.3–5.5).

The only surface published through the Cloudflare tunnel besides the liveness
probe. A client asks for context before it calls its own model, then reports
back what the exchange cost.

Brown Bear never calls Anthropic here: the API key stays on the client, and
this service being down should degrade context rather than block work — so
every endpoint fails loudly and quickly instead of hanging.
"""

import logging
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from brownbear import embeddings, gateway, pricing, savings
from brownbear.config import get_settings
from brownbear.connectors import ollama
from brownbear.models.tokens import TokenSource
from brownbear.tracking import record_token_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ext", tags=["gateway"])

# Bounded so a single request cannot ask the embedder to chew through a book.
MAX_DOCUMENT_CHARS = 1_000_000
MAX_PROMPT_CHARS = 32_000


class _Scoped(BaseModel):
    """Requests that carry a cache scope (BB-202).

    Normalising at the boundary, once, rather than at each use: the scope key
    reaches the Chroma `where` filter, the content/exchange id hashes and the
    stored metadata, and those must agree or a document is stored under a key no
    lookup will ever produce. This is the single place that decides the canonical
    form.
    """

    @field_validator("project", check_fields=False)
    @classmethod
    def _canonical_project(cls, value: str) -> str:
        return gateway.normalise_project(value)

    @field_validator("model", check_fields=False)
    @classmethod
    def _canonical_model(cls, value: str) -> str:
        return gateway.normalise_model(value)


class DocumentIn(_Scoped):
    text: Annotated[str, Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)]
    source: Annotated[str, Field(min_length=1, max_length=512)]
    project: Annotated[str, Field(min_length=1, max_length=128)] = "default"
    metadata: dict[str, Any] | None = None


class ContextIn(_Scoped):
    prompt: Annotated[str, Field(min_length=1, max_length=MAX_PROMPT_CHARS)]
    project: Annotated[str, Field(min_length=1, max_length=128)] = "default"
    model: Annotated[str, Field(min_length=1, max_length=128)] = "unknown"
    # Overrides the stored default for this one call; the client may want looser
    # retrieval without loosening the cache for everyone.
    k: Annotated[int | None, Field(ge=1, le=50)] = None
    skip_cache: bool = False
    # What the client will DO with a hit. Only it knows, and the saving is real in
    # one mode and exactly zero in the other: `block` serves the cached answer in
    # place of a model call, `inject` adds it as context and the model still runs.
    cache_mode: Annotated[str, Field(pattern="^(inject|block)$")] = "inject"


class ExchangeIn(_Scoped):
    prompt: Annotated[str, Field(min_length=1, max_length=MAX_PROMPT_CHARS)]
    response: Annotated[str, Field(min_length=1)]
    project: Annotated[str, Field(min_length=1, max_length=128)] = "default"
    model: Annotated[str, Field(min_length=1, max_length=128)] = "unknown"
    tokens_in: Annotated[int, Field(ge=0)] = 0
    tokens_out: Annotated[int, Field(ge=0)] = 0
    # The input breakdown. Providers bill these three at different rates — fresh at
    # par, cache writes above it, cache reads at a fraction — so summing them into
    # tokens_in and pricing at one rate overstates a cache-heavy session badly.
    # Optional: a client that sends none gets the old flat pricing, recorded as
    # such rather than silently mixed in with correctly-priced rows.
    tokens_in_fresh: Annotated[int | None, Field(ge=0)] = None
    tokens_cache_write: Annotated[int | None, Field(ge=0)] = None
    tokens_cache_read: Annotated[int | None, Field(ge=0)] = None
    # Dedup key: replaying the same exchange must not double-count usage.
    request_id: str | None = Field(default=None, max_length=128)
    # A client billed by its own provider knows the real cost; the local
    # pricing table may only have the `*` fallback, which prices it at zero.
    cost_usd: Decimal | None = None
    stale_after: str | None = None
    store: bool = True
    #: Who ran it — a hostname, sent by the client hook (spec 012). Optional, and
    #: unverifiable: the edge authenticates one shared secret for every machine, so
    #: this is the same kind of claim as a file's `extracted_by`. A client that
    #: sends nothing leaves the exchange attributed to nobody rather than to the
    #: server that received it.
    machine: Annotated[str | None, Field(max_length=128)] = None


async def _collections() -> gateway.Collections:
    try:
        return await gateway.ensure_collections()
    except Exception as exc:  # noqa: BLE001
        # Embeddings are the usual cause: Ollama answers 501 when the model has
        # no embedding support. Say so rather than surfacing a bare 500.
        logger.exception("gateway collections unavailable")
        raise HTTPException(
            status_code=503,
            detail=(
                "context gateway unavailable: could not prepare collections "
                f"({type(exc).__name__}). Check that the embedding model "
                f"'{get_settings().embedding_model}' is pulled and /api/embed answers."
            ),
        ) from exc


@router.get("/health")
async def health() -> dict[str, Any]:
    """Gateway readiness: embeddings reachable and both collections present."""
    settings = get_settings()
    detail: dict[str, Any] = {
        "embedding_model": settings.embedding_model,
        "threshold": gateway.threshold(),
        "top_k": gateway.top_k(),
        "ttl_days": gateway.ttl_days(),
    }
    try:
        collections = await gateway.ensure_collections()
    except Exception as exc:  # noqa: BLE001
        return {"ready": False, "error": f"{type(exc).__name__}: {exc}", **detail}

    return {
        "ready": True,
        "collections": {
            settings.conversations_collection: {
                "id": collections.conversations,
                "space": collections.conversations_space,
            },
            settings.knowledge_collection: {
                "id": collections.knowledge,
                "space": collections.knowledge_space,
            },
        },
        **detail,
    }


@router.post("/documents")
async def add_document(payload: DocumentIn) -> dict[str, Any]:
    """Ingest text into the knowledge collection.

    Idempotent by content: a chunk's id is a hash of its text and project, so
    re-ingesting an unchanged document replaces rather than duplicates it.
    """
    collections = await _collections()
    try:
        result = await gateway.ingest(
            collections,
            text=payload.text,
            source=payload.source,
            project=payload.project,
            metadata=payload.metadata,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest failed for source=%s", payload.source)
        raise HTTPException(status_code=502, detail=f"ingest failed: {type(exc).__name__}") from exc

    return {"stored": True, "project": payload.project, **result}


@router.post("/context")
async def context(payload: ContextIn) -> dict[str, Any]:
    """Cache-check and retrieve in one call.

    Always returns ``score`` and ``matched_prompt`` — the client can reject a
    hit it does not like, and a human can see why something matched.
    """
    collections = await _collections()

    try:
        # Cached (BB-201): the same prompt in a coding loop should not re-run the
        # embedding model. A cache miss or an unreachable Redis falls through to
        # Ollama transparently.
        embedding = await embeddings.embed_one(payload.prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("embedding failed")
        raise HTTPException(
            status_code=502, detail=f"embedding failed: {type(exc).__name__}"
        ) from exc

    cache: dict[str, Any] = {"hit": False, "reason": "skipped"}
    if not payload.skip_cache:
        cache = await gateway.lookup_cache(
            collections,
            prompt=payload.prompt,
            embedding=embedding,
            project=payload.project,
            model=payload.model,
        )

    if cache.get("hit"):
        # Best-effort and awaited: it is a single insert, and losing the record of
        # what the memory served would make the savings report quietly incomplete.
        await savings.record_context_event(
            project=payload.project,
            model=payload.model,
            hit=True,
            cache_mode=payload.cache_mode,
            score=cache.get("score"),
            answer=cache.get("answer"),
            chunks=[],
        )
        # A hit is the whole answer; retrieval would be wasted work.
        return {
            "hit": True,
            "answer": cache.get("answer"),
            "score": cache.get("score"),
            "matched_prompt": cache.get("matched_prompt"),
            "created_at": cache.get("created_at"),
            "threshold": gateway.threshold(),
            "chunks": [],
        }

    chunks = await gateway.retrieve(
        collections,
        prompt=payload.prompt,
        embedding=embedding,
        project=payload.project,
        k=payload.k or gateway.top_k(),
    )
    await savings.record_context_event(
        project=payload.project,
        model=payload.model,
        hit=False,
        cache_mode=payload.cache_mode,
        score=cache.get("score"),
        answer=None,
        chunks=chunks,
    )
    return {
        "hit": False,
        "reason": cache.get("reason"),
        "score": cache.get("score"),
        "matched_prompt": cache.get("matched_prompt"),
        "near_miss": cache.get("near_miss", False),
        "threshold": gateway.threshold(),
        "chunks": chunks,
    }


@router.post("/exchange")
async def exchange(payload: ExchangeIn) -> dict[str, Any]:
    """Store a completed exchange and record its usage (spec 003 M8).

    Storing and metering happen in one call because the client is the only
    party that saw the response.
    """
    collections = await _collections()

    stored: dict[str, Any] | None = None
    if payload.store:
        try:
            stored = await gateway.store_exchange(
                collections,
                prompt=payload.prompt,
                response=payload.response,
                project=payload.project,
                model=payload.model,
                stale_after=payload.stale_after,
                machine=payload.machine,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to store exchange")
            raise HTTPException(
                status_code=502, detail=f"store failed: {type(exc).__name__}"
            ) from exc

    warnings: list[str] = []
    event_id: int | None = None
    if payload.tokens_in or payload.tokens_out:
        priced = payload.cost_usd is not None or pricing.has_explicit_price(payload.model)
        if not priced:
            # The `*` fallback would record this as free. Tokens are still worth
            # recording, but the zero must not read as a fact.
            warnings.append(
                f"no pricing row for '{payload.model}' and no cost_usd supplied; "
                "cost recorded as 0 and should not be trusted"
            )
        event_id = await record_token_event(
            model=payload.model,
            tokens_in=payload.tokens_in,
            tokens_out=payload.tokens_out,
            tokens_in_fresh=payload.tokens_in_fresh,
            tokens_cache_write=payload.tokens_cache_write,
            tokens_cache_read=payload.tokens_cache_read,
            source=TokenSource.remote_api,
            endpoint="/ext/exchange",
            request_id=payload.request_id,
            cost_usd=payload.cost_usd,
        )
        if event_id is None and payload.request_id:
            warnings.append(f"duplicate request_id '{payload.request_id}'; usage not counted twice")

    # Backdated reporting is not re-aggregated yet: catch-up walks its cursor
    # forward, so an event older than the newest completed run gets no bucket.
    # Usage reported now is current, so this is latent rather than active.
    return {
        "stored": stored is not None,
        "cached_entry": stored,
        "token_event_id": event_id,
        "warnings": warnings,
    }
