"""Settings endpoints (spec 001 §1.6)."""

import logging
from typing import Annotated, Any

import anyio.to_thread
from fastapi import APIRouter, Body, HTTPException

from brownbear import settings_store
from brownbear.scheduler import apply_collection_intervals

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def read_settings() -> dict[str, Any]:
    values = await anyio.to_thread.run_sync(settings_store.effective)
    return {"settings": list(values.values())}


@router.put("")
async def write_settings(values: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    """Apply setting overrides.

    The batch is validated as a whole before anything is written, so a bad
    value in one field cannot leave the others half-applied.
    """
    try:
        applied = await anyio.to_thread.run_sync(lambda: settings_store.update(values))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Interval changes take effect now; alert thresholds are stored for the
    # alerting work to consume and change nothing on their own.
    rescheduled = apply_collection_intervals()

    effective = await anyio.to_thread.run_sync(settings_store.effective)
    return {
        "applied": applied,
        "rescheduled": rescheduled,
        "settings": list(effective.values()),
    }
