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

    # --- public design book (BB-109) ---
    # Mounted read-only from jungle/dev/design rather than baked into the image,
    # so an edited document publishes without a rebuild. An absent directory
    # degrades the route to 404; it never breaks startup.
    design_dir: str = "/app/brownbear/design"

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

    # --- monitoring collection ---
    snapshot_interval_seconds: int = 30
    cache_sample_interval_seconds: int = 30
    # At a 30s interval these tables grow by ~5,800 rows a day each; nothing
    # else would ever remove them. Token retention is separate and longer.
    monitoring_retention_days: int = 7

    # --- token tracking ---
    default_currency: str = "USD"
    # Requests slower than this are still proxied; only the upstream read waits.
    ollama_timeout_seconds: float = 600.0
    health_timeout_seconds: float = 5.0

    # --- context gateway (spec 005) ---
    # An embedding model, not a chat model: Ollama answers /api/embed with 501
    # for a model whose runner has no embedding support.
    embedding_model: str = "nomic-embed-text"
    embedding_timeout_seconds: float = 120.0

    # --- embedding cache (BB-201) ---
    # Embedding the prompt is the only per-request model call in the gateway's hot
    # path, and prompts repeat in a coding loop. Keyed by model, because a vector
    # from one embedding model is meaningless to another.
    embedding_cache_enabled: bool = True
    # Embeddings are deterministic for a fixed model, so the TTL is memory
    # management rather than freshness. A week is long enough to be useful and
    # short enough that a re-pulled model's stale vectors age out on their own.
    embedding_cache_ttl_seconds: int = 604_800
    # Texts per /api/embed call. Ollama loads the whole batch at once, so this
    # bounds peak memory rather than optimising throughput.
    embedding_batch_size: int = 32

    # --- file ingestion (spec 007) ---
    # Content-addressed blobs on a volume. Not in the image: an uploaded corpus
    # must survive a rebuild, and a 50MB file has no business in a layer.
    blob_dir: str = "/data/blobs"
    # Enforced while streaming, not after. A cap checked once the body has been
    # read is not a cap — the bytes are already here.
    max_upload_bytes: int = 50 * 1024 * 1024
    # Client-supplied thumbnails only; nothing renders server-side. Small because a
    # preview that is not much smaller than the original is not a preview.
    max_preview_bytes: int = 2 * 1024 * 1024

    # --- agent configuration sync (spec 008) ---
    # These are small text files a reader wants to read, so they live in Postgres
    # rather than in the blob store: dedup and streaming buy nothing here, and a
    # `text` column is what makes them listable and comparable.
    #
    # 256 KB is well above any real settings file or skill document. A file over
    # the cap is recorded with its size and digest and no content — never
    # truncated, because a configuration file cut in half is a configuration that
    # exists on no machine.
    max_config_file_bytes: int = 256 * 1024
    # A whole `.claude` directory in one request. The edge caps the body at 52 MB;
    # this is the app's own, smaller limit, stated in the rejection so a client is
    # never silently truncated.
    max_sync_bytes: int = 8 * 1024 * 1024
    max_sync_files: int = 500
    # Uncompressed ceiling for a zip. Higher than max_sync_bytes because the
    # archive arrives compressed and text compresses well.
    max_sync_unpacked_bytes: int = 32 * 1024 * 1024
    # After this, a machine's configuration is shown as stale rather than as
    # current. A sync is a deliberate client action, so silence is expected — and
    # silence must never be rendered as an up-to-date configuration.
    config_stale_hours: int = 24
    # After this, "no usage reported" is shown as possibly-broken rather than as
    # a quiet day (BB-205). The client hooks fail open and silent, so an empty
    # token page is ambiguous by construction and something has to resolve it.
    # Longer than the config window on purpose: a machine syncs its configuration
    # on a schedule, but nobody owes this stack a prompt.
    usage_stale_hours: int = 24
    # How many past contents of one configuration file to keep (spec 010). Bounded
    # deliberately: after blobs, an unbounded history is the second thing in this
    # stack that would grow forever with nothing pruning it. Ten covers "what did I
    # change last week"; it is not an archive.
    config_revisions_kept: int = 10

    # Two collections, never one: a cache hit must be a prior *answer*, and a
    # mixed collection lets a document paragraph clear the threshold and get
    # served as though it were one (spec 005).
    conversations_collection: str = "conversations"
    knowledge_collection: str = "knowledge"

    # Chunking for ingested documents. Overlap keeps a sentence spanning a
    # boundary retrievable from either side.
    chunk_chars: int = 1200
    chunk_overlap_chars: int = 200

    # Start strict: a wrong cache hit is worse than no cache. Tune down only
    # with evidence from the near-miss log. Editable at runtime via /settings.
    cache_similarity_threshold: float = 0.95
    context_top_k: int = 5
    # Code answers go stale as the codebase moves. 0 disables expiry.
    cache_ttl_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
