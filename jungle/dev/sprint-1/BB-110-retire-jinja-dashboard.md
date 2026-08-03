# Refactor: Retire the Jinja Dashboard

**Status:** Done — 2026-08-03, delivered notes in the commit message
**Priority:** Medium — closes the sprint; two dashboards drifting is the failure
this prevents
**Points:** 1
**Branch:** `refactor/bb-110-retire-jinja-ui`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** BB-104 — the edge must already serve all five pages from the
frontend
**Removes:** `brownbear/routers/ui.py`, `brownbear/templates/`, `brownbear/static/`,
the `jinja2` dependency, and the edge's `/static/` location

---

## Overview

Delete the server-rendered dashboard now that the Next.js frontend serves every
page it served. This is the deletion half of the port: leaving both alive means
two implementations of the same pages drifting apart, which is precisely the cost
the sprint was meant to remove.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Router to delete | `jungle/app/brownbear/routers/ui.py` — `APIRouter(include_in_schema=False)`, owns `/`, `/tokens`, `/cache`, `/collections`, `/settings` |
| Mounted in | `jungle/app/brownbear/main.py`, via `app.include_router(ui.router)` — **last**, with a comment noting the UI owns `/` |
| Templates to delete | `brownbear/templates/` — `base.html`, `overview.html`, `tokens.html`, `cache.html`, `collections.html`, `settings.html` |
| Static to delete | `brownbear/static/` — `app.css` (477 lines), `charts.js` (420 lines) |
| Static mount in `main.py` | `app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")` plus the `STATIC_DIR` constant |
| Dependency to drop | `jinja2>=3.1` in `jungle/app/pyproject.toml` |
| Edge location to delete | `location /static/` in `edge/nginx.conf.template` |
| Serving the pages now | `web:3000` (container `brownbear-web`), already proxied by the edge for `/`, `/tokens`, `/cache`, `/collections`, `/settings`, `/_next/` |

**Constraints:**

- **`charts.js` is the reference implementation for the chart layer.** Its header
  comment records why the charts are hand-rolled and what they guarantee. Do not
  delete it until the React port is merged and verified — and preserve the
  reasoning in the ported components or the Design Book, not only in git history.
- The design book route (`/design`) may live in the same app but is **independent**
  of the Jinja UI and must keep working. If it renders with inline CSS, it does not
  depend on `/static/`; confirm this rather than assuming.
- The `/static/` prefix and `/_next/` are different prefixes. Deleting the former
  must not touch the latter.
- Removing `jinja2` requires confirming nothing else imports it — FastAPI itself
  does not need it unless `Jinja2Templates` is used.
- API contracts are frozen; this ticket deletes UI only and changes no `/api/*`
  behaviour.

---

## Behaviour contract

Unchanged after this refactor:

- [ ] `/`, `/tokens`, `/cache`, `/collections`, `/settings` all still render —
      served by `web:3000`
- [ ] Every `/api/*` route returns the same shape and status codes
- [ ] `/ext/` and `/ollama/api/*` unchanged
- [ ] `GET /api/health/live` still public; `GET /design` still public
- [ ] Unauthenticated access to any guarded route still `401`; unnamed paths still
      `403`
- [ ] The app still starts with no template engine present

Deliberately changed:

- `GET /static/*` no longer exists (`403` from the default deny at the edge, `404`
  directly on the app).
- The app no longer serves HTML for the five page routes.

---

## Subtasks

### 110.1 — Confirm the replacement is complete

- [ ] All five routes render through the edge from `web:3000`, authenticated
- [ ] Screenshot each page in light and dark before deleting anything
- [ ] Confirm the React charts carry the table twins, `aria-label`s, fixed slot
      order, and broken-line-at-null behaviour of the originals

### 110.2 — Remove the UI router

- [ ] Delete `brownbear/routers/ui.py`
- [ ] Remove `ui` from the import list and the `include_router` call in `main.py`,
      including the "Last: the UI owns `/`" comment that no longer applies
- [ ] Remove the `StaticFiles` mount and the `STATIC_DIR` constant
- [ ] Remove the now-unused `StaticFiles` import

### 110.3 — Delete templates and static assets

- [ ] Delete `brownbear/templates/` entirely
- [ ] Delete `brownbear/static/` entirely
- [ ] Confirm the ported chart reasoning survives in the React components or the
      Design Book

### 110.4 — Drop the dependency

- [ ] Remove `jinja2>=3.1` from `pyproject.toml`
- [ ] `grep -rn "jinja2\|Jinja2Templates\|TemplateResponse" jungle/app/` returns
      nothing
- [ ] Rebuild the image and confirm the app starts

### 110.5 — Remove the edge location

- [ ] Delete `location /static/` from `edge/nginx.conf.template`
- [ ] Confirm `/_next/` is untouched
- [ ] `nginx -t`, then reload

### 110.6 — Verify

- [ ] `grep -rn "/static/" jungle/ edge/` returns no live reference
- [ ] `GET /static/app.css` through the edge → `403`
- [ ] All five pages still render; `/design` still renders
- [ ] Full test suite passes: `docker build --target dev -t brownbear-dev
      jungle/app && docker run --rm brownbear-dev`

---

## Migration & rollback

- **Lands as:** one commit — deletions only, after 110.1's verification.
- **Rollback:** `git revert` restores the files, but **the app image must be
  rebuilt** for the revert to take effect, so this is not revert-alone reversible.
- **Data:** none. No migration, no schema change, no volume touched.

---

## Acceptance Criteria

- [ ] Every line of the behaviour contract verified by request, not assumed
- [ ] `ui.py`, `templates/`, and `static/` are gone
- [ ] `jinja2` is absent from `pyproject.toml` and the built image
- [ ] `grep` for `jinja2`, `TemplateResponse`, and `/static/` finds no live
      reference — results recorded in the PR
- [ ] The edge no longer publishes `/static/`; `/_next/` still works
- [ ] All five pages and `/design` render through the edge
- [ ] Existing tests pass unmodified, or each change is justified as not a weakened
      assertion
- [ ] The app image is smaller than before

---

## Implementation Notes

- **Delete in this sprint, not "later".** Two dashboards serving the same data is
  the exact drift this port was meant to end, and a deferred deletion ticket is how
  that becomes permanent.
- **The comment in `main.py` matters.** `ui.router` is mounted last *because* it
  owns `/`; once it is gone the ordering constraint is gone too, and leaving the
  comment misleads the next reader.
- **`charts.js` earned its keep.** Its conventions are now the Design Book's §9.
  Deleting the file is fine; losing the reasoning is not.
- **Rebuild before declaring victory.** The Dockerfile copies `brownbear/` at build
  time, so a deleted file lingers in the running container until the image is
  rebuilt.
