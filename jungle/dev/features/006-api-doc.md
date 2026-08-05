# Feature: API Documentation at /api-doc/v1

**Status:** Done — 2026-08-06, see *Delivered* at the end
**Priority:** Medium — the `/ext/*` contract is what remote clients are written against, and it is currently documented only in prose in `REMOTE-SETUP.md`
**Points:** 3
**Branch:** `feat/006-api-doc`
**Date:** 2026-08-06

---

## Overview

Serve the HTTP API contract at `/api-doc/v1`: a readable page for humans and the
raw OpenAPI schema for machines. Generated from the app's own route definitions so
it cannot drift from the code.

The point is not to restate FastAPI's schema — that already exists at
`/openapi.json`. It is to document **what is actually reachable through the
tunnel**, which the schema gets wrong.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Serving app | FastAPI, container `brownbear-app`, port `8080` |
| Router pattern | `jungle/app/brownbear/routers/`, mounted in `brownbear/main.py` |
| Existing schema | `GET /openapi.json` — live, 23 paths, title "Brown Bear", version `0.1.0` |
| Built-in docs | `/docs` and `/redoc` exist and answer `200` locally, `403` through the edge |
| Edge config | `edge/nginx.conf.template` — envsubst template, default-deny |
| Existing public routes | `/api/health/live` and `/design` only |
| Auth at the edge | `Authorization: Bearer $BB_EDGE_TOKEN`, or Basic as user `bb` |

**Two facts that shape the whole design:**

1. **FastAPI's `/docs` requires the internet.** It loads Swagger UI from
   `cdn.jsdelivr.net` and a favicon from `fastapi.tiangolo.com`. This stack is
   meant to run on a machine with no internet, so `/docs` renders a blank page
   exactly when it is most needed. Exposing it is not an option; the page must be
   self-contained, like `/design` (BB-109).

2. **The OpenAPI schema overstates the remote surface.** It advertises
   `PUT /api/settings`, `POST /api/tokens/aggregate`, `GET /metrics` and a
   catch-all `/ollama/{path}` accepting all seven methods. The edge denies every
   one of those except four named Ollama routes. A client developer reading the
   schema would write code against endpoints that return `403` through the tunnel.
   **Documenting the edge-enforced contract is the feature.**

---

## Decisions (locked)

| Decision | Choice | Consequence |
|---|---|---|
| Rendering | **Hand-rendered, self-contained HTML** | No CDN, no script, works offline; we own the layout |
| Audience | **Authenticated, not public** | Unlike `/design`, this enumerates the attack surface. The people who need it hold the token |
| Scope | **The edge contract, not the app's routes** | Requires a reachability annotation per endpoint, and something to stop it drifting |
| Path | **`/api-doc/v1`** | The version is the *contract's*, not the app's. `v1` changes when a published endpoint changes shape |

### Reachability must not drift

The annotation (public / authenticated / denied) is a second source of truth
beside `edge/nginx.conf.template`, and a second source of truth rots. So it is
declared once in Python **and a test parses the edge template and asserts the two
agree**. A route added to the edge without being documented, or documented without
being published, fails the suite.

---

## Requirements

### The page

- Self-contained: no external stylesheet, script, font or image
- Styled from the Design Book's tokens, light and dark
- Every endpoint shows: method, path, summary, and **reachability through the
  tunnel**
- Denied endpoints are listed and marked denied rather than omitted — a reader
  needs to know `PUT /api/settings` exists and is deliberately unreachable
- Grouped by concern (gateway, tokens, monitoring, docs, proxy), not alphabetically
- Auth requirements stated once, prominently, with a copy-pasteable example

### The schema

- `GET /api-doc/v1/openapi.json` returns the app's OpenAPI document
- Annotated with reachability so a machine consumer sees the same contract the
  page shows

### Constraints

- MUST NOT read the database, gateway, Redis or Chroma — the doc is static and
  must serve when the stack is degraded
- MUST NOT expose a secret; the auth section names the header, never a value
- Rendered once and cached: this is immutable per build
- GET only, method-pinned at the edge

---

## Subtasks

### 6.1 — Reachability model

- [ ] `EDGE_ROUTES` table: path pattern → `public` | `authenticated` | `denied`,
      with the allowed methods
- [ ] Group and summary metadata per endpoint
- [ ] Helper resolving an OpenAPI path to its reachability

### 6.2 — The router

- [ ] `brownbear/routers/api_doc.py`, `APIRouter(prefix="/api-doc/v1")`
- [ ] `GET ""` → self-contained HTML, rendered once and cached
- [ ] `GET "/openapi.json"` → the annotated schema
- [ ] Mounted in `main.py`
- [ ] No import of db, connectors or settings_store

### 6.3 — The page

- [ ] Grouped endpoint tables with reachability chips (colour **plus** label)
- [ ] Auth section with a working `curl` example
- [ ] Sticky table of contents; wide tables scroll in their own container
- [ ] Light and dark via `prefers-color-scheme`

### 6.4 — Edge exposure

