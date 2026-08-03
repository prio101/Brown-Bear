# Sprint 1 — Next.js Frontend

**Goal:** replace the server-rendered Jinja dashboard with a Next.js application
built on the project design system, without changing a single API contract.

**Capacity:** 20 points
**Committed:** 20 points across 10 tickets
**Date opened:** 2026-08-03
**Design authority:** [`../design/DESIGN-BOOK.md`](../design/DESIGN-BOOK.md) —
normative. [`../design/DESIGN-GUIDE.md`](../design/DESIGN-GUIDE.md) — principles.

---

## Why this sprint

The current dashboard is Jinja templates plus two hand-written static files
(`app.css`, `charts.js`). It works, and its chart layer is genuinely good — a
validated palette, table twins, no library. What it cannot do is grow: no
component model, no type safety against the API, no shared state, and every new
panel is copied HTML.

This sprint ports the dashboard to Next.js and keeps everything that was right.
Explicitly **not** in scope: changing any API response, adding a write path, or
redesigning the charts.

---

## Ticket index

| ID | Title | Type | Pts | Branch |
|---|---|---|---|---|
| [BB-101](BB-101-nextjs-app-scaffold.md) | Next.js app scaffold + container | feature | 3 | `feat/bb-101-nextjs-scaffold` |
| [BB-102](BB-102-design-system-foundation.md) | Design system foundation (M3 tokens) | feature | 3 | `feat/bb-102-design-tokens` |
| [BB-103](BB-103-typed-api-client.md) | Typed API client + data layer | feature | 2 | `feat/bb-103-api-client` |
| [BB-104](BB-104-edge-frontend-routes.md) | Edge routes for the frontend | refactor | 1 | `refactor/bb-104-edge-frontend-routes` |
| [BB-105](BB-105-overview-page.md) | Overview page | feature | 2 | `feat/bb-105-overview-page` |
| [BB-106](BB-106-token-analytics-page.md) | Token analytics page + charts | feature | 3 | `feat/bb-106-token-analytics` |
| [BB-107](BB-107-cache-collections-pages.md) | Cache + Collections pages | feature | 2 | `feat/bb-107-cache-collections` |
| [BB-108](BB-108-settings-page.md) | Settings page (read-only) | feature | 1 | `feat/bb-108-settings-page` |
| [BB-109](BB-109-design-book-public-view.md) | Design Book public view — **done** | feature | 2 | `feat/bb-109-design-book-public` |
| [BB-110](BB-110-retire-jinja-dashboard.md) | Retire the Jinja dashboard | refactor | 1 | `refactor/bb-110-retire-jinja-ui` |

**Total: 20 points.**

Templates used: features → [`../features/TEMPLATE.md`](../features/TEMPLATE.md);
refactors → [`../refactors/TEMPLATE.md`](../refactors/TEMPLATE.md). A bug template
exists at [`../bugs/TEMPLATE.md`](../bugs/TEMPLATE.md) for anything this sprint
uncovers.

---

## Dependency graph

```
BB-101 scaffold ──┬─► BB-102 tokens ──┬─► BB-105 overview ──┐
                  │                   ├─► BB-106 tokens ────┤
                  └─► BB-103 client ──┼─► BB-107 cache+coll ├─► BB-104 edge ─► BB-110 retire
                                      └─► BB-108 settings ──┘

BB-109 design book ── independent (app-side only, no frontend dependency)
```

**Critical path:** BB-101 → BB-102/103 → BB-106 (the heaviest page) → BB-104 →
BB-110. BB-109 can be worked at any point by anyone blocked.

**BB-104 must land after all four page tickets.** It repoints `/` and the four
page routes from the FastAPI app to `web:3000`; landing it earlier points the
live dashboard at routes that do not exist yet and 502s it for everyone. BB-107
also depends on BB-106 for the shared chart primitives.

---

## Ticket self-containment rule

Every ticket in this sprint carries a **Context** section holding every fact
needed to execute it: ports, endpoints, response shapes, auth headers, file
paths. The rule is deliberate:

> A competent implementer — human or LLM — opens one ticket file and nothing
> else, and can finish the work.

No ticket says "see BB-102 for the tokens" or "as described in spec 005". Facts
are inlined and duplicated across tickets on purpose. The cost is that a changed
fact must be updated in several files; the benefit is that no ticket requires
loading the sprint's history to start. Each ticket states **Reads required:** at
the top of its Context block — where that says "this file only", it is a promise,
and a reviewer should reject a ticket that breaks it.

The one intended exception: the Design Book is normative and referenced by path,
not inlined. It is a specification, not sprint context.

---

## Architecture decisions for this sprint

**D1 — Server-side data fetching.** Pages fetch from `http://app:8080` inside the
Docker network via React server components. No API credentials ever reach the
browser, and the frontend needs no token handling at all.

**D2 — The edge keeps owning authentication.** The Next.js app gains no auth code.
`brownbear-edge` already authenticates every route it publishes; the frontend
sits behind it unchanged. One boundary, not two.

**D3 — The chart layer is ported, not redesigned.** `charts.js` conventions
(fixed slot order, table twins, text never wearing a series color) move into
React components with the same output. The palette is already validated; a
redesign would need re-validation for no gain.

**D4 — API contracts are frozen.** This sprint reads `/api/*` and changes nothing
about it. Any endpoint that turns out to be inadequate gets a follow-up ticket,
not an in-sprint edit.

**D5 — The public Design Book is served by the app, not by Next.js.** Serving it
from Next.js would require making `/_next/static/*` publicly reachable, which
publishes the whole application bundle to reach one docs page. A self-contained
HTML route on the FastAPI app keeps the public surface to exactly two paths.

---

## Definition of done

- [ ] All 10 tickets closed, each against its own branch
- [ ] `docker compose up -d` brings up the frontend with no manual steps
- [ ] Every page renders in light and dark, at compact / medium / expanded
- [ ] Design Book §13 conformance checklist passes per page
- [ ] The Jinja dashboard, its templates, and `jinja2` are gone (BB-110)
- [ ] No API response shape changed — verified by diffing responses pre/post
- [ ] The edge still default-denies everything not explicitly allowlisted

---

## Risks

| Risk | Mitigation |
|---|---|
| Chart port loses a11y properties silently | BB-106 acceptance requires the table twin and `aria-label` per chart, checked explicitly |
| A second public route widens the attack surface | BB-109 publishes static docs only, no app data; reviewed as a security change |
| Frontend and Jinja UI both live, drifting | BB-110 deletes the old one in the same sprint; not deferred |
| M3 theme generation adds build complexity | Tokens generated once into CSS custom properties at build, not at runtime |
| Node image inflates the stack's footprint | Multi-stage build, `output: "standalone"`, alpine base |
