"""What is actually reachable through the tunnel (spec 006).

FastAPI's OpenAPI schema describes the *app*. The edge describes the *contract*,
and the two disagree in ways that would mislead anyone writing a client: the
schema advertises `PUT /api/settings`, `POST /api/tokens/aggregate`, `GET /metrics`
and an `/ollama/{path}` catch-all accepting seven methods, every one of which the
edge denies except four named Ollama routes.

This module is the declared contract. It is a second source of truth beside
`edge/nginx.conf.template`, and a second source of truth rots — so
`tests/test_api_doc.py` parses the edge template and asserts the two agree. Adding
a route to the edge without declaring it here, or declaring one the edge does not
publish, fails the suite.

Denied endpoints are declared rather than omitted. A reader needs to know that
`PUT /api/settings` exists and is deliberately unreachable; silence would read as
an oversight and invite someone to try.
"""

from dataclasses import dataclass
from enum import Enum


class Reach(str, Enum):
    """How an endpoint behaves through the edge."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    DENIED = "denied"


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    reach: Reach
    group: str
    summary: str


#: Order is presentation order within a group.
CONTRACT: tuple[Endpoint, ...] = (
    # --- context gateway -----------------------------------------------------
    Endpoint(
        "POST", "/ext/context", Reach.AUTHENTICATED, "Context gateway",
        "Ask for context before calling a model. Returns a cached prior answer, or "
        "retrieved chunks to send yourself.",
    ),
    Endpoint(
        "POST", "/ext/exchange", Reach.AUTHENTICATED, "Context gateway",
        "Report a completed exchange: stores the prompt/answer pair and records "
        "token usage. The client is the only party that sees the model's response, "
        "so usage is reported here rather than captured.",
    ),
    Endpoint(
        "POST", "/ext/documents", Reach.AUTHENTICATED, "Context gateway",
        "Ingest a document into the knowledge collection. Chunked and embedded; "
        "idempotent by content.",
    ),
    Endpoint(
        "GET", "/ext/health", Reach.AUTHENTICATED, "Context gateway",
        "Gateway readiness: embedding model, collections and their distance spaces, "
        "cache threshold, top-k and TTL.",
    ),
    # --- health --------------------------------------------------------------
    Endpoint(
        "GET", "/api/health/live", Reach.PUBLIC, "Health",
        "Liveness probe. Deliberately unauthenticated so an external monitor can "
        "reach it; reveals nothing but whether the app is up.",
    ),
    Endpoint(
        "GET", "/api/health", Reach.AUTHENTICATED, "Health",
        "Backing-service health. Always 200 — the payload carries the verdict, so a "
        "degraded Redis never makes the app itself look dead.",
    ),
    Endpoint("GET", "/api/info", Reach.AUTHENTICATED, "Health", "App name and version."),
    # --- monitoring ----------------------------------------------------------
    Endpoint(
        "GET", "/api/system", Reach.AUTHENTICATED, "Monitoring",
        "Host CPU, memory and disk: the latest sample plus a series over the window. "
        "Sampled every 30s.",
    ),
    Endpoint(
        "GET", "/api/cache", Reach.AUTHENTICATED, "Monitoring",
        "Redis counters over a window. `hit_rate` and `lifetime_hit_rate` are "
        "nullable — null means no samples, which is not zero.",
    ),
    Endpoint(
        "GET", "/api/collections", Reach.AUTHENTICATED, "Monitoring",
        "ChromaDB collections with document counts, dimensions and recorded "
        "embedding model.",
    ),
    Endpoint(
        "GET", "/api/export", Reach.AUTHENTICATED, "Monitoring",
        "Stream a dataset as CSV or JSON.",
    ),
    # --- tokens --------------------------------------------------------------
    Endpoint(
        "GET", "/api/tokens/summary", Reach.AUTHENTICATED, "Tokens",
        "Totals for a period, with `source` and `live` describing where the numbers "
        "came from.",
    ),
    Endpoint(
        "GET", "/api/tokens/history", Reach.AUTHENTICATED, "Tokens",
        "One row per (period, model, source) — NOT one row per period. Group by "
        "`period_start` to build a time series.",
    ),
    Endpoint("GET", "/api/tokens/by-model", Reach.AUTHENTICATED, "Tokens", "Totals grouped by model."),
    Endpoint(
        "GET", "/api/tokens/by-source", Reach.AUTHENTICATED, "Tokens",
        "Totals grouped by source. `local_ollama` is measured here; `remote_api` is "
        "reported by a client and is only as trustworthy as that client.",
    ),
    Endpoint(
        "GET", "/api/tokens/aggregation", Reach.AUTHENTICATED, "Tokens",
        "Rollup job state: latest completed window per grain, and recent runs.",
    ),
    Endpoint(
        "POST", "/api/tokens/aggregate", Reach.DENIED, "Tokens",
        "Trigger a rollup. Denied through the tunnel — read the state, never trigger it.",
    ),
    # --- memory graph (BB-301) -----------------------------------------------
    Endpoint(
        "GET", "/api/graph", Reach.AUTHENTICATED, "Memory graph",
        "Stored memory as nodes and edges: collections, projects, models, sources, "
        "exchanges and chunks, with the structural edges between them. Structural "
        "only — similarity is computed per node on expand.",
    ),
    Endpoint(
        "GET", "/api/graph/node", Reach.AUTHENTICATED, "Memory graph",
        "One node with its neighbourhood. For an exchange or a chunk this also "
        "returns its nearest other memories as weighted `similar_to` edges. Takes "
        "`?id=<kind>:<value>`.",
    ),
    Endpoint(
        "GET", "/api/logs/recent", Reach.AUTHENTICATED, "Memory graph",
        "The most recent query and token log rows as one response — the same rows "
        "the stream opens with, for a client that will not hold a connection.",
    ),
    Endpoint(
        "GET", "/api/logs/stream", Reach.AUTHENTICATED, "Memory graph",
        "Live query and token logs as Server-Sent Events. Frames are typed: query, "
        "token, ready, heartbeat, error. Logs stream rather than joining the graph — "
        "they outnumber stored memories by roughly a thousand to one.",
    ),
    # --- settings ------------------------------------------------------------
    Endpoint(
        "GET", "/api/settings", Reach.AUTHENTICATED, "Settings",
        "Effective configuration with each value's source layer.",
    ),
    Endpoint(
        "PUT", "/api/settings", Reach.DENIED, "Settings",
        "Change configuration. Denied through the tunnel by design: an authenticated "
        "remote caller may read this stack but not reconfigure it. Change settings on "
        "the host.",
    ),
    # --- inference proxy -----------------------------------------------------
    # FastAPI reports one /ollama/{path} catch-all accepting seven methods. The edge
    # publishes exactly these four. Rendering the catch-all verbatim would be the
    # single most misleading line on the page.
    Endpoint(
        "POST", "/ollama/api/chat", Reach.AUTHENTICATED, "Inference proxy",
        "Proxied chat completion. Token usage is counted locally on the way through.",
    ),
    Endpoint("POST", "/ollama/api/generate", Reach.AUTHENTICATED, "Inference proxy", "Proxied completion."),
    Endpoint("POST", "/ollama/api/embed", Reach.AUTHENTICATED, "Inference proxy", "Proxied embedding."),
    Endpoint("GET", "/ollama/api/tags", Reach.AUTHENTICATED, "Inference proxy", "List pulled models."),
    Endpoint(
        "POST", "/ollama/api/pull", Reach.DENIED, "Inference proxy",
        "Model management is denied through the tunnel — pull, create, copy, push and "
        "delete would let a caller fill the disk or destroy pulled models.",
    ),
    # --- metrics -------------------------------------------------------------
    Endpoint(
        "GET", "/metrics", Reach.DENIED, "Metrics",
        "Prometheus exposition. Denied through the tunnel; scrape it on the host.",
    ),
    Endpoint("GET", "/api/metrics", Reach.DENIED, "Metrics", "Metrics as JSON. Denied through the tunnel."),
    # --- documentation -------------------------------------------------------
    Endpoint(
        "GET", "/design", Reach.PUBLIC, "Documentation",
        "The design system, rendered. Public: design values describe nobody's attack "
        "surface.",
    ),
    Endpoint("GET", "/design/{slug}", Reach.PUBLIC, "Documentation", "The design documents as raw Markdown."),
    Endpoint(
        "GET", "/api-doc/v1", Reach.AUTHENTICATED, "Documentation",
        "This page. Authenticated, unlike /design, because an endpoint inventory does "
        "describe the attack surface.",
    ),
    Endpoint(
        "GET", "/api-doc/v1/openapi.json", Reach.AUTHENTICATED, "Documentation",
        "The OpenAPI schema, annotated with the reachability shown here.",
    ),
    Endpoint(
        "GET", "/api-doc/v1/handbook", Reach.AUTHENTICATED, "Documentation",
        "The memory handbook: the four layers, the order they are consulted in, and "
        "what each will and will not return. Answers what the endpoint list cannot — "
        "which store produced a result.",
    ),
    Endpoint(
        "GET", "/api-doc/v1/handbook.md", Reach.AUTHENTICATED, "Documentation",
        "The handbook as raw Markdown. This is the one a model on another machine "
        "should read: the rendered page would spend its context on styling.",
    ),
    Endpoint(
        "GET", "/api-doc/v1/handbook.json", Reach.AUTHENTICATED, "Documentation",
        "The handbook structured for a program: layers, lookup order, controls and "
        "guarantees as fields rather than prose.",
    ),
)

#: Group presentation order.
GROUPS: tuple[str, ...] = (
    "Context gateway",
    "Memory graph",
    "Tokens",
    "Monitoring",
    "Health",
    "Settings",
    "Inference proxy",
    "Metrics",
    "Documentation",
)


def by_group() -> dict[str, list[Endpoint]]:
    grouped: dict[str, list[Endpoint]] = {group: [] for group in GROUPS}
    for endpoint in CONTRACT:
        grouped.setdefault(endpoint.group, []).append(endpoint)
    return {group: items for group, items in grouped.items() if items}


def reach_of(method: str, path: str) -> Reach | None:
    """Declared reachability, or None when the path is not in the contract."""
    for endpoint in CONTRACT:
        if endpoint.method == method.upper() and endpoint.path == path:
            return endpoint.reach
    return None
