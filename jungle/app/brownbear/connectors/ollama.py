"""Ollama connector (spec 001 §1.3)."""

from typing import Any

from brownbear.config import get_settings
from brownbear.connectors import get_http_client
from brownbear.connectors.base import ServiceHealth, timed_check


async def list_models() -> list[dict[str, Any]]:
    settings = get_settings()
    resp = await get_http_client().get(
        f"{settings.ollama_url}/api/tags", timeout=settings.health_timeout_seconds
    )
    resp.raise_for_status()
    return resp.json().get("models", [])


async def running_models() -> list[dict[str, Any]]:
    """Models currently loaded in memory."""
    settings = get_settings()
    resp = await get_http_client().get(
        f"{settings.ollama_url}/api/ps", timeout=settings.health_timeout_seconds
    )
    resp.raise_for_status()
    return resp.json().get("models", [])


async def check() -> ServiceHealth:
    async def probe() -> dict[str, Any]:
        models = await list_models()
        return {
            "model_count": len(models),
            "models": [m.get("name") for m in models],
        }

    return await timed_check("ollama", probe)
