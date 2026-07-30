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

## Blockers (must clear before any of this works)

1. **Ollama has no embeddings.** `/api/embed` returns 501 on this host and no embedding
   model is pulled. Both the cache and retrieval depend on it. Pull `nomic-embed-text`
   (768-dim) and confirm the endpoint answers.
2. **No authentication anywhere.** Today `PUT /api/settings`, `POST /api/tokens/aggregate`
   and the whole `/ollama/*` proxy are open. Opening a tunnel to :8080 as it stands exposes
   all of it. Spec 002 §2.3 must land *with* the tunnel, not after.
3. **ChromaDB is empty.** Ingestion (§5.3) has to exist before retrieval means anything.

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
- [ ] Enable embeddings on the Ollama service; pull `nomic-embed-text`
- [ ] `connectors/ollama.embed()` with batching
- [ ] Record embedding model + dimension per collection

### 5.2 — Collections
- [ ] Create `conversations` and `knowledge` collections with recorded dimensions
- [ ] Metadata schema: project, source, model, created_at, stale_after

### 5.3 — Ingestion
- [ ] `POST /ext/documents` — text, chunked, embedded, stored in `knowledge`
- [ ] PDF parsing on ingest
- [ ] Re-ingest is idempotent by content hash

### 5.4 — Context endpoint
- [ ] `POST /ext/context` — embed, cache-check, retrieve, one response
- [ ] Threshold, k and TTL configurable through the settings store
- [ ] Near-miss logging

### 5.5 — Exchange endpoint (M8)
- [ ] `POST /ext/exchange` — store the pair, record `token_events`, dedup
- [ ] Dirty-window re-aggregation for backdated usage
- [ ] Unknown-price handling for remote models

### 5.6 — Tunnel and auth (spec 002 §2.1–2.3)
- [x] `cloudflared` service, profile-gated so nothing publishes by accident
- [x] Default-deny edge allowlist (`edge/nginx.conf`) as the tunnel's origin
- [ ] API-key middleware over every `/ext` and `/api` route — **deferred by decision**
- [ ] Rate limiting, audit log

#### What is exposed today

The tunnel points at `edge:8081`, never at `app:8080`. The edge default-denies and forwards
exactly two things:

| Path | Why it is safe without auth |
|---|---|
| `GET /api/health/live` | Returns `{"status":"ok"}` and nothing else |
| `/ext/*` | The gateway surface. Does not exist yet, so it 404s today |

Everything else — `/api/settings`, `/api/tokens/*`, `/api/export`, `/metrics`, the dashboard,
and the whole `/ollama/*` proxy — returns 403 at the edge. Verified: a `PUT /api/settings`
through the edge is refused and the setting is unchanged.

**This is containment, not authentication.** Anyone who learns the hostname can call the
allowed paths. That is acceptable while the only allowed path is a liveness probe. It stops
being acceptable the moment `/ext/*` carries prompts and returns retrieved context — so
§2.3's API keys must land with 5.4, not after.

#### Runbook

Persistent tunnel (survives restarts, stable hostname):

1. In the Cloudflare Zero Trust dashboard: **Networks → Tunnels → Create a tunnel**
2. Copy the token into `.env` as `CLOUDFLARE_TUNNEL_TOKEN`
3. Add a public hostname routed to **`http://edge:8081`** — not `app:8080`
4. `docker compose --profile tunnel up -d`

Throwaway tunnel (no account, random URL, gone on stop):

```bash
docker compose --profile quicktunnel up -d
docker compose logs cloudflared-quick | grep trycloudflare.com   # the URL
```

Neither profile starts with a plain `docker compose up`.

### 5.7 — Dashboard
- [ ] Cache hit rate, tokens saved, and near-miss list
- [ ] Collection health per corpus

---

## Acceptance criteria

- [ ] A repeated question returns a cache hit with its score and matched prompt, and costs
      zero tokens
- [ ] A near-but-different question does **not** hit, and appears in the near-miss log
- [ ] A hit never crosses `project` or `model` boundaries
- [ ] A miss returns useful retrieved chunks with source attribution
- [ ] Reported usage lands in `token_events` and reaches the right aggregate window even
      when backdated
- [ ] A paid model with no configured price reports unknown cost, never $0
- [ ] Every `/ext` route rejects an unauthenticated call
- [ ] Brown Bear being down degrades the client to a plain Claude call, never blocks it

---

## Open questions

- Does the client fall back gracefully (plain Claude call) on gateway timeout? It should —
  design the client wrapper with a short timeout and a bypass.
- One `project` per repo, or per working directory? Affects cache scoping.
- Should conversation storage be opt-in per request? Everything sent is retained by default,
  which is a lot of prompt history on one machine.
