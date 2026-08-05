# Bug: The dashboard never updates, and claims to be current while not updating

**Status:** Fixed — 2026-08-06 via option A, see *Resolution* at the end
**Severity:** High — an operations dashboard that silently shows stale data as current is worse than one that shows nothing
**Points:** 3
**Branch:** `fix/bb-203-realtime-updates`
**Date:** 2026-08-06

---

## Symptom

The dashboard does not update in realtime. Numbers sit frozen until the page is
reloaded by hand.

```
Leave / open for an hour:
  "Tokens today"     unchanged, though the remote client kept reporting
  "Cache hit rate"   unchanged, though Redis kept serving
  provenance badge   still reads "● measured · just now"   <-- the actual bug
```

Always, on every page.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Pages | `/`, `/tokens`, `/cache`, `/collections`, `/settings` in `jungle/web/` |
| Rendering | React server components; `fetch` with `cache: "no-store"` |
| Refresh mechanism | **none** — verified: no `revalidate`, `setInterval`, `EventSource`, `WebSocket`, `router.refresh` or polling anywhere in `src/` |
| Freshness display | `relativeAge()` in `ProvenanceBadge` and `Panel`, both **server-rendered** |
| Server sampling rate | 30s (`BB_SNAPSHOT_INTERVAL_SECONDS`, `BB_CACHE_SAMPLE_INTERVAL_SECONDS`) |
| Data fetching | server-side against `app:8080`; the browser holds no API credential (sprint-1 D1) |

---

## Reproduction

1. Open `/` through the edge.
2. Generate activity — run a few `/ext/context` calls, or use Claude Code from a
   client machine.
3. Watch the page. Nothing changes.
4. Leave it open for ten minutes and read the provenance badge: still "just now".
5. Reload. The numbers jump to current.

**Expected:** either the page updates, or it is visibly honest about being a
snapshot.
**Actual:** the page is a snapshot that asserts it is live.

---

## Root cause

Two distinct faults, and the second is the one that makes this a bug rather than a
missing feature.

**1. No refresh mechanism was ever built.** Every page is a server component with
`cache: "no-store"`. That makes the data fresh *at the moment of the request* and
does nothing whatever afterwards — `no-store` prevents a stale cache, it does not
cause a re-fetch. There is no polling, no SSE, no websocket, no revalidation
interval. This is a gap in the sprint, not a regression: BB-105 through BB-108
specified per-panel loading, empty and error states and never specified what
happens on the *second* tick. Nothing in the acceptance criteria caught it,
because every check was "does it render", and it does.

**2. The freshness badge lies, which the design system explicitly forbids.**
`relativeAge(fetchedAt)` is evaluated once, server-side, during render. The string
"just now" is then baked into the HTML and never recomputed. An hour later the
badge still says "just now" about data an hour old.

This is a direct violation of the project's own rule. `DESIGN-BOOK.md` §10.1
requires every non-local number to carry its freshness, and BB-105's own
implementation note says why:

> "Freshness is not decoration. '2 min ago' is what makes a zero interpretable."

A frozen "just now" does the opposite of that: it takes the one element whose job
is to let a reader detect staleness and makes it assert the opposite. It is worse
than showing no age at all, because a missing badge invites a reload while a
confident one suppresses it. This is the same class of failure as
`DESIGN-GUIDE.md`'s "distinguish nothing-to-show from not-working" — a display
that cannot express a state it can be in.

**Note the ordering.** Fault 2 is independently worth fixing even if realtime
updates are never built, and it is the cheaper of the two. A page that refreshes
every 30s but still hard-codes "just now" between refreshes remains wrong for 29
of every 30 seconds.

---

## Fix

Four options for fault 1. Fault 2 is fixed in all of them and is not optional.

- [ ] **A — `router.refresh()` on an interval (recommended).** A small client
      component calls Next's `router.refresh()` every 30s, which re-runs the
      server components and streams fresh markup in. No new endpoint, no edge
      change, no API credential in the browser, and the entire existing data
      layer is reused unchanged. Matches the server sampling rate, so it cannot
      poll faster than the data can change.
- [ ] **B — Client-side polling of `/api/*`.** The browser already holds Basic
      credentials for page access, so it *could* fetch directly. Rejected: it
      duplicates the typed data layer in the client, moves credentials into
      application JS by convention if not by necessity, and contradicts sprint-1
      decision D1.
- [ ] **C — Server-sent events.** Genuinely push-based and the best experience,
      but it needs a new streaming endpoint, an edge location with
      `proxy_buffering off`, and a reconnect strategy. Worth revisiting if 30s
      proves too slow; too much machinery for a dashboard whose underlying data
      moves every 30s.
- [ ] **D — Manual refresh affordance only.** A visible "refresh" button plus a
      truthful timestamp. Not sufficient alone, but the honest fallback if
      auto-refresh is ever disabled.

**Required regardless of the above:**

- [ ] **Make freshness tick.** The badge must recompute client-side on a timer so
      "just now" becomes "2 min ago" without a page load. This is fault 2 and the
      real bug.
- [ ] **Never animate a refreshed value.** `DESIGN-BOOK.md` §6 prohibits
      animating a number the reader is looking at; a value that swaps must swap
      instantly, with no tween and no count-up.
