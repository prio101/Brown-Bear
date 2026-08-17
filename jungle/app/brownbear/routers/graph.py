"""The memory graph API (BB-301).

Two endpoints, split along the line that matters for cost: the overview is
structural and cheap, expansion is where similarity is computed and where the
vector queries happen. A single endpoint returning everything would make opening
the page as expensive as exploring all of it.

`id` is a query parameter rather than a path segment because node ids carry both
a type prefix and a value that may contain `/` and `:` — `source:brownbear/docs/
DESIGN-BOOK.md` in a path segment would need escaping the client would get wrong.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from brownbear import graph

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
async def overview() -> dict[str, Any]:
    """Every stored memory as a structural graph.

    Structural edges only. `truncated` is true when the node cap or the per-
    collection page size was reached — reported rather than silently applied, so a
    partial graph never reads as a complete one.
    """
    try:
        return await graph.build_overview()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"could not read the memory graph: {type(exc).__name__}",
        ) from exc


@router.get("/node")
async def node(
    id: str = Query(min_length=3, max_length=512, description="Typed node id, e.g. exchange:x_ab12"),
    min_similarity: float = Query(
        graph.SIMILARITY_EDGE_MIN,
        ge=0.0,
        le=1.0,
        description="Floor for drawing a similar_to edge. Corpus- and model-dependent.",
    ),
) -> dict[str, Any]:
    """One node, its structural neighbours, and — for a memory — its nearest others.

    A node with no neighbours returns itself with empty edges rather than 404: an
    isolated memory is a real state worth seeing, and one of the more interesting
    ones, because it means nothing in the corpus resembles it.

    `min_similarity` is a parameter rather than a fixed constant because the right
    value depends on the embedding model and the corpus. Every returned edge carries
    its weight, so a caller can filter harder without another round trip.
    """
    kind, _, value = id.partition(":")
    if kind not in {"collection", "project", "model", "source", "exchange", "chunk"} or not value:
        raise HTTPException(status_code=422, detail=f"not a node id: {id!r}")

    try:
        result = await graph.expand(id, min_similarity=min_similarity)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"could not expand {id}: {type(exc).__name__}",
        ) from exc

    if result.get("node") is None and not result.get("nodes"):
        raise HTTPException(status_code=404, detail=f"no such node: {id}")
    return result
