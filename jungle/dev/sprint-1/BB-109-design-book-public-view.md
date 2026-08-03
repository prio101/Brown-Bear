# Feature: Design Book Public View

**Status:** Done — 2026-08-03, see *Delivered* at the end
**Priority:** Medium — unblocks external and LLM consumers of the design system
**Points:** 2
**Branch:** `feat/bb-109-design-book-public`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** nothing — app-side only, no frontend dependency

---

## Overview

Publish the Design Book and Design Guide as a public, unauthenticated view served
by the FastAPI app: a readable HTML page for humans and raw Markdown for LLM
consumers. This is the second public route the stack has ever had, so the ticket
is as much a security change as a feature.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Source documents | `jungle/dev/design/DESIGN-BOOK.md`, `jungle/dev/design/DESIGN-GUIDE.md` |
| Serving app | FastAPI, container `brownbear-app`, port `8080`, built from `./jungle/app` with `target: runtime` |
| App Dockerfile | `jungle/app/Dockerfile` — copies `alembic.ini`, `alembic/`, and `brownbear/` only |
| Router pattern | routers live in `jungle/app/brownbear/routers/`, mounted in `brownbear/main.py` via `app.include_router(...)` |
| Router prefixes in use | `/api` (health, monitoring, export), `/api/tokens`, `/api/settings`, `/ext`, `/ollama`, and `ui.py` which owns `/` |
| Edge config | `edge/nginx.conf.template` (envsubst template, rendered at container start) |
| Only existing public route | `location = /api/health/live` — deliberately unauthenticated for external monitors |
| Edge default | `location /` returns `403` — anything not allowlisted does not exist remotely |

**New routes:**

| Route | Auth | Content type |
|---|---|---|
| `GET /design` | **public** | `text/html` — self-contained page, book + guide |
| `GET /design/design-book.md` | **public** | `text/markdown` — raw, for LLM consumers |
| `GET /design/design-guide.md` | **public** | `text/markdown` — raw |

**Constraints:**

- **Self-contained HTML only.** No `/_next/` assets, no external stylesheet, no
  CDN font, no script. Serving this page from the Next.js frontend would require
  publishing `/_next/static/*` unauthenticated, which exposes the entire
  application bundle to reach one docs page. That is why this lives on the app.
- **Static documentation only.** This route MUST NOT read the database, the
  gateway, ChromaDB, Redis, or any setting. It renders two files from the image and
  nothing else.
- **No secrets, no operational data.** The documents contain design values only.
  Verify before publishing — a design doc that grows a hostname or a token later
  becomes a leak through this route.
- The route must be **GET-only** and method-pinned at the edge.
- The app image copies only `brownbear/`, so the documents must be brought inside
  that tree at build time; a runtime path into the repo does not exist in the
  container.
- The `markdown` renderer is a new dependency; keep it to one, with no plugins
  that execute embedded content.

---

## Subtasks

### 109.1 — Get the documents into the image

- [ ] Build step copying `jungle/dev/design/*.md` into
      `jungle/app/brownbear/design/` so the existing `COPY brownbear ./brownbear`
      picks them up
- [ ] The copy is part of the build, not a committed duplicate — a stale published
      book is worse than none
- [ ] Document the mechanism in the Dockerfile with a comment saying why

### 109.2 — Renderer

- [ ] Add `markdown` to `jungle/app/pyproject.toml` dependencies
- [ ] `brownbear/routers/design.py` with `APIRouter(prefix="/design")`
- [ ] Render Markdown → HTML **once at startup**, cache in memory; these files do
      not change at runtime
- [ ] Enable table and fenced-code extensions; enable no extension that executes or
      includes external content
- [ ] Mount in `main.py` **before** `ui.router`, which owns `/`

### 109.3 — The page

- [ ] One self-contained HTML document: inline `<style>`, no external requests
- [ ] Styled from the Design Book's own tokens — the page demonstrates the system
      it documents
- [ ] Light and dark via `prefers-color-scheme`, using the book's fixed surfaces
- [ ] Sticky table of contents from the headings; anchor links per heading
- [ ] Wide content (tables, code blocks) scrolls inside its own container; the page
      body never scrolls horizontally
- [ ] Prominent links to the raw Markdown for machine consumers

### 109.4 — Raw Markdown routes

- [ ] `GET /design/design-book.md` and `/design/design-guide.md`
- [ ] `Content-Type: text/markdown; charset=utf-8`
- [ ] Byte-identical to the source files — no rewriting, no wrapping

### 109.5 — Edge exposure

- [ ] New **public** location in `edge/nginx.conf.template`:
      `location /design` → `app:8080/design`, `limit_except GET { deny all; }`,
      no `$bb_auth` guard, default timeout include
- [ ] Placed beside `= /api/health/live` with a comment saying why it is public
- [ ] Confirm the default-deny `location /` still catches everything else

