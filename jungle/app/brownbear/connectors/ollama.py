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


async def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed texts, batched.

    Ollama answers /api/embed with 501 when the named model's runner has no
    embedding support — a chat model produces that, not a broken server, so the
    default here is an embedding model. Batches are chunked because Ollama
    embeds the whole request at once and a large one spikes memory.
    """
    if not texts:
        return []

    settings = get_settings()
    name = model or settings.embedding_model
    size = max(1, settings.embedding_batch_size)
    vectors: list[list[float]] = []

    for start in range(0, len(texts), size):
        batch = texts[start : start + size]
        resp = await get_http_client().post(
            f"{settings.ollama_url}/api/embed",
            json={"model": name, "input": batch},
            timeout=settings.embedding_timeout_seconds,
        )
        resp.raise_for_status()
        returned = resp.json().get("embeddings") or []
        if len(returned) != len(batch):
            raise RuntimeError(
                f"ollama returned {len(returned)} embeddings for {len(batch)} inputs"
            )
        vectors.extend(returned)

    return vectors


async def embed_one(text: str, model: str | None = None) -> list[float]:
    return (await embed([text], model=model))[0]


async def check() -> ServiceHealth:
    async def probe() -> dict[str, Any]:
        models = await list_models()
        return {
            "model_count": len(models),
            "models": [m.get("name") for m in models],
        }

    return await timed_check("ollama", probe)
