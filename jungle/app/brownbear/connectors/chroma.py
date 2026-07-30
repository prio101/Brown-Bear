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
