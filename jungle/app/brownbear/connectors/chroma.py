"""ChromaDB connector (spec 001 §1.3).

The specs were written against /api/v1. That version now returns 410 Gone on
chromadb/chroma:latest, so the version lives in settings and every path is
built here. Pin the image tag; treat a version bump as a change to this file.
"""

from typing import Any

from brownbear.config import get_settings
from brownbear.connectors import get_http_client
from brownbear.connectors.base import ServiceHealth, timed_check

# v2 scopes collections under a tenant and database.
DEFAULT_TENANT = "default_tenant"
DEFAULT_DATABASE = "default_database"


def _base() -> str:
    settings = get_settings()
    return f"{settings.chroma_url}/api/{settings.chroma_api_version}"


def collections_path() -> str:
    settings = get_settings()
    if settings.chroma_api_version == "v1":
        return f"{_base()}/collections"
    return f"{_base()}/tenants/{DEFAULT_TENANT}/databases/{DEFAULT_DATABASE}/collections"


async def heartbeat() -> dict[str, Any]:
    settings = get_settings()
    resp = await get_http_client().get(
        f"{_base()}/heartbeat", timeout=settings.health_timeout_seconds
    )
    resp.raise_for_status()
    return resp.json()


async def version() -> str:
    settings = get_settings()
    resp = await get_http_client().get(
        f"{_base()}/version", timeout=settings.health_timeout_seconds
    )
    resp.raise_for_status()
    return resp.text.strip('"\n ')


async def list_collections() -> list[dict[str, Any]]:
    settings = get_settings()
    resp = await get_http_client().get(
        collections_path(), timeout=settings.health_timeout_seconds
    )
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, list) else payload.get("collections", [])


async def collection_count(collection_id: str) -> int:
    """Document count for one collection."""
    settings = get_settings()
    resp = await get_http_client().get(
        f"{collections_path()}/{collection_id}/count",
        timeout=settings.health_timeout_seconds,
    )
    resp.raise_for_status()
    return int(resp.text.strip('"\n '))


async def collections_with_counts() -> list[dict[str, Any]]:
    """Collections plus their document counts (spec 001 §1.5).

    A failed count leaves that collection listed with ``count: None`` rather
    than failing the whole listing — one bad collection should not blank the
    page.
    """
    collections = await list_collections()
    results: list[dict[str, Any]] = []
    for collection in collections:
        identifier = collection.get("id") or collection.get("name")
        entry = {
            "id": collection.get("id"),
            "name": collection.get("name"),
            "metadata": collection.get("metadata"),
            "dimension": collection.get("dimension"),
            "count": None,
            "error": None,
        }
        try:
            entry["count"] = await collection_count(str(identifier))
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)
    return results


