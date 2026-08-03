# Feature: Typed API Client + Data Layer

**Status:** Open
**Priority:** High — all four page tickets consume this
**Points:** 2
**Branch:** `feat/bb-103-api-client`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** BB-101 — the Next.js app must exist

---

## Overview

A single typed data layer between the Next.js pages and the FastAPI backend:
types for every endpoint the dashboard reads, one fetch wrapper with timeouts and
per-call error isolation, and a provenance model so pages can render where each
number came from. Read paths only — this sprint adds no write path.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| App directory | `jungle/web/` |
| Backend base URL | `http://app:8080` from `BB_API_URL` (Docker network, server-side only) |
| Auth needed backend-side | **None** — the FastAPI app has no auth; the edge is the boundary |
| Fetch location | React server components / server actions only. NEVER from the browser |

**Endpoints this layer must cover (all GET):**

| Endpoint | Response shape (abridged) |
|---|---|
| `/api/info` | `{name, version}` |
| `/api/health` | `{healthy: bool, services: {[name]: {...}}}` |
| `/api/system` | system metrics (cpu, memory, disk) |
| `/api/cache?minutes=` | `{window_minutes, samples, current: {timestamp, used_memory_bytes, total_keys, connected_clients, keyspace_hits, keyspace_misses, lifetime_hit_rate} \| null, window, series: [{timestamp, hits, misses, hit_rate, used_memory_bytes, total_keys, connected_clients}]}` |
| `/api/collections` | ChromaDB collections |
| `/api/tokens/summary?period=` | `{period, period_start, period_end, live, source, tokens_in, tokens_out, total_tokens, cost, currency, request_count}` |
| `/api/tokens/history?period=` | `{period, start, end, count, truncated, results: [{period_start, ...}]}` |
| `/api/tokens/by-model` | totals grouped by model |
| `/api/tokens/by-source` | totals grouped by source |
| `/api/tokens/aggregation` | aggregation job state |
| `/api/settings` | `{settings: [...]}` |
| `/ext/health` | `{ready, collections: {conversations: {id, space}, knowledge: {id, space}}, embedding_model, threshold, top_k, ttl_days}` |

**Constraints:**

- `hit_rate` and `lifetime_hit_rate` are **nullable** — `null` means "no samples",
  which is not zero. The type must be `number | null` and consumers must be forced
  to handle it.
- `/api/cache` returns `current: null` and `samples: 0` on a cold window. That is
  a valid response, not an error.
- `truncated: true` on history means results were capped; a chart drawn from a
  truncated series without saying so is wrong.
- `/api/tokens/summary` already carries provenance: `source` (e.g.
  `token_events`) and `live`. Surface it, don't discard it.
- **Denied at the edge, so never call them from the frontend:** `PUT
  /api/settings`, `POST /api/tokens/aggregate`, `/metrics`, and every Ollama
  model-management route. Server-side calls would technically succeed on the
  Docker network — which is exactly why this must be enforced in code.
- API contracts are frozen this sprint. If an endpoint is inadequate, open a
  follow-up ticket; do not change the backend here.

---

## Subtasks

### 103.1 — Types

- [ ] `src/lib/api/types.ts` — one type per endpoint above
- [ ] Nullable fields typed as nullable; no `any`, no non-null assertions
- [ ] `Provenance = "measured" | "reported" | "derived"` with a mapping from the
      backend's `source` field
- [ ] Runtime validation at the boundary (`zod` or equivalent) — a shape change in
      the backend must fail loudly at the seam, not render `NaN` three components
      deep

### 103.2 — Fetch wrapper

- [ ] `src/lib/api/client.ts` exposing one typed `get<T>(path, opts)`
- [ ] Per-call timeout, default `5000ms`; `10000ms` for `/api/export`
- [ ] Returns a discriminated result — `{ok: true, data}` | `{ok: false, error}` —
      rather than throwing, so one dead endpoint cannot blank a page
- [ ] Error object carries: endpoint, status or cause, and a timestamp for the
      "last checked" display
- [ ] `cache: "no-store"` on all dashboard reads — this is live operational data
- [ ] Server-only guard: importing this module from a client component is a build
      error

### 103.3 — Panel data helpers

- [ ] `fetchPanel(...)` helper returning `loading | ready | empty | error` as an
      explicit union — the four states the Design Book requires every panel to
      distinguish
- [ ] `empty` and `error` are separate variants. Collapsing them is the specific
      bug this models away
- [ ] Parallel fetch helper so a page issues its calls concurrently and one slow
      endpoint does not serialise the page

### 103.4 — Freshness

- [ ] Every successful result carries `fetchedAt`
- [ ] Helper formatting it as relative age ("2 min ago") for provenance badges

### 103.5 — Tests

- [ ] Unit tests: timeout, non-200, malformed body, and a `null` `hit_rate`
      surviving to the consumer as `null` rather than `0`
- [ ] A test asserting the write-path allowlist rejects `PUT /api/settings`

---

## Acceptance Criteria

- [ ] Every endpoint in the table has a type and a typed accessor
- [ ] A backend shape change fails validation at the seam with a named endpoint
- [ ] One failing endpoint degrades exactly one panel; the rest of the page renders
- [ ] `null` hit rates reach the UI as `null`, never coerced to `0`
- [ ] `truncated: true` is exposed to consumers, not swallowed
- [ ] Importing the client from a browser component fails the build
- [ ] No credentials or tokens appear anywhere in client-side JS
- [ ] No write path exists in this layer
- [ ] Page-level calls run concurrently, verified by timing a page with a
      deliberately slowed endpoint

---

## Implementation Notes

- **Result objects over exceptions:** a thrown error in a server component takes
  out the whole render subtree. Panels must fail independently, and that is a type
  decision, not a `try`/`catch` habit.
- **Why validate at runtime with types already in place:** the types describe what
  the backend promised; validation catches what it actually sent. This layer is
  the only place that gap is cheap to find.
- **`no-store` matters:** Next.js caches `fetch` aggressively by default. A cached
  token total on an operations dashboard is a correctness bug.
- **The denied-route list is a real trap:** those calls succeed server-side on the
  Docker network. Encoding the denial here keeps the frontend honest about what is
  remotely reachable.