- [ ] `location /api-doc/` → `app:8080/api-doc/`, authenticated, `limit_except GET`
- [ ] Placed with the other authenticated routes, not beside the public ones

### 6.5 — Drift protection

- [ ] Test parsing `edge/nginx.conf.template` for every `location` and its
      `limit_except`, asserting `EDGE_ROUTES` agrees
- [ ] Test that every OpenAPI path resolves to a reachability entry — a new route
      cannot land undocumented
- [ ] Test that the page names no secret

---

## Acceptance Criteria

- [ ] `GET /api-doc/v1` returns a complete styled page, authenticated, and `401`
      without credentials
- [ ] The page makes zero external requests
- [ ] It renders with Postgres, Redis, ChromaDB and Ollama stopped
- [ ] Every one of the 23 OpenAPI paths appears, each with its reachability
- [ ] `PUT /api/settings`, `POST /api/tokens/aggregate` and `GET /metrics` are
      shown as **denied**, not omitted
- [ ] The `/ollama/{path}` catch-all is documented as the four named routes the
      edge actually publishes
- [ ] `GET /api-doc/v1/openapi.json` returns valid JSON with the annotation
- [ ] `POST /api-doc/v1` → denied at the edge
- [ ] Adding an edge location without documenting it fails the test suite
- [ ] No secret appears in the output

---

## Implementation Notes

- **Do not expose `/docs` or `/redoc` instead.** They need a CDN, and this stack
  is built for a machine with no internet. That is the whole reason for a
  hand-rendered page.
- **The drift test is the load-bearing part.** Without it this becomes a document
  that describes an older edge config, which is worse than no document because it
  is trusted.
- **Authenticated, deliberately.** `/design` is public because design tokens
  describe nobody's attack surface. An endpoint inventory does. Keeping the public
  surface at two paths keeps it auditable at a glance.
- **`/ollama/{path}` needs special handling.** FastAPI reports one catch-all path
  with seven methods; the edge publishes four specific routes. Rendering the
  catch-all verbatim would be the single most misleading line on the page.

---

## Delivered — 2026-08-06

**Files:** `brownbear/api_contract.py` (new), `brownbear/routers/api_doc.py` (new),
`scripts/check_edge_contract.py` (new), `tests/test_api_doc.py` (new),
`brownbear/main.py`, `edge/nginx.conf.template`.

**Live at** `GET /api-doc/v1` and `/api-doc/v1/openapi.json` — `200` authenticated,
`401` without credentials, `403` on `POST`. Nothing else changed:
`/api/health/live` and `/design` still public, `/` still `401`, `/metrics`,
`/docs` and `PUT /api/settings` still `403`.

**The page** renders 30 endpoints in 8 groups: 3 public, 22 token-required,
5 denied. 14KB, zero `<script>`, `<link>` or `<img>`, no CDN — the only `https://`
in the output is the placeholder in the `curl` example. No secret: it names
`$BB_EDGE_TOKEN` as a variable and never a value.

**The `/ollama/{path}` catch-all is expanded, not copied.** FastAPI advertises one
path accepting seven methods; the page documents the four the edge publishes plus
`pull` marked denied, and a test asserts the expansion exists.

**Denied routes are listed, not omitted.** `PUT /api/settings`,
`POST /api/tokens/aggregate`, `GET /metrics`, `GET /api/metrics` and
`POST /ollama/api/pull` all appear, struck through and labelled. Omitting them
would read as an oversight and invite someone to try.

**Drift protection works in both directions — verified.**
`scripts/check_edge_contract.py` parses the edge template's 16 locations, derives
reachability with nginx's matching order (exact, then regex in order, then longest
prefix, then the method pin), and compares. Clean: *all 30 declared endpoints agree
with the edge config*, exit 0. Negative control: declaring `/metrics` public and
`/ext/context` public produced two `DRIFT` lines and exit 1.

**Why the drift check is a script, not a pytest case.** The test image is built
from `jungle/app`, and Docker cannot COPY `edge/nginx.conf.template` from outside
that build context. A test that skipped when the file was absent would never run in
the only place tests do run, which is worse than no test because it looks like
coverage. The suite keeps what it can enforce: that every served route is declared
(19 tests), that the page is inert and self-contained, and that it leaks nothing.

Tests: 157 pass, up from 138.

### Two notes for the next person

- **`Reach.PUBLIC` and `Reach.DENIED` are both six characters.** While testing the
  negative control I hit a stale `__pycache__`: the edited and restored files had
  identical sizes, and CPython validates bytecode on size plus mtime, so it served
  the old `.pyc` and the script reported drift that no longer existed. If a check
  disagrees with what you can read in the source, clear `__pycache__` before
  believing it.
- **`/docs` and `/redoc` are still mounted** and still answer `200` on the host.
  They are `403` through the edge, so they are not a remote exposure, but they are a
  second, CDN-dependent answer to the same question. Worth deciding whether to
  disable them (`docs_url=None`) so there is one API doc rather than three.
