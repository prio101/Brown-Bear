# Feature: Overview Page

**Status:** Open
**Priority:** High — the dashboard's landing surface
**Points:** 2
**Branch:** `feat/bb-105-overview-page`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** BB-102 (tokens), BB-103 (API client)

---

## Overview

The `/` page: stack health, headline token numbers, gateway readiness, and the
liveness state of remote clients. This is where the PAIR rules bite hardest —
the page's job is to make "everything is fine" and "you have been silently
disconnected for two days" impossible to confuse.

---

## Context

**Reads required:** this file, plus `../design/DESIGN-BOOK.md` (normative spec).

| Fact | Value |
|---|---|
| Route | `/` in `jungle/web/` |
| Rendering | React server component, data fetched server-side from `http://app:8080` |
| Endpoints | `GET /api/info`, `GET /api/health`, `GET /api/system`, `GET /api/tokens/summary?period=day`, `GET /ext/health` |
| `/api/health` shape | `{healthy: bool, services: {[name]: {...}}}` |
| `/api/tokens/summary` shape | `{period, period_start, period_end, live, source, tokens_in, tokens_out, total_tokens, cost, currency, request_count}` |
| `/ext/health` shape | `{ready, collections: {conversations: {id, space}, knowledge: {id, space}}, embedding_model, threshold, top_k, ttl_days}` |
| Services monitored | ollama, chromadb, postgres, redis |
| Gateway defaults | threshold `0.95`, top_k `5`, ttl_days `30`, embedding `nomic-embed-text`, space `cosine` |

**Constraints:**

- Panels must fail independently. One dead connector never blanks the page.
- **Empty ≠ broken.** A zero token count on a quiet day and an unreachable
  collector are different states with different copy and different iconography.
- Every non-local number carries a provenance badge (`measured` / `reported` /
  `derived`) plus its freshness. `/api/tokens/summary` supplies `source` and
  `live` — map from them, don't guess.
- Remote clients report token usage voluntarily; a client can be configured with
  `BB_NO_STORE=1` or simply not run its hook. Totals that include reported data
  must say so.
- The client-side hooks **fail open**: an unreachable gateway, a wrong token, and
  a genuine no-match all produce silence. Absence of data is never evidence of
  health.
- A collection whose `space` is not `cosine` produces meaningless similarity
  scores and must be flagged, not rendered as if fine.
- No animated number counting. No dual-axis chart. No pie chart.

---

## Subtasks

### 105.1 — Page shell

- [ ] `/` route, server component, all five endpoint calls issued concurrently
- [ ] Responsive grid: 1 column compact, 2 medium, 4 expanded
- [ ] Navigation rail at medium+, bottom bar at compact, with the five
      destinations (overview, tokens, cache, collections, settings)

### 105.2 — Stat tiles

- [ ] Four tiles: total tokens today, cost today, request count, cache hit rate
- [ ] Each renders label, value, delta with an explicit comparison window, and a
      provenance badge with freshness
- [ ] `display-small` for the value, proportional figures (not tabular)
- [ ] A `null` rate renders as "no samples", never `0%`

### 105.3 — Service health panel

- [ ] One row per service from `/api/health.services`
- [ ] Status color **plus icon plus text label** — never color alone
- [ ] A degraded service names what is affected and one next step
- [ ] Panel-level error state when `/api/health` itself fails, distinct from
      "all services down"

### 105.4 — Gateway readiness panel

- [ ] `ready` state, embedding model, threshold, top_k, TTL from `/ext/health`
- [ ] Per-collection: name, id, distance space
- [ ] **Non-cosine space is flagged prominently** — every score from it is
      meaningless
- [ ] `ready: false` explains what is missing and what to do

### 105.5 — Liveness banner

- [ ] Persistent banner (not a snackbar) with four states: healthy (no banner),
      stale, unreachable, unknown
- [ ] States what is affected, when it last worked, and one next step
- [ ] Never dismissible into invisibility for an ongoing failure

### 105.6 — States

- [ ] Loading skeletons at fixed panel heights so nothing reflows
- [ ] Distinct empty and error states per panel, each naming one next action
- [ ] Verified in light and dark, at all three breakpoints

---

## Acceptance Criteria

- [ ] With every service healthy, the page shows no false alarm and no banner
- [ ] With Redis stopped, exactly one panel shows an error and the rest render
- [ ] With no token events, tiles show an empty state distinguishable at a glance
      from an error state
- [ ] Every non-local number displays provenance and freshness
- [ ] A `null` hit rate renders as "no samples", never `0%`
- [ ] A non-cosine collection is visibly flagged
- [ ] Status is never conveyed by color alone
- [ ] No layout shift between loading and loaded
- [ ] Keyboard navigation reaches every control with a visible focus ring
- [ ] Renders correctly in light and dark at compact, medium, and expanded
- [ ] No value outside the design tokens; no animated numbers

---

## Implementation Notes

- **The banner is the point of this page.** Everything else is a number; the
  banner is the only element that can tell the user the numbers are stale.
- **Freshness is not decoration.** "2 min ago" is what makes a zero interpretable.
- **Concurrent fetches:** five sequential server-side calls make the page as slow
  as their sum. Issue them together.
- **Cost is derived,** computed from a price table — never badge it `measured`.
