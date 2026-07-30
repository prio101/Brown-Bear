"""Connectors to the four backing services.

Every call to Ollama, ChromaDB, Redis and PostgreSQL goes through this package.
That indirection is the mitigation for the roadmap's top cross-cutting risk:
ChromaDB already dropped /api/v1 (it returns 410), and when v2 goes the same
way the fix stays confined to one module instead of three specs' worth of
call sites.
"""

import httpx

from brownbear.config import get_settings
from brownbear.connectors.base import ServiceHealth

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Process-wide async HTTP client, shared so connections are pooled."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        settings = get_settings()
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ollama_timeout_seconds, connect=10.0),
            follow_redirects=False,
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


__all__ = ["ServiceHealth", "close_http_client", "get_http_client"]
