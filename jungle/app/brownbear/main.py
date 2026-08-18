"""FastAPI entrypoint.

Routers are mounted here as each spec lands:
  /api/health   — F1 (this phase)
  /ollama/*     — M3 token-capturing proxy (this phase)
  /api/tokens   — spec 003 read endpoints
  /api/maintenance — spec 004
  /ext          — spec 005 context gateway (semantic cache + retrieval)
  /ext/agents   — spec 008 agent configuration sync
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
        agents,
        api_doc,
        design,
        export,
        ext,
        files,
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
    # Spec 007. Under /ext/, so the edge publishes it with the same shared secret
    # as the rest of the gateway and needs no new nginx location.
    app.include_router(files.router)
    # Spec 008. Under /ext/ for the same reason files are: the edge already
    # authenticates everything there with the shared secret, so a machine's
    # configuration is never reachable without it.
    app.include_router(agents.router)
    # Public, unauthenticated at the edge (BB-109).
    app.include_router(design.router)
    # Authenticated at the edge (spec 006): an endpoint inventory describes the
    # attack surface, which design tokens do not.
    app.include_router(api_doc.router)
    # Same prefix, separate module: the memory handbook explains what the endpoint
    # list cannot — which of the four stores answered, and what it guarantees.
    app.include_router(handbook.router)
    # No router owns "/" any more: the Next.js frontend serves every page, and the
    # edge proxies them to web:3000 (BB-104, BB-110).

    @app.get("/api/info")
    async def info() -> dict:
        return {"name": settings.app_name, "version": __version__}

    return app


app = create_app()