- [ ] **Honour `prefers-reduced-motion`** for any indicator the refresh adds.
- [ ] **Give the reader control** (PAIR: feedback + control). Auto-refresh that
      cannot be paused fights anyone reading a table or comparing two rows. A
      pause toggle, and a visible "last updated", are part of the fix rather than
      polish.
- [ ] **Do not refresh `/settings`.** Configuration does not change under the
      reader, and re-fetching it every 30s is noise with no signal.

### Regression test

- [ ] `relativeAge` already has unit coverage; add a test that the ticking
      component recomputes rather than rendering a constant.
- [ ] A test that the refresh interval is not shorter than the server sampling
      interval — polling faster than the data changes is pure load.

---

## Acceptance Criteria

- [ ] Numbers update without a manual reload on `/`, `/tokens`, `/cache` and
      `/collections`
- [ ] The freshness badge advances over time and never reads "just now" about
      data that is minutes old
- [ ] No value animates or counts up when it changes
- [ ] The reader can pause auto-refresh, and can see when the data last arrived
- [ ] `prefers-reduced-motion` is honoured
- [ ] `/settings` does not auto-refresh
- [ ] No API credential appears in client-side JS
- [ ] The refresh interval is no faster than the 30s server sampling rate

---

## Implementation Notes

- **`cache: "no-store"` was never a refresh mechanism** and was never claimed to
  be — it prevents serving a stale value *for a request*. Conflating the two is
  the easy mistake here.
- **Fault 2 is the one to fix first.** It is smaller, it is a violation of a
  written rule rather than a missing feature, and it is what makes the current
  state actively misleading rather than merely limited.
- **Every sprint-1 check was a first-render check.** Status codes, rendered HTML,
  counted table twins, token conformance. None of them could have caught "and
  then nothing happens", which is worth remembering for the next acceptance list.
- **Watch the panel-independence rule.** A refresh that fails must degrade like
  any other fetch failure — one panel showing an error, the rest still rendering
  their last good values, not a blanked page.

---

## Resolution — 2026-08-06

**Files:** `src/components/RelativeTime.tsx` (new),
`src/components/AutoRefresh.tsx` (new), `src/components/ProvenanceBadge.tsx`,
`src/components/Panel.tsx`, the four live pages, `vitest.config.mts`,
`src/components/__tests__/realtime.test.tsx` (new).

**Fault 2 — the freshness lie — is fixed.** `RelativeTime` recomputes on a 15s
timer. It takes the server-rendered string as `initial` and uses it verbatim for
the first paint, so hydration matches exactly; the timer then takes over. Without
that, server and client would compute against different clocks and React would
warn. Applied to the provenance badge and to both panel states that quote an age.

**Fault 1 — no refresh — is fixed with option A.** `AutoRefresh` calls
`router.refresh()` every 30s, which re-runs the page's server components and
streams fresh markup in. No new endpoint, no edge change, no API credential in
the browser, and the whole typed data layer is reused unchanged.

`renderedAt` comes from the server on each render, so the "Updated …" label moves
on its own. There is deliberately no client-side "last refreshed" state: the
honest answer is when the *data* was fetched, not when a timer last fired, and
those diverge precisely when a refresh fails — which is when the difference
matters.

**Verified live.** A fresh render picks up new data:

```
before: Tokens today 384,342
        POST /ext/exchange  (tokens_in 1234, tokens_out 567)
after:  Tokens today 386,143      (+1,801)
```

Controls present on `/`, `/tokens`, `/cache` and `/collections`; absent on
`/settings`, since configuration does not change under the reader.

**Design Book obligations met:** no value animates or tweens on refresh (§6 —
never animate a number being read); the reader can pause, the preference persists,
and paused says so out loud rather than silently freezing; a hidden tab is not
refreshed, because it cannot be read and the box is also running a model server;
`prefers-reduced-motion` is already enforced globally by `interaction.css`.

**Interval is pinned to the server sampling rate.** `SERVER_SAMPLE_INTERVAL_MS`
is exported and a test asserts the refresh interval is never shorter: polling
faster than the data can change surfaces nothing and only adds load.

Tests: 49 pass, up from 39 — 10 new, and the load-bearing one advances a fake
clock five minutes and asserts the label *changed*. Asserting the initial render
would have passed against the bug.

### Two toolchain notes

- **happy-dom, not jsdom.** jsdom 27 fails to load under vitest's forks pool:
  its CSS-parser chain (`@asamuzakjp/css-color` → `@csstools/css-calc`) is
  ESM-only and gets `require()`d, giving `ERR_REQUIRE_ESM`. happy-dom avoids that
  chain and is lighter. The DOM is opt-in per file via an
  `@vitest-environment` docblock, so the data-layer suite still starts instantly.
- **One test was wrong, not the code.** Asserting the `initial` string via
  `render()` fails because testing-library flushes effects on mount, so the timer
  has already corrected the label. Rewritten against `renderToStaticMarkup`,
  which is the markup hydration actually compares against.

### Still not verified

**No browser has been opened.** The refresh is proven by unit tests and by the
server producing fresh data per request; what remains unproven is that
`router.refresh()` visibly updates a real page without a flash of the loading
state. This is the same browser-verification gap sprint 1 closed with, and this
ticket does not close it either.
