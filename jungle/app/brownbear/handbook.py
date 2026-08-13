"""The memory handbook: what Brown Bear remembers, and in what order.

An LLM on another machine reaches this stack through `/ext/context` and gets back
either an answer or some chunks. What it cannot see from that response is *which*
of four separate stores produced it, what each one guarantees, or why a miss was a
miss. This module is that explanation, and it is the reference the remote client
is expected to read before deciding how much to trust a result.

Pure data plus renderers, like `api_contract.py` and for the same reason: the page
must serve while the stack is degraded, so nothing here may import a connector, a
session or a setting. The values below are therefore *declared* defaults, labelled
as such — the live numbers come from `GET /ext/health`, and the handbook says so
rather than pretending to be authoritative about runtime state.

Three renderings, one source. `to_markdown()` is what a remote model reads,
`to_json()` is what a program reads, and the HTML page is derived from the
Markdown. Authoring them separately would guarantee they disagree within a month,
and a memory handbook that lies about the memory is worse than none.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Bumped when the *meaning* of a layer changes — a new store, a different order
#: of consultation, a changed guarantee. Not bumped for wording. A client that
#: caches this document keys on it.
HANDBOOK_VERSION = "1.0"


@dataclass(frozen=True)
class Layer:
    """One memory layer, described in the terms a caller needs to decide trust."""

    ordinal: int
    key: str
    name: str
    store: str
    module: str
    #: One line: what this layer is *for*. Not how it works.
    purpose: str
    #: What is actually keyed or indexed, in concrete terms.
    keyed_by: str
    #: The isolation boundary. Getting this wrong is the classic cause of a cache
    #: that never hits (BB-202) or one that serves another project's answer.
    scope: str
    #: What it can return to a caller. The most important field on this record.
    returns: str
    #: What it must never do, stated positively so a reader cannot skim past it.
    never: str
    #: Behaviour when its backing service is unavailable.
    on_failure: str
    declared_defaults: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


LAYERS: tuple[Layer, ...] = (
    Layer(
        ordinal=1,
        key="quick_cache",
        name="Quick Cache Layer",
        store="Redis 7",
        module="brownbear/embeddings.py",
        purpose=(
            "Avoid re-running the embedding model for a prompt that has been seen "
            "before. This is the only per-request model call in the gateway's hot "
            "path, and prompts repeat constantly in a coding loop."
        ),
        keyed_by="bb:emb:<embedding_model>:<sha256(text)> — content-addressed, model-scoped",
        scope=(
            "Global across projects and models. Safe precisely because the key is the "
            "hash of the exact text plus the embedding model: identical input, "
            "identical vector."
        ),
        returns="A vector. Never an answer, never a document.",
        never=(
            "Serve a vector computed by a different embedding model. The model name "
            "is in the key for this reason: a foreign vector would silently corrupt "
            "every similarity score the cache layer then compares against 0.95."
        ),
        on_failure=(
            "Treated as a miss. Redis being down, unreachable, or returning a corrupt "
            "payload falls through to Ollama and recomputes. It never raises."
        ),
        declared_defaults={
            "embedding_cache_enabled": True,
            "embedding_cache_ttl_seconds": 604800,
            "embedding_model": "nomic-embed-text",
        },
        notes=(
            "The TTL is memory management, not freshness — embeddings are "
            "deterministic for a fixed model. A week is long enough to be useful and "
            "short enough that a re-pulled model's vectors age out on their own.",
            "Document ingestion deliberately bypasses this layer: chunks are "
            "near-unique, so caching them would spend memory on entries that never "
            "repeat.",
        ),
    ),
    Layer(
        ordinal=3,
        key="key_based",
        name="Key Based Layer",
        store="Deterministic identifiers (SHA-256), applied at write time",
        module="brownbear/gateway.py, brownbear/tracking.py",
        purpose=(
            "Make writes idempotent. Re-storing the same exchange or re-ingesting an "
            "unchanged document replaces the existing record instead of creating a "
            "duplicate that would then compete with it at lookup time."
        ),
        keyed_by=(
            "exchange_id = x_<sha256(project\\0model\\0prompt)[:32]> for a "
            "conversation; content_id = c_<sha256(project\\0chunk_text)[:32]> for a "
            "knowledge chunk; request_id (caller-supplied) for token usage."
        ),
        scope=(
            "The project and model are inside the hash, so the same prompt asked "
            "about a different repository or by a different model is a different "
            "record, not an overwrite."
        ),
        returns=(
            "Nothing to a reader. This layer has no read path — it decides identity "
            "on write."
        ),
        never=(
            "Serve as an exact-match lookup. There is deliberately no "
            "'did I answer this precise string before' shortcut on the read side; "
            "retrieval is semantic only, through the Hard Memory Layer."
        ),
        on_failure=(
            "Not applicable — it is a hashing rule, not a service. A failed write "
            "surfaces as a 502 from /ext/exchange or /ext/documents."
        ),
        declared_defaults={
            "digest": "sha256, truncated to 32 hex characters",
            "conversation_prefix": "x_",
            "chunk_prefix": "c_",
        },
        notes=(
            "This is the layer most often misread as a fast path. It is not one. Its "
            "value is that the semantic layers above and below it never accumulate "
            "duplicates, which would otherwise split a corpus and drag scores down.",
            "request_id is the dedup key for metering: replaying an exchange must not "
            "double-count its tokens. A repeat returns token_event_id: null and a "
            "warning rather than counting twice.",
        ),
    ),
    Layer(
        ordinal=2,
        key="hard_memory",
        name="Hard Memory Layer",
        store="ChromaDB — `conversations` collection",
        module="brownbear/gateway.py :: lookup_cache, store_exchange",
        purpose=(
            "Durable prompt/answer history. This is the only layer that can produce a "
            "cache hit, because a hit must be a prior *answer* and this is the only "
            "collection that contains answers."
        ),
        keyed_by=(
            "The embedded *prompt* is the index; the answer rides along as the stored "
            "document. A lookup therefore matches on what was asked, not on what was "
            "said back."
        ),
        scope=(
            "project AND model, both matched with Chroma $eq on normalised values. An "
            "answer about one repository is never served for another, and one model's "
            "answer is not automatically valid for a different model."
        ),
        returns=(
            "A prior answer, with its similarity score, the prompt it matched, and "
            "when it was created — so the caller can reject a hit it does not like."
        ),
        never=(
            "Serve a hit below the threshold, one flagged non-cacheable, or one past "
            "its stale_after stamp. An unparseable expiry counts as expired: refusing "
            "to serve is the safe direction for a cache."
        ),
        on_failure=(
            "A lookup failure degrades to a miss and the request continues to "
            "retrieval. Brown Bear being unwell must degrade context, not block work."
        ),
        declared_defaults={
            "cache_similarity_threshold": 0.95,
            "cache_ttl_days": 30,
            "near_miss_margin": 0.05,
            "candidates_examined": 3,
            "distance_space": "cosine",
        },
        notes=(
            "Volatile prompts — 'today', 'currently', 'latest', 'what time', and "
            "anything over 4000 characters — are stored but flagged cacheable: false "
            "and never served. They are real history; their answers just expire the "
            "moment they are given.",
            "Only cosine distance converts to the 0..1 similarity the threshold is "
            "expressed in. Any other space yields no score, which callers treat as "
            "'cannot serve a hit' rather than guessing.",
            "A score within 0.05 below the cutoff is logged as a near-miss, so the "
            "threshold can be tuned from evidence rather than taste.",
            "Scope keys are normalised by stripping case and every non-alphanumeric "
            "character: Brown-Bear, brownbear, brown_bear and 'Brown Bear' all "
            "collapse to brownbear. Before BB-202 they did not, and the cache could "
            "not serve a single hit.",
        ),
    ),
    Layer(
        ordinal=4,
        key="rag",
        name="RAG (Retrieval Layer)",
        store="ChromaDB — `knowledge` collection",
        module="brownbear/gateway.py :: retrieve, ingest",
        purpose=(
            "Ground an answer the model is still going to write itself. Consulted "
            "only when the Hard Memory Layer declines to serve a hit."
        ),
        keyed_by=(
            "Documents split into overlapping character chunks, each embedded "
            "separately and stored with its source and chunk index."
        ),
        scope=(
            "project only — deliberately not model. A document is a fact about a "
            "codebase, not about whoever read it, so every model shares one corpus."
        ),
        returns=(
            "Up to k chunks, each with its text, similarity score, source and chunk "
            "index. Context to reason over — never a finished answer."
        ),
        never=(
            "Produce a cache hit. A paragraph from a document must never be served as "
            "though it were something Brown Bear had previously answered. Keeping the "
            "two collections apart is what makes that structurally impossible rather "
            "than merely discouraged."
        ),
        on_failure=(
            "Returns no chunks. The caller proceeds without grounding, which is a "
            "quality loss and not an error."
        ),
        declared_defaults={
            "context_top_k": 5,
            "chunk_chars": 1200,
            "chunk_overlap_chars": 200,
            "max_document_chars": 1000000,
        },
        notes=(
            "Chunks prefer to break at a paragraph, then a sentence, within the last "
            "quarter of the window, so they tend to split between ideas rather than "
            "mid-sentence. Overlap keeps a sentence that straddles a boundary "
            "retrievable from either side.",
            "Ingestion is idempotent by content id, so re-sending an unchanged "
            "document replaces its chunks rather than duplicating them.",
        ),
    ),
)


def ordered() -> tuple[Layer, ...]:
    """Layers in numbered order, which is NOT the order they are consulted in.

    The numbering is the catalogue: cheapest and most volatile first, the durable
    corpus last. The runtime path is `LOOKUP_ORDER`, and it differs — the Key Based
    Layer is numbered third but runs last, because it acts on write rather than on
    read. Conflating the two is the misreading this document exists to prevent, so
    both orders are published and each says what it is.
    """
    return tuple(sorted(LAYERS, key=lambda layer: layer.ordinal))


@dataclass(frozen=True)
class Step:
    ordinal: int
    layer: str
    action: str
    outcome: str


#: The actual order of consultation inside POST /ext/context, in the order the
#: code runs. This is the part a remote model most needs and can least infer.
LOOKUP_ORDER: tuple[Step, ...] = (
    Step(
        1,
        "quick_cache",
        "Embed the incoming prompt, via Redis when the vector is already known.",
        "A hit skips the embedding model entirely. A miss computes it and stores it. "
        "Either way the request continues — this layer changes cost, never outcome.",
    ),
    Step(
        2,
        "hard_memory",
        "Unless skip_cache is set, query `conversations` for the three nearest prior "
        "prompts within this project and model.",
        "If the best candidate clears the threshold, is cacheable and is unexpired, "
        "the request STOPS here: the answer is returned and `chunks` is empty. "
        "Retrieval is not run, because a hit is the whole answer.",
    ),
    Step(
        3,
        "rag",
        "On any miss — below threshold, non-cacheable, expired, or no candidate — "
        "query `knowledge` for the top k chunks in this project.",
        "Returns hit: false with the chunks, plus the score and matched_prompt of the "
        "candidate that failed, so the caller can see why it missed.",
    ),
    Step(
        4,
        "key_based",
        "Later, when the client reports the finished exchange to /ext/exchange, "
        "derive the record's identity by hash.",
        "The pair is upserted into `conversations` under a deterministic id, becoming "
        "Hard Memory for the next lookup. The prompt's vector is usually still in the "
        "Quick Cache from step 1, so storing costs no model call.",
    ),
)


@dataclass(frozen=True)
class Knob:
    name: str
    where: str
    default: str
    effect: str


#: Everything a caller can actually change, and where it lives. Split by side,
#: because remote callers repeatedly try to change server-side values through the
#: tunnel and get a 403 — PUT /api/settings is denied by design.
KNOBS: tuple[Knob, ...] = (
    Knob(
        "skip_cache",
        "per request — POST /ext/context body",
        "false",
        "Bypass the Hard Memory Layer and go straight to retrieval. Use when you know "
        "the answer must be fresh.",
    ),
    Knob(
        "k",
        "per request — POST /ext/context body",
        "context_top_k (5)",
        "How many knowledge chunks to return, 1..50. Loosens retrieval for one call "
        "without loosening the cache for everyone.",
    ),
    Knob(
        "store",
        "per request — POST /ext/exchange body",
        "true",
        "false meters the exchange without writing it to Hard Memory.",
    ),
    Knob(
        "stale_after",
        "per request — POST /ext/exchange body",
        "now + cache_ttl_days",
        "ISO-8601 expiry for this one answer. Set it short for something you know "
        "will age badly.",
    ),
    Knob(
        "BB_CACHE_MODE",
        "client hook — environment",
        "inject",
        "inject adds a cache hit as context and the model still answers. block returns "
        "the cached answer instead of calling the model — the only mode that costs "
        "zero tokens, and the only one where a wrong hit is shown as if it were an "
        "answer.",
    ),
    Knob(
        "BB_PROJECT / BB_MODEL",
        "client hook — environment",
        "git repo name / \"claude\"",
        "The two halves of the Hard Memory scope. They must match across machines or "
        "each machine keeps a private cache that no other can see.",
    ),
    Knob(
        "BB_NO_STORE / BB_STORE_MIN_CHARS",
        "client hook — environment",
        "unset / 200",
        "Meter without storing; and keep answers shorter than N characters out of the "
        "cache, since \"Done.\" is noise in a corpus.",
    ),
    Knob(
        "cache_similarity_threshold / context_top_k / cache_ttl_days",
        "server — PostgreSQL settings store, host only",
        "0.95 / 5 / 30",
        "Editable at runtime on the host. NOT changeable through the tunnel: "
        "PUT /api/settings is denied, so a remote caller may read this stack's "
        "configuration but never reconfigure it.",
    ),
)


#: Stated plainly because every one of these has been mistaken for a bug.
GUARANTEES: tuple[str, ...] = (
    "A miss is a valid, common, and usually correct outcome. The threshold is "
    "deliberately strict: a confidently wrong cache hit is worse than no cache.",
    "score and matched_prompt come back on every lookup, hit or miss. A client may "
    "apply a stricter rule than the server's, and a human can always see why "
    "something matched.",
    "Retrieval never runs on a hit, and a hit never comes from the knowledge corpus. "
    "The two collections exist separately to make that structural.",
    "Every layer degrades rather than fails. Redis down means recompute; Chroma "
    "unreachable means no context; the settings store unavailable means declared "
    "defaults. None of them block the caller's work.",
    "Nothing here calls a commercial model. Brown Bear stores, retrieves and meters; "
    "the API key never leaves the client, and the client is the only party that sees "
    "the model's response — which is why usage is reported to /ext/exchange rather "
    "than captured.",
)


def to_json() -> dict[str, Any]:
    """The machine-readable handbook.

    Deliberately the same structure the page renders, so a program and a person are
    reading one document rather than two that drifted.
    """
    return {
        "handbook_version": HANDBOOK_VERSION,
        "title": "Brown Bear — Memory Handbook",
        "summary": (
            "Four memory layers, consulted in a fixed order. Read `lookup_order` "
            "first: it is the part a caller cannot infer from a response."
        ),
        "live_values_endpoint": "/ext/health",
        "values_are": "declared defaults — query live_values_endpoint for effective values",
        "layers": [asdict(layer) for layer in ordered()],
        "lookup_order": [asdict(step) for step in LOOKUP_ORDER],
        "controls": [asdict(knob) for knob in KNOBS],
        "guarantees": list(GUARANTEES),
    }


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows]
    return out


def to_markdown() -> str:
    """The handbook as Markdown — this is what a remote LLM reads.

    Markdown rather than HTML for the machine path, for the same reason
    `/design/{slug}` serves raw Markdown: a model reading a styled page spends its
    context on the styling.
    """
    out: list[str] = [
        "# Brown Bear — Memory Handbook",
        "",
        f"Handbook version {HANDBOOK_VERSION}. Four memory layers, consulted in a fixed",
        "order. Every value below is a **declared default** — query `GET /ext/health`",
        "for what this instance is actually running.",
        "",
        "## Read this first — the order of consultation",
        "",
        "This is what a caller cannot infer from a `/ext/context` response:",
        "",
    ]
    for step in LOOKUP_ORDER:
        layer = next(l for l in LAYERS if l.key == step.layer)
        out += [
            f"**{step.ordinal}. {layer.name}** — {step.action}",
            "",
            f"> {step.outcome}",
            "",
        ]

    out += ["## The four layers", ""]
    out += _table(
        ("#", "Layer", "Store", "Can return an answer?"),
        [
            (
                str(layer.ordinal),
                layer.name,
                layer.store,
                "**Yes**" if layer.key == "hard_memory" else "No",
            )
            for layer in ordered()
        ],
    )
    out.append("")

    for layer in ordered():
        out += [
            f"### {layer.ordinal}. {layer.name}",
            "",
            f"*{layer.store} — `{layer.module}`*",
            "",
            f"**Purpose.** {layer.purpose}",
            "",
            f"**Keyed by.** {layer.keyed_by}",
            "",
            f"**Scope.** {layer.scope}",
            "",
            f"**Returns.** {layer.returns}",
            "",
            f"**Never.** {layer.never}",
            "",
            f"**On failure.** {layer.on_failure}",
            "",
        ]
        if layer.declared_defaults:
            out += ["Declared defaults:", ""]
            out += _table(
                ("Setting", "Default"),
                [(f"`{k}`", f"`{v}`") for k, v in layer.declared_defaults.items()],
            )
            out.append("")
        if layer.notes:
            out += ["Notes:", ""]
            out += [f"- {note}" for note in layer.notes]
            out.append("")

    out += ["## What you can control", ""]
    out += _table(
        ("Control", "Where", "Default", "Effect"),
        [(f"`{k.name}`", k.where, f"`{k.default}`", k.effect) for k in KNOBS],
    )
    out += ["", "## Guarantees and common misreadings", ""]
    out += [f"- {g}" for g in GUARANTEES]
    out += [
        "",
        "## Calling it",
        "",
        "```bash",
        'curl -s -X POST "$BB_GATEWAY_URL/ext/context" \\',
        '  -H "Authorization: Bearer $BB_EDGE_TOKEN" \\',
        '  -H "Content-Type: application/json" \\',
        '  -d \'{"prompt":"...","project":"brownbear","model":"claude-opus-5"}\'',
        "```",
        "",
        "A hit returns `{hit:true, answer, score, matched_prompt, created_at, chunks:[]}`.",
        "A miss returns `{hit:false, reason, score, matched_prompt, near_miss, chunks:[...]}`.",
        "Both carry `threshold`, so a client can apply a stricter rule than the server's.",
        "",
    ]
    return "\n".join(out)
