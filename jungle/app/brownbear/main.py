"""FastAPI entrypoint.

Routers are mounted here as each spec lands:
  /api/health   — F1 (this phase)
  /ollama/*     — M3 token-capturing proxy (this phase)
  /api/tokens   — spec 003 read endpoints
  /api/maintenance — spec 004
  /ext          — spec 005 context gateway (semantic cache + retrieval)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from brownbear import __version__
from brownbear.config import get_settings


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
        api_doc,
        design,
        export,
        ext,
        graph,
        handbook,
        health,
        logs,
        metrics,
        monitoring,
        ollama_proxy,
        tokens,
    )
    from brownbear.routers import settings as settings_router

    app.include_router(health.router)
    app.include_router(tokens.router)
    app.include_router(monitoring.router)
    app.include_router(metrics.router)
    app.include_router(export.router)
    app.include_router(settings_router.router)
    app.include_router(ext.router)
    app.include_router(ollama_proxy.router)
    # BB-301. Two shapes of the same question, split by the shape of the data:
    # memory is a few dozen connected documents and is served as a graph; logs are
    # tens of thousands of ordered rows and are streamed.
    app.include_router(graph.router)
    app.include_router(logs.router)

    @app.get("/api/info")
    async def info() -> dict:
        return {"name": settings.app_name, "version": __version__}

    return app


app = create_app()
