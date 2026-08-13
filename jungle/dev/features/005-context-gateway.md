# Feature: Context Gateway & Semantic Cache

**Status:** Open
**Priority:** High — this is the reason the stack exists
**Date:** 2026-07-30
**Reorders:** spec 002 (tunnel/gateway) moves ahead of 003's M8 and spec 004

---

## Overview

Brown Bear sits in front of Claude as a **context gateway**. An external machine (Arch
Linux running Claude Code) asks Brown Bear for context before every request. Brown Bear
answers from a semantic cache when it can, and otherwise returns retrieved context for the
client to send to Claude itself.

Brown Bear never calls Anthropic. The API key stays on the client, and Brown Bear being
down degrades context rather than blocking work.

---

## Flow

```
Arch PC                          tunnel                Brown Bear (WSL2)
   │                                │
   │ 1. POST /ext/context ──────────►│──► embed(prompt)
   │    {prompt, project, model}     │    │
   │                                 │    ├─► search conversations collection
   │                                 │    │     score ≥ threshold ─► CACHE HIT
   │                                 │    └─► search knowledge collection
   │                                 │          top-k chunks     ─► CONTEXT
   │ ◄───────────────────────────────│
   │   {hit: true,  answer, score, matched_prompt}   → use it, 0 tokens
   │   {hit: false, chunks[]}                        → build prompt, call Claude
   │                                 │
   │ 2. POST /ext/exchange ─────────►│──► store prompt+response in conversations
   │    {prompt, response, usage}    │──► record token_events (source=remote_api)
```

Step 2 carries the token usage, which is what spec 003's **M8** becomes: the client is the
only party that sees the Anthropic response, so usage must be reported, not captured.

---

## Decisions (locked)

| Decision | Choice | Consequence |
|---|---|---|
| Who calls Anthropic | **The client** | M8 is required; metering depends on the client reporting |
| Cache type | **Semantic** (embedding similarity) | Needs embeddings; needs a threshold; can return a wrong answer if too loose |
| Corpus | Past Claude conversations **and** docs/notes/PDFs | Two separate collections — see below |
| Prompt privacy | Prompt transits the tunnel | Required for server-side embedding. Client-side embedding is the alternative |

### Two collections, never one

`conversations` and `knowledge` do different jobs and must not share a collection:

- A **cache hit** must be a prior *answer*. Searching a mixed collection lets a PDF
  paragraph clear the similarity threshold and get returned as though it were an answer.
- The two want different thresholds: a cache hit needs near-identity, retrieval wants loose
  top-k.

Each collection records the embedding model and dimension it was built with. Changing
embedding models invalidates every vector in it — that is spec 004's `ReEmbedder`.

---

## Blockers — all three cleared 2026-07-31

1. ~~**Ollama has no embeddings.**~~ **Cleared, and the diagnosis was wrong.** The 501 said
   `Start it with --embeddings`, which read as a missing server flag; it is not. Ollama
   returns 501 for any model whose runner has no embedding support, and the only model
   pulled was a chat model. Pulling `nomic-embed-text` fixed it with **no compose change**:
   `/api/embed` returns 768-dim vectors and batches correctly.
2. ~~**No authentication anywhere.**~~ **Cleared at the edge, not in the app.** One shared
   secret in `edge/nginx.conf.template`, accepted as `Authorization: Bearer` (machines) or
   HTTP basic (browsers, which cannot send a bearer header from the address bar). The app
   itself still has no auth — this is a boundary control, so anything bypassing the edge
   bypasses it. Spec 002 §2.3's per-key auth, rate limiting and audit log are still open.
3. ~~**ChromaDB is empty.**~~ `conversations` and `knowledge` are created on demand by
   `/ext/health`, both in **cosine** space, with embedding model and dimension recorded.

**Why cosine matters.** Chroma defaults to `l2`, whose distances are unbounded and cannot be
compared to a 0.95 cutoff. Collections are created with cosine explicitly, and
`gateway.similarity()` returns `None` for any other space — a non-cosine collection can
never serve a hit rather than serving one on a meaningless number.

---

## Requirements

### Semantic cache safety

A cache that returns a confidently wrong answer is worse than no cache. Non-negotiables:

- **Start strict.** Cosine similarity ≥ 0.95 to serve a hit; tune down only with evidence.
- **Always return `score` and `matched_prompt`.** The client can reject a hit it does not
  like, and a human can see *why* something matched.
- **Scope the key.** A hit is only valid for the same `model` and same `project`. An answer
  about one repo must never serve another.
