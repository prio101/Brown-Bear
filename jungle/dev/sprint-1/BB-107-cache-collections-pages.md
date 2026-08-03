# Feature: Cache + Collections Pages

**Status:** Open
**Priority:** Medium — the surfaces where a wrong cache hit becomes visible
**Points:** 2
**Branch:** `feat/bb-107-cache-collections`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** BB-102 (tokens), BB-103 (API client), BB-106 (chart primitives)

---

## Overview

Two pages: `/cache` reports Redis cache behaviour over a window, and
`/collections` reports the ChromaDB corpus that retrieval and the semantic cache
depend on. Together they answer "is the cache working, and can I trust what it
returns" — which makes the honest handling of nulls and non-cosine spaces the
whole job.

---

## Context

**Reads required:** this file, plus `../design/DESIGN-BOOK.md` (normative spec).

| Fact | Value |
|---|---|
| Routes | `/cache`, `/collections` in `jungle/web/` |
| Endpoints | `GET /api/cache?minutes=`, `GET /api/collections`, `GET /ext/health` |
| `/api/cache` shape | `{window_minutes, samples, current: {timestamp, used_memory_bytes, total_keys, connected_clients, keyspace_hits, keyspace_misses, lifetime_hit_rate} \| null, window, series: [{timestamp, hits, misses, hit_rate, used_memory_bytes, total_keys, connected_clients}]}` |
| Cold-window response | `{window_minutes, samples: 0, current: null, window: null, series: []}` — valid, not an error |
| `/ext/health` shape | `{ready, collections: {conversations: {id, space}, knowledge: {id, space}}, embedding_model, threshold, top_k, ttl_days}` |
| Gateway defaults | threshold `0.95`, top_k `5`, ttl_days `30`, embedding `nomic-embed-text` (768-dim), space `cosine` |
| Collections | `conversations` (cache hits — prior answers) and `knowledge` (retrieval context) |

**Constraints:**

- `hit_rate` and `lifetime_hit_rate` are **nullable**. `null` means "no samples"
  and MUST NOT render as `0%`. A chart must break its line at a null, never plot
  it as zero.
- `samples: 0` with `current: null` is the cold-start state: an **empty** state,
  not an error state.
- The two collections do different jobs and MUST NOT be presented as
  interchangeable. A cache hit is a **prior answer** from `conversations`;
  retrieval is **supporting context** from `knowledge`. They use different
  thresholds by design.
- Similarity is comparable to the `0.95` cutoff **only in cosine space**. A
  non-cosine collection MUST be flagged as unscoreable — every score from it is
  meaningless. Unscoreable renders as the literal text "cannot be scored", never
  `0`, never `—`, never a hidden row.
- Each collection records the embedding model and dimension it was built with.
  Changing embedding models invalidates every vector in it; a mismatch between a
  collection's recorded model and the live one MUST be surfaced.
- An empty `knowledge` collection bounds retrieval quality — that is a fact the
  user needs, not an empty state to decorate.
- No pie chart for cache composition. Hit/miss over time is a line or stacked
  area; a single point in time is a stacked bar.

---

## Subtasks

### 107.1 — `/cache` page

- [ ] Stat tiles: current hit rate, lifetime hit rate, total keys, memory used,
      connected clients — each with provenance and freshness
- [ ] Hit-rate line chart over the window, **line broken at null samples**
- [ ] Hits vs misses over time as a stacked area (2 series → legend required)
- [ ] Window selector (minutes) in the filter row above the charts, state in URL
- [ ] Table twin for each chart
- [ ] Cold-start empty state: explains that no samples have been collected yet and
      when collection next runs

### 107.2 — Null and empty handling

- [ ] `null` rates render "no samples" everywhere they appear
- [ ] Charts break the line at nulls rather than plotting zero
- [ ] `samples: 0` renders the empty state, visually distinct from the panel error
      state
- [ ] A test fixture with interleaved nulls verifies the break, not just the tile

### 107.3 — `/collections` page

- [ ] One card per collection: name, id, document count, embedding model,
      dimension, distance space
- [ ] Role stated per collection — `conversations` serves cache hits (prior
      answers), `knowledge` serves retrieval context — so the two never read as
      interchangeable
- [ ] Gateway parameters shown in context: threshold `0.95`, top_k, TTL
- [ ] `ready: false` from `/ext/health` explains what is missing and the next step

### 107.4 — Trust flags

- [ ] **Non-cosine space:** prominent flag on that collection, stating that scores
      from it cannot be compared to the threshold
- [ ] **Model mismatch:** collection's recorded embedding model differs from the
      live one → flagged as stale vectors, naming re-embedding as the remedy
- [ ] **Empty collection:** stated plainly with its consequence for retrieval
- [ ] Each flag is status color **plus icon plus label**

### 107.5 — States and a11y

- [ ] Loading skeletons at fixed heights; panels fail independently
- [ ] Light and dark, all three breakpoints
- [ ] Keyboard reachable with visible focus rings; chart table twins announced

---

## Acceptance Criteria

- [ ] A `null` hit rate renders "no samples" and never `0%`
- [ ] A series containing nulls breaks the line; no null is plotted as zero
- [ ] `samples: 0` shows an empty state clearly distinct from an error state
- [ ] With Redis stopped, `/cache` shows a panel error naming Redis and one next
      step, and the rest of the page renders
- [ ] The two collections' distinct roles are stated on the page
- [ ] A collection with a non-cosine space is visibly flagged as unscoreable
- [ ] An unscoreable score renders "cannot be scored", never `0` and never hidden
- [ ] A model mismatch is surfaced with re-embedding named as the remedy
- [ ] An empty collection states its consequence for retrieval
- [ ] No pie chart; legend present for the 2-series chart; table twins present
- [ ] Every flag pairs color with an icon and a label
- [ ] Light and dark verified at all three breakpoints

---

## Implementation Notes

- **`null` is the whole ticket.** Coercing it to `0` turns "we have no idea" into
  "the cache is failing", which is a worse lie than showing nothing.
- **Why the collection roles must be spelled out:** the codebase keeps them
  separate precisely so a document chunk cannot clear the similarity threshold and
  be returned as an answer. A UI that blurs them reintroduces the failure the
  split prevents.
- **Cosine is not a detail.** Chroma defaults to `l2`, whose distances are
  unbounded and cannot be compared to `0.95`. The backend returns `None` for any
  non-cosine space rather than a meaningless number; render that refusal, don't
  paper over it.
- **Reuse BB-106's primitives.** If a chart need here cannot be met by them, extend
  the shared component — do not fork a second chart implementation.