### 109.6 — Security verification

- [ ] `curl` the route with **no credentials** → `200`
- [ ] `POST /design` → `403` (nginx `limit_except … deny all` denies at the edge
      rather than passing through for FastAPI to answer `405`; this matches every
      other method-pinned route in the config)
- [ ] Confirm the rendered HTML contains no token, hostname, or operational value
- [ ] Confirm the route makes no database, Redis, Chroma, or Ollama call — check
      with the stack's dependencies stopped: the page must still render
- [ ] Confirm no other path became reachable: re-test `PUT /api/settings` → `403`,
      `GET /metrics` → `403`, `GET /` unauthenticated → `401`

---

## Acceptance Criteria

- [ ] `GET /design` returns a complete styled page with **no credentials**
- [ ] The page makes zero external requests — verified with the network panel
- [ ] Both raw Markdown routes return the source byte-for-byte as
      `text/markdown`
- [ ] The page renders with Postgres, Redis, ChromaDB and Ollama all stopped
- [ ] `POST /design` → `403`; every other denied route still `403`/`401`
- [ ] No secret, hostname, or operational value appears in the output
- [ ] Light and dark both render; no horizontal body scroll at 360px width
- [ ] Rebuilding the image picks up an edited design document
- [ ] The `/_next/` prefix was **not** made public

---

## Implementation Notes

- **Why the app and not the frontend:** one docs page is not worth publishing an
  application bundle. Keeping the public surface at exactly two paths —
  `/api/health/live` and `/design` — keeps it auditable in a glance.
- **Render at startup, not per request.** The files are immutable in the image;
  per-request Markdown rendering is unauthenticated CPU a stranger can spend.
- **This is a security-relevant change.** Diff the rendered edge config before and
  after and confirm the only new location is the intended public one.
- **The no-backend-calls rule is testable and worth testing** — stop the
  dependencies and load the page. It also means this route cannot be used to probe
  whether the stack is alive, which `/api/health/live` already answers on purpose.

---

## Delivered — 2026-08-03

**Files:** `jungle/app/brownbear/routers/design.py` (new),
`jungle/app/tests/test_design.py` (new), `brownbear/main.py`,
`brownbear/config.py`, `jungle/app/pyproject.toml`, `compose.yaml`,
`edge/nginx.conf.template`.

**Live at** `https://<tunnel>/design`, `/design/design-book.md`,
`/design/design-guide.md` — all three `200` with no credentials. Tests: 102 pass
(92 pre-existing + 10 new).

**Four deviations from the plan above, each deliberate:**

1. **§109.1 — read-only bind mount, not a build-time copy.** The build context is
   `./jungle/app`, so a Dockerfile `COPY` cannot reach `../dev/design` without
   moving the context to the repo root and rewriting every existing path. Mounting
   `./jungle/dev/design:/app/brownbear/design:ro` is simpler *and* better on the
   ticket's own terms: an edited document publishes with no rebuild, so the
   published book cannot go stale. Path is overridable via `BB_DESIGN_DIR`; a
   missing mount degrades to 404 and is covered by a test.
2. **§109.2 — rendered on first request, cached, not at startup.** `lru_cache`
   gives the same "render once" property without coupling the route to the app
   lifespan. Unauthenticated per-request Markdown rendering was the actual concern,
   and it is closed.
3. **Edge uses two locations, not one.** `location = /design` plus `location
   /design/`. A bare `location /design` would also match `/designfoo`, which
   belongs in the default deny — verified: `/designfoo` → `403`.
4. **Tests added** beyond the subtask list, pinning the properties that make
   public exposure safe: the fixed slug allowlist (a stray `SECRETS.md` in the
   mount → 404), byte-identical raw output, path traversal unreachable, missing
   mount degrading to 404, and — structurally — that the module imports nothing but
   `brownbear.config`, which is how "renders with every service stopped" is
   guaranteed rather than hoped for.

**One defect found and fixed during implementation.** Both documents cross-link
each other as `[DESIGN-GUIDE.md](DESIGN-GUIDE.md)` — correct in the repo, dead on
the rendered page, where it resolves to `/DESIGN-GUIDE.md` and hits the default
deny. Both are rendered into one page, so those hrefs are rewritten to the in-page
anchors (`#design-book`, `#design-guide`). Heading ids are namespaced per document
for the same reason: both files have an `## Overview`, and unprefixed anchors would
have pointed the guide's TOC at the book's headings.

**Operational note.** Editing `edge/nginx.conf.template` invalidated Docker
Desktop's WSL bind-mount staging path, so `docker compose restart edge` failed with
an `OCI runtime create` mount error and left the edge down. `docker compose up -d
--force-recreate edge` fixed it. On this host, **edit the template then
force-recreate — never restart.**