- **Expire.** Code answers go stale as the codebase moves; cached exchanges carry a TTL and
  a `stale_after` the client can override.
- **Never cache volatile prompts.** Anything referencing "today", current time, or pasted
  file contents is stored but flagged non-cacheable.
- **Log every near-miss** (score within 0.05 of the threshold) so the threshold is tuned
  from data rather than taste.

### Retrieval

- Top-k chunks from `knowledge`, k configurable, with per-chunk source attribution
- Chunking with overlap; PDFs parsed on ingest
- Every query logged to `query_logs` — the table exists and has been empty since spec 001,
  and spec 004's access-based pruning depends on it

### Reporting (M8)

- `POST /ext/exchange` records the token usage *and* stores the exchange in one call
- Dedup on `request_id` (the unique constraint already exists and is verified)
- **Backdated windows must be re-aggregated.** Catch-up moves a cursor forward, so a
  reported event older than the newest completed run gets no bucket. Mark affected windows
  dirty and re-run them, cascading daily → weekly → monthly.
- **Unpriced remote models must not read $0.** The `*` fallback row makes any unknown model
  free, which is correct for local inference and wrong for a paid one. For
  `source=remote_api` with no explicit price, record cost as unknown, not zero, and surface
  it on the dashboard.

---

## Subtasks

### 5.1 — Embeddings foundation
- [x] Pull `nomic-embed-text` — no server flag needed; see the blocker note above
- [x] `connectors/ollama.embed()` with batching (`embedding_batch_size`, default 32)
- [x] Record embedding model + dimension per collection

### 5.2 — Collections
- [x] Create `conversations` and `knowledge` collections with recorded dimensions
- [x] Metadata schema: project, source, model, created_at, stale_after

### 5.3 — Ingestion
- [x] `POST /ext/documents` — text, chunked, embedded, stored in `knowledge`
- [ ] PDF parsing on ingest — **still open**; the endpoint takes text only
- [x] Re-ingest is idempotent by content hash

### 5.4 — Context endpoint
- [x] `POST /ext/context` — embed, cache-check, retrieve, one response
- [x] Threshold, k and TTL configurable through the settings store
- [x] Near-miss logging — emitted to the application log with score and cutoff
- [ ] Near-misses are not *queryable*: `query_logs` has no score column, so tuning the
      threshold from data still means reading logs. A `cache_lookups` table would fix it.

### 5.5 — Exchange endpoint (M8)
- [x] `POST /ext/exchange` — store the pair, record `token_events`, dedup
- [ ] Dirty-window re-aggregation for backdated usage — **still open.** `catch_up` seeds its
      cursor from the newest completed run and walks forward, so a reported event older than
      that gets no bucket. Latent while clients report current usage; a real hole the moment
      one backfills.
- [~] Unknown-price handling: the endpoint accepts `cost_usd` from the client and **warns**
      when a paid model has no pricing row, instead of silently reporting $0. The persisted
      value is still 0 in that case — `token_events.cost_usd` is `NOT NULL`, so recording
      genuinely-unknown cost needs a migration.

### 5.6 — Tunnel and auth (spec 002 §2.1–2.3)
- [x] `cloudflared` service, profile-gated so nothing publishes by accident
- [x] Default-deny edge allowlist (`edge/nginx.conf.template`) as the tunnel's origin
- [x] Shared-secret authentication at the edge, bearer or basic, fail-closed when unset
- [ ] Per-key auth *in the app* — still open. The edge is a boundary control: it identifies
      nobody, cannot be revoked per client, and is bypassed by anything reaching :8080
      directly. Spec 002 §2.3 remains the real fix.
- [ ] Rate limiting, audit log

#### What is exposed today

The tunnel points at `edge:8081`, never at `app:8080`. Two layers now stand in front of it:
authentication, then the allowlist.

| Path | Auth | Notes |
|---|---|---|
| `GET /api/health/live` | **none** | Deliberately public so an external monitor can probe it. Returns `{"status":"ok"}` and nothing else |
| `/ext/*` | required | The gateway. Prompts in, cached answers and context out |
| `GET /`, `/tokens`, `/cache`, `/collections`, `/settings`, `/static/*` | required | The dashboard, read-only |
| `GET /api/{info,health,system,cache,collections,export}` | required | Read-only |
| `GET /api/settings` | required | Read only — `PUT` is denied even with a valid credential |
| `GET /api/tokens/{summary,history,by-model,by-source,aggregation}` | required | Read-only |
| `POST /ollama/api/{chat,generate,embed}`, `GET /ollama/api/tags` | required | Inference only |

