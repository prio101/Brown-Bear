"""Environment-driven configuration.

Every setting is overridable with a ``BB_``-prefixed environment variable,
e.g. ``BB_OLLAMA_URL=http://localhost:11434``.

Defaults assume the app runs *inside* the compose network, where services are
reachable by container name. Running on the host requires overriding the URLs.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- application ---
    app_name: str = "Brown Bear"
    debug: bool = False

    # --- backing services (in-network names, not localhost) ---
    # Roadmap D3: a dedicated `brownbear` database, never VectorAdmin's `vdbms`.
    database_url: str = (
        "postgresql+psycopg://vectoradmin:vectoradmin123@postgres:5432/brownbear"
    )
    ollama_url: str = "http://ollama:11434"
    chroma_url: str = "http://chromadb:8000"
    redis_url: str = "redis://:your_strong_password@redis:6379/0"

    # ChromaDB dropped /api/v1 (it now returns 410); v2 is current.
    chroma_api_version: str = "v2"

    # --- background jobs ---
    # Off in tests, and useful to disable on a second replica so aggregation
    # runs in exactly one place.
    scheduler_enabled: bool = True

    # --- token tracking ---
    default_currency: str = "USD"
    # Requests slower than this are still proxied; only the upstream read waits.
    ollama_timeout_seconds: float = 600.0
    health_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
