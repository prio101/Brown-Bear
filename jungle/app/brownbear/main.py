"""FastAPI entrypoint.

Routers are mounted here as each spec lands:
  /api/health   — F1 (this phase)
  /ollama/*     — M3 token-capturing proxy (this phase)
  /api/tokens   — spec 003 read endpoints
  /api/maintenance — spec 004
  /ext          — spec 002 external gateway
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from brownbear import __version__
from brownbear.config import get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from brownbear.connectors import close_http_client
    from brownbear.connectors.redis_conn import close_redis
    from brownbear.scheduler import shutdown_scheduler, start_scheduler

    start_scheduler()
    yield
    shutdown_scheduler()
    await close_http_client()
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )

    from brownbear.routers import (
        export,
        health,
        metrics,
        monitoring,
        ollama_proxy,
        tokens,
        ui,
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(health.router)
    app.include_router(tokens.router)
    app.include_router(monitoring.router)
    app.include_router(metrics.router)
    app.include_router(export.router)
    app.include_router(ollama_proxy.router)
    # Last: the UI owns "/", which the API used to serve.
    app.include_router(ui.router)

    @app.get("/api/info")
    async def info() -> dict:
        return {"name": settings.app_name, "version": __version__}

    return app


app = create_app()
