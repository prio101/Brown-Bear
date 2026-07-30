"""FastAPI entrypoint.

Routers are mounted here as each spec lands:
  /api/health   — F1 (this phase)
  /ollama/*     — M3 token-capturing proxy (this phase)
  /api/tokens   — spec 003 read endpoints
  /api/maintenance — spec 004
  /ext          — spec 002 external gateway
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

    from brownbear.routers import health, ollama_proxy, tokens

    app.include_router(health.router)
    app.include_router(tokens.router)
    app.include_router(ollama_proxy.router)

    @app.get("/")
    async def root() -> dict:
        return {"name": settings.app_name, "version": __version__}

    return app


app = create_app()