async def get_collection(name: str) -> dict[str, Any] | None:
    """One collection by name, or None if it does not exist."""
    settings = get_settings()
    resp = await get_http_client().get(
        f"{collections_path()}/{name}", timeout=settings.health_timeout_seconds
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


async def ensure_collection(
    name: str,
    *,
    space: str = "cosine",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get or create a collection.

    Space defaults to cosine because the semantic cache thresholds on cosine
    similarity; the Chroma default is l2, whose distances are not comparable to
    a 0.95 cutoff. Space is fixed at creation — an existing collection is
    returned as-is rather than silently reinterpreted.
    """
    existing = await get_collection(name)
    if existing is not None:
        return existing

    body: dict[str, Any] = {
        "name": name,
        "get_or_create": True,
        "configuration": {"hnsw": {"space": space}},
    }
    if metadata:
        body["metadata"] = metadata

    settings = get_settings()
    resp = await get_http_client().post(
        collections_path(), json=body, timeout=settings.health_timeout_seconds
    )
    resp.raise_for_status()
    return resp.json()


def collection_space(collection: dict[str, Any]) -> str | None:
    """The distance function a collection was built with."""
    config = collection.get("configuration_json") or {}
    return (config.get("hnsw") or {}).get("space")


async def upsert(
    collection_id: str,
    *,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict[str, Any]],
) -> None:
    """Insert or replace documents. Upsert, so re-ingesting the same id is idempotent."""
    if not ids:
        return
    settings = get_settings()
    resp = await get_http_client().post(
        f"{collections_path()}/{collection_id}/upsert",
        json={
            "ids": ids,
            "embeddings": embeddings,
            "documents": documents,
            "metadatas": metadatas,
        },
        timeout=settings.embedding_timeout_seconds,
    )
    resp.raise_for_status()


async def get_documents(
    collection_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    where: dict[str, Any] | None = None,
    ids: list[str] | None = None,
    with_embeddings: bool = False,
) -> list[dict[str, Any]]:
    """Documents by id or filter, without a query vector.

    `query` finds what is *near* something; this enumerates what is *there*, which
    is what building a graph of stored memory needs — you cannot draw the nodes by
    repeatedly asking for neighbours of a point you do not have yet.

    Embeddings are excluded by default and cost real bandwidth when included: 768
    floats per document. Only the similarity step asks for them, and only for the
    one node it is expanding.
    """
    body: dict[str, Any] = {
        "limit": max(1, limit),
        "offset": max(0, offset),
        "include": ["documents", "metadatas"] + (["embeddings"] if with_embeddings else []),
    }
    if where:
        body["where"] = where
    if ids:
        body["ids"] = ids

    settings = get_settings()
    resp = await get_http_client().post(
        f"{collections_path()}/{collection_id}/get",
        json=body,
        timeout=settings.embedding_timeout_seconds,
    )
    resp.raise_for_status()
    payload = resp.json()

    # `get` returns flat lists, unlike `query`, which nests one level per query
    # vector. Handling both shapes in one helper would hide that difference.
    doc_ids = payload.get("ids") or []
    docs = payload.get("documents") or []
    metas = payload.get("metadatas") or []
    vectors = payload.get("embeddings") or []

    return [
        {
            "id": doc_ids[i],
            "document": docs[i] if i < len(docs) else None,
            "metadata": metas[i] if i < len(metas) else {},
            "embedding": vectors[i] if i < len(vectors) else None,
        }
        for i in range(len(doc_ids))
    ]


async def query(
    collection_id: str,
    *,
    embedding: list[float],
    n_results: int = 5,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Nearest documents, flattened into one row per hit.

    Chroma nests results one level per query embedding; this sends a single
    embedding and unwraps that level so callers do not index into [0].
    """
    body: dict[str, Any] = {
        "query_embeddings": [embedding],
        "n_results": max(1, n_results),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        body["where"] = where

    settings = get_settings()
    resp = await get_http_client().post(
        f"{collections_path()}/{collection_id}/query",
        json=body,
        timeout=settings.embedding_timeout_seconds,
    )
    resp.raise_for_status()
    payload = resp.json()

    def first(key: str) -> list[Any]:
        nested = payload.get(key) or []
        return nested[0] if nested and isinstance(nested[0], list) else []

    ids, docs = first("ids"), first("documents")
    metas, distances = first("metadatas"), first("distances")

    return [
        {
            "id": ids[i] if i < len(ids) else None,
            "document": docs[i] if i < len(docs) else None,
            "metadata": metas[i] if i < len(metas) else {},
            "distance": distances[i] if i < len(distances) else None,
        }
        for i in range(len(ids))
    ]


async def delete(collection_id: str, *, where: dict[str, Any]) -> int:
    """Delete documents matching a filter; returns how many were removed.

    Counted first, because Chroma's delete response does not reliably carry the
    removed ids and a caller that reports "removed 0" when it removed 400 is worse
    than one that does not report at all. A `where` is required — an unfiltered
    delete here would empty a collection.
    """
    if not where:
        raise ValueError("delete requires a where clause")

    settings = get_settings()
    doomed = await get_documents(collection_id, limit=10_000, where=where)
    if not doomed:
        return 0

    resp = await get_http_client().post(
        f"{collections_path()}/{collection_id}/delete",
        json={"where": where},
        timeout=settings.embedding_timeout_seconds,
    )
    resp.raise_for_status()
    return len(doomed)


async def check() -> ServiceHealth:
    async def probe() -> dict[str, Any]:
        await heartbeat()
        detail: dict[str, Any] = {"api_version": get_settings().chroma_api_version}
        try:
            detail["version"] = await version()
            detail["collection_count"] = len(await list_collections())
        except Exception as exc:  # noqa: BLE001 - heartbeat passed; extras are best-effort
            detail["detail_error"] = f"{type(exc).__name__}: {exc}"
        return detail

    return await timed_check("chromadb", probe)
