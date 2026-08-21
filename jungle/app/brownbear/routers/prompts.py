"""Prompt Palace API (spec 012).

Three endpoints, split along the line that decides cost. The listing is metadata
only and touches no vectors; expanding one prompt is where the similarity queries
happen, one per collection. A single endpoint returning everything would make
opening the page as expensive as reading all of it — the same split `/api/graph`
makes, for the same reason.

`/api/*` rather than `/ext/*`: this is a dashboard read, not a client-facing
gateway route. It is published through the edge for the browser's sake — the page's
list is server-rendered, but selecting a prompt fetches its answer and its
neighbours from the browser, and the browser can only reach the origin.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query

from brownbear import prompts

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

#: Exchange ids are `x_<32 hex>` (gateway.exchange_id). Pinned in the path so a
#: malformed id is a 422 here rather than an unexpected miss from Chroma.
ID_PATTERN = r"^x_[0-9a-f]{8,64}$"


@router.get("")
async def index(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project: str | None = None,
    model: str | None = None,
    machine: str | None = Query(
        None,
        description="Hostname a client claimed, or 'unattributed' for prompts with none.",
    ),
) -> dict[str, Any]:
    """Stored prompts, newest first among those scanned.

    `total`, `scanned` and `matched` are separate numbers on purpose: Chroma
    returns documents in no particular order, so "newest" is only ever newest
    within what was read, and `truncated` says when that distinction is live.
    """
    try:
        return await prompts.listing(
            limit=limit, offset=offset, project=project, model=model, machine=machine
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"could not read stored prompts: {type(exc).__name__}",
        ) from exc


@router.get("/{exchange_id}")
async def detail(exchange_id: str = Path(pattern=ID_PATTERN)) -> dict[str, Any]:
    """One exchange with the whole answer, which the listing omits."""
    try:
        found = await prompts.detail(exchange_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503, detail=f"could not read {exchange_id}: {type(exc).__name__}"
        ) from exc
    if found is None:
        raise HTTPException(status_code=404, detail=f"no such exchange: {exchange_id}")
    return found


@router.get("/{exchange_id}/related")
async def related(
    exchange_id: str = Path(pattern=ID_PATTERN),
    min_similarity: float = Query(
        prompts.RELATED_MIN,
        ge=0.0,
        le=1.0,
        description="Floor for calling two memories related. Corpus- and model-dependent.",
    ),
    limit: int = Query(prompts.RELATED_LIMIT, ge=1, le=25),
) -> dict[str, Any]:
    """Nearest prior prompts and nearest knowledge chunks, scored.

    Kept as two lists rather than one ranked set: a neighbouring prompt is an
    answer the cache might have served, a neighbouring chunk is context that would
    have been injected, and merging them invites reading a retrieved passage as an
    answer.
    """
    try:
        found = await prompts.related(exchange_id, min_similarity=min_similarity, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"could not expand {exchange_id}: {type(exc).__name__}",
        ) from exc
    if found is None:
        raise HTTPException(status_code=404, detail=f"no such exchange: {exchange_id}")
    return found
