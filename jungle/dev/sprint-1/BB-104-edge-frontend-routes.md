# Refactor: Edge Routes for the Frontend

**Status:** Done — 2026-08-03, delivered notes in the commit message
**Priority:** High — without it the new frontend is unreachable through the tunnel
**Points:** 1
**Branch:** `refactor/bb-104-edge-frontend-routes`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** BB-105, BB-106, BB-107, BB-108 — all five page routes must exist
before `/` is repointed, or the dashboard 502s for everyone

---

## Overview

Repoint the edge's HTML page routes from the FastAPI app to the Next.js service,
and add the asset prefix the framework needs. Authentication, the default-deny
posture, and every API route stay exactly as they are — this ticket moves an
origin, nothing else.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Edge config | `edge/nginx.conf.template` (an **envsubst template**, rendered by the nginx image into `/etc/nginx/conf.d/` at startup) |
| Edge service | `edge`, container `brownbear-edge`, listening `8081`, published `127.0.0.1:8081` |
| Frontend origin | `http://web:3000` (container `brownbear-web`) |
| Backend origin | `http://app:8080` (container `brownbear-app`) |
| Auth | one shared secret, accepted as `Authorization: Bearer $BB_EDGE_TOKEN` or `Basic $BB_EDGE_BASIC` (user `bb`); both from `.env` |
| Include files | `proxy_common.conf`, `proxy_timeouts.conf`, `proxy_timeouts_long.conf` — nginx rejects duplicate directives in one context, so each location includes exactly one timeout file |
| Auth variable | `$bb_auth` — `1` when authenticated; each guarded location does `error_page 401 = @unauthorized;` then `if ($bb_auth = 0) { return 401; }` |

**Routes moving from `app:8080` to `web:3000`:**

| Location | Current target | New target |
|---|---|---|
| `= /` | `app:8080/` | `web:3000` |
| `~ ^/(tokens\|cache\|collections\|settings)$` | `app:8080$uri` | `web:3000$uri` |

**New location required:** `/_next/` → `web:3000` (authenticated, GET only). The
framework serves its bundles and chunks from this prefix; without it every page
renders unstyled and inert.

**Constraints:**

- The edge **default-denies**: `location /` returns 403 for anything not
  explicitly allowlisted. A route that is not named does not exist remotely.
- Both `BB_EDGE_TOKEN` and `BB_EDGE_BASIC` render as empty when unset, which the
  config deliberately turns into "reject everyone". Do not weaken that guard.
- `map_hash_bucket_size 256;` is required — the credential strings exceed nginx's
  default 64-byte bucket and it refuses to start rather than truncating.
- `/api/health/live` is the only intentionally unauthenticated route. This ticket
  adds no public route.
- The `/static/` location still serves the Jinja dashboard's CSS and JS. Leave it
  alone; removing it belongs to BB-110.

---

## Behaviour contract

Unchanged after this refactor:

- [ ] `GET /api/health/live` remains reachable **without** credentials
- [ ] Every `/api/*` read route returns the same shape, status codes, and method
      restrictions, still served by `app:8080`
- [ ] `/ext/` still proxies to `app:8080` with the long timeout set
- [ ] `/ollama/api/{chat,generate,embed,tags}` unchanged, still method-pinned
- [ ] `PUT /api/settings`, `POST /api/tokens/aggregate`, `/metrics` and every
      Ollama model-management route still fall through to the 403 default deny
- [ ] Unauthenticated requests to any guarded route still return `401` with a
      `WWW-Authenticate: Basic` header, so browsers still prompt
- [ ] An unset `BB_EDGE_TOKEN` still rejects every authenticated route

Deliberately changed:

- The five HTML page routes are served by `web:3000` instead of `app:8080`.
- `/_next/` is newly published (authenticated, GET only).

---

## Subtasks

### 104.1 — Repoint the page routes

- [ ] `location = /` → `proxy_pass http://web:3000;`
- [ ] `location ~ ^/(tokens|cache|collections|settings)$` → `proxy_pass
      http://web:3000$uri;`
- [ ] Keep `limit_except GET { deny all; }` and the `$bb_auth` guard on both
- [ ] Keep `include /etc/nginx/proxy_timeouts.conf;` (default, not long)

### 104.2 — Add the asset prefix

- [ ] New `location /_next/` → `web:3000`, authenticated, `limit_except GET`
- [ ] Default timeout include

### 104.3 — Verify the contract

- [ ] `docker compose exec edge nginx -t` passes before reload
- [ ] Unauthenticated `GET /` → `401` with `WWW-Authenticate`
- [ ] Authenticated `GET /` → the Next.js page, fully styled
- [ ] Unauthenticated `GET /api/health/live` → `200`
- [ ] `PUT /api/settings` → `403`
- [ ] `POST /api/tokens/aggregate` → `403`
- [ ] `GET /metrics` → `403`
- [ ] `GET /ollama/api/tags` authenticated → `200`; `POST` to it → `403`
      (`limit_except … deny all` denies at the edge; it never reaches FastAPI to
      become a `405` — verified 2026-08-03)
- [ ] With `BB_EDGE_TOKEN` unset, every guarded route → `401`

---

## Migration & rollback

- **Lands as:** one commit touching only `edge/nginx.conf.template`.
- **Rollback:** `git revert` plus `docker compose up -d edge`. Fully reversible —
  no data, no migration, no image rebuild.
- **Ordering:** must land **after** the four page tickets. Landing it early points
  `/` at routes that do not exist yet.

---

## Acceptance Criteria

- [ ] Every line of the behaviour contract verified by an actual request, not
      assumed
- [ ] `nginx -t` passes
- [ ] The frontend renders through the edge with assets loading
- [ ] No new public route was added
- [ ] `/static/` still resolves (BB-110 removes it)
- [ ] The default-deny `location /` still returns 403 for an unnamed path

---

## Implementation Notes

- **It is a template, not a conf.** Edits go to `edge/nginx.conf.template`;
  editing the rendered file inside the container is lost on restart.
- **`/_next/` cannot be folded into `/static/`.** The prefix is framework-fixed.
- **Trailing slashes change semantics.** `proxy_pass http://web:3000;` and
  `.../;` differ in what gets appended. Verify a nested asset path resolves, not
  just `/`.
- **One timeout include per location.** Adding a second is an nginx startup
  failure, not a warning.
- **This is a security-relevant file.** Diff the rendered config before and after
  (`docker compose exec edge cat /etc/nginx/conf.d/default.conf`) and confirm the
  only differences are the intended ones.