Denied outright, credential or not: `PUT /api/settings`, `POST /api/tokens/aggregate`,
`/metrics`, and every Ollama model-management route — `pull`, `create`, `copy`, `push`,
`delete` — because those let a caller fill the disk or destroy pulled models.

**One secret, two forms.** `Authorization: Bearer <BB_EDGE_TOKEN>` for machines; HTTP basic
(user `bb`, same token as the password) for browsers, which cannot be told to send a bearer
header from the address bar. Both live in `.env`, which is gitignored; the config is an
envsubst template so no secret is ever committed.

**Fail-closed.** envsubst renders an unset `BB_EDGE_TOKEN` as the literal valid credential
`"Bearer "`, which anyone could send. A guard map turns an empty secret into "reject
everyone". Verified against a container started with no secret: every gated route 401s,
including `Authorization: Bearer ` with the trailing space.

**This is a boundary control, not per-client identity.** One secret shared by every caller:
it cannot be revoked for one machine, it attributes nothing in the audit log, and anything
that reaches `app:8080` directly — another process on the host, another container on the
compose network — bypasses it completely. Spec 002 §2.3 is still the real fix.

#### Runbook

Persistent tunnel — **this is the live configuration.** The public URL is fixed
at `https://brownbear.frostmangobox.com` and needs no per-restart action.

It is served by the *host* cloudflared, not by a compose service:

```bash
systemctl status cloudflared     # unit: cloudflared.service
journalctl -u cloudflared -f     # named tunnel, token at /etc/cloudflared/token
```

Its public hostname routes to **`http://localhost:8081`** — the edge, never
`app:8080`. `localhost` rather than `edge:8081` because the host cloudflared
runs outside the compose network and reaches the edge via the `127.0.0.1:8081`
binding. Ingress is managed remotely in the Zero Trust dashboard, so routing
changes are made there, not in this repo.

Compose's `cloudflared` service (profile `tunnel`, origin `http://edge:8081`,
token from `.env`) is the unused alternative, for moving the tunnel into the
stack. Do not run it and the host unit against the same tunnel.

Throwaway tunnel (no account, random URL, gone on stop) — **local testing only,
never for another machine:**

```bash
docker compose --profile quicktunnel up -d
docker compose logs cloudflared-quick | grep trycloudflare.com   # the URL
```

Its URL changes on every restart, and the client hooks fail open — so a dead
quick tunnel silently detaches every remote node rather than raising an error.

Neither profile starts with a plain `docker compose up`.

### 5.7 — Dashboard
- [ ] Cache hit rate, tokens saved, and near-miss list
- [ ] Collection health per corpus

---

## Acceptance criteria

Verified 2026-07-31 through the live Cloudflare tunnel, not just locally.

- [x] A repeated question returns a cache hit with its score and matched prompt, and costs
      zero tokens — score 1.0, matched prompt echoed back
- [x] A near-but-different question does **not** hit, and appears in the near-miss log —
      "vector embeddings" vs "metadata" scored 0.829 against a 0.95 cutoff and was refused
- [x] A hit never crosses `project` or `model` boundaries — both scoped by a Chroma `where`
      filter; changing either returns "no candidates"
- [x] A miss returns useful retrieved chunks with source attribution
- [~] Reported usage lands in `token_events` — yes, deduplicated on `request_id`. **Backdated
      usage still misses its window**: see the open item under §5.5
- [~] A paid model with no configured price reports unknown cost, never $0 — it *warns* and
      accepts a client-supplied `cost_usd`; the stored value is still 0 without one, pending
      a nullable-cost migration
- [x] Every `/ext` route rejects an unauthenticated call — 401 with a `WWW-Authenticate`
      challenge; wrong, empty and absent credentials all rejected
- [x] Brown Bear being down degrades the client rather than blocking it — a missing embedding
      model answers 503 with what to fix, and the gateway falls back to its configured
      defaults when the settings store is unreachable rather than failing the lookup

Also verified: 92 unit tests pass (54 new), `ruff check` clean, and re-ingesting identical
content returns the same chunk ids rather than duplicating them.

---

## Open questions

- Does the client fall back gracefully (plain Claude call) on gateway timeout? It should —
  design the client wrapper with a short timeout and a bypass.
- One `project` per repo, or per working directory? Affects cache scoping.
- Should conversation storage be opt-in per request? Everything sent is retained by default,
  which is a lot of prompt history on one machine.
