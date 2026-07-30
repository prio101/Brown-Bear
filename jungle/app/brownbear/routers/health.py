"""System health (spec 001 §1.5).

Two endpoints on purpose:
  /api/health/live  — is *this* app up? Used by container orchestration.
  /api/health       — are the backing services up? Always 200; the payload
                      carries the verdict, so a degraded Redis never makes
                      the app itself look dead and get restarted.
"""

import asyncio

from fastapi import APIRouter

from brownbear.connectors import chroma, ollama, postgres, redis_conn

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health/live")
async def live() -> dict:
    return {"status": "ok"}


@router.get("/health")
async def health() -> dict:
    results = await asyncio.gather(
        ollama.check(),
        chroma.check(),
        redis_conn.check(),
        postgres.check(),
    )
    return {
        "healthy": all(r.healthy for r in results),
        "services": {r.name: r.as_dict() for r in results},
    }
