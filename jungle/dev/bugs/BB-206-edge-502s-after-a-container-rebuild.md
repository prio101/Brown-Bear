# Bug: every tunnelled route 502s after rebuilding app or web

**Status:** Fixed — 2026-08-21
**Severity:** High — total outage of everything published through the tunnel. The origin, the dashboard and all `/ext/*` clients are affected at once, and nothing in the stack recovers on its own
**Points:** 2
**Branch:** `fix/BB-206-edge-upstream-resolution`
**Date:** 2026-08-21
**Regression in:** nothing — latent since the edge was introduced. Triggered the first time `app` and `web` were recreated while the edge kept running (2026-08-21, deploying spec 011)

---

## Symptom

Every authenticated route through the tunnel answers `502 Bad Gateway`, including
the dashboard and the whole `/ext/*` gateway. The stack looks healthy: all
containers are `Up`, `curl localhost:8080/api/health` is 200, and
`curl localhost:3001/files` is 200. Only requests that pass through the edge fail.
It persists indefinitely — every request, until the edge is restarted by hand.

```
2026/08/21 10:02:32 [error] 41#41: *2417 connect() failed (111: Connection refused)
  while connecting to upstream, client: 172.21.0.1, server: _,
  request: "POST /ext/exchange HTTP/1.1", upstream: "http://172.21.0.10:8080/ext/exchange",
  host: "brownbear.frostmangobox.com"
2026/08/21 10:02:53 [error] 41#41: *2417 connect() failed (111: Connection refused)
  while connecting to upstream, client: 172.21.0.1, server: _,
  request: "GET /files HTTP/1.1", upstream: "http://172.21.0.5:3000/files",
  host: "brownbear.frostmangobox.com"
```

Read those two upstream addresses together — they are the tell. `172.21.0.10:8080`
is the API port at the address the *dashboard* was on, and `172.21.0.5:3000` is the
dashboard port at the address the *API* was on. The two containers had swapped
addresses and nginx knew neither.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Component | `edge/nginx.conf.template` — the nginx origin, container `brownbear-edge` |
| Environment | `nginx:1.27-alpine`, compose network `brown-bear_default` (172.21.0.0/16) |
| Reachable via | `curl -H "Host: brownbear.frostmangobox.com" -H "Authorization: Bearer $BB_EDGE_TOKEN" http://127.0.0.1:8081/ext/health` |
| Auth | one shared secret, `Authorization: Bearer $BB_EDGE_TOKEN` or `Basic $BB_EDGE_BASIC` |
| First seen | 2026-08-21, immediately after `docker compose up -d --force-recreate app web` |

The edge reaches the other two services by container name — `app:8080` and
`web:3000` — over the compose network. Docker assigns those addresses at container
*start*, not once per service, so any recreation can move them.

---

## Reproduction

Reliable, and it does not need a rebuild — only a change of address. The first
attempt at this reproduced nothing, because Docker happened to hand the recreated
containers the same two addresses back; the fillers below force the change.

1. Note the current addresses and confirm the edge is healthy.
   ```bash
   docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' brownbear-app brownbear-web
   ```
2. Free the addresses and park them somewhere else.
   ```bash
   docker compose stop app web
   for i in 1 2 3; do docker run -d --name ipfiller$i --network brown-bear_default alpine sleep 600; done
   ```
3. Start the services again — they come up on new addresses — and **do not touch the
   edge**.
   ```bash
   docker compose start app web
   ```
4. Ask the edge for anything.
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -H "Host: brownbear.frostmangobox.com" \
        -H "Authorization: Bearer $BB_EDGE_TOKEN" http://127.0.0.1:8081/ext/health
   ```

**Expected:** 200 — the upstream is up and its name still resolves.
**Actual:** 502, on every route, forever. `docker compose restart edge` fixes it.

---

## Root cause

**nginx resolves a literal upstream hostname once, at configuration load, and then
dials that address for the life of the process.** Every `proxy_pass` in this file
named its upstream literally (`http://app:8080…`, `http://web:3000…`), so the
edge held two IP addresses captured at startup. Recreating the containers moved
them, and nginx went on connecting to addresses that no longer belonged to
anything — hence `connection refused` rather than a timeout or a DNS error.

The symptom pointed the other way. "502 from the origin" reads as *the upstream is
down*, and the first thing to check is the upstream — which was up, healthy, and
serving 200 on its own port the whole time. Nothing was wrong with `app` or `web`
at all, and nothing was wrong with the tunnel either: nginx was logging the
requests, so they had already crossed Cloudflare and arrived. The failure was
entirely in the one hop that looked least likely, and it was a stale belief rather
than a broken component.

Adding a `resolver` alone would not have fixed it. nginx only re-resolves when the
upstream host comes from a *variable*; with a literal hostname the directive is
inert, which is a second wrong belief worth writing down.

---

## Fix

- [x] `resolver 127.0.0.11 ipv6=off valid=30s;` in `edge/nginx.conf.template` —
      Docker's embedded DNS, with staleness capped at 30 seconds. `ipv6=off`
      because the embedded resolver answers AAAA for names that have no IPv6
      address and the failed lookups are pure latency
- [x] `set $bb_app app; set $bb_web web;` at server level, and all 19
      `proxy_pass` directives moved onto them — without a variable host the
      resolver does nothing
- [x] Each of those 19 now states its URI explicitly, because a variable host
      turns off two conveniences of the literal form (see the note below)
- [x] No change to authentication, to `limit_except`, or to the default-deny — the
      allowlist is untouched

### Regression test

The check is a behavioural sweep rather than a unit test: what had to be proved is
that 19 rewritten directives still route and still deny exactly as before.

- [x] `python3 jungle/app/scripts/check_edge_contract.py` — parses the 20 locations
      out of the template and agrees with all 54 declared endpoints. This is the
      existing guard, and it passes unchanged
- [x] A 44-route sweep of every published path, every path that must stay denied,
      and both auth-failure cases, captured before the change and diffed after:
      identical, including the sub-path cases (`/_next/static/…`,
      `/design/design-book.md`, `/ext/files/{id}`) that a mis-translated
      `proxy_pass` would have truncated
- [x] The forwarded URI as *uvicorn logged it*, before and after, for an
      exact-match location, a prefix location and a regex location — byte for
      byte identical, query strings included
- [x] The reproduction above, run against the fix: 200 immediately, with the edge
      never restarted and the old addresses held by other containers

---

## Acceptance Criteria

- [x] The reproduction no longer 502s, and needs no edge restart
- [x] Recovery is bounded by `valid=30s`, so a stale answer cannot outlive half a
      minute
- [x] Every published route returns exactly the status it returned before
- [x] Every denied route stays denied: `/metrics` 403, `PUT /api/settings` 403,
      `POST /api/tokens/aggregate` 403, `/ollama/api/delete` 403, and a GET-only
      route still refuses POST
- [x] An absent credential is still 401 and a wrong one still 401
- [x] Query strings still reach the app on exact-match locations, which is where
      the variable form silently drops them if `$is_args$args` is forgotten

---

## Implementation Notes

- **A variable host changes URI handling, and this is the trap.** With a literal
  `proxy_pass`, nginx substitutes the matched location prefix into the target and
  appends the original query string for free. With a variable it does neither: the
  URI is passed exactly as written. A careless conversion of
  `location /ext/ → proxy_pass http://app:8080/ext/;` sends every request to
  `/ext/` and nothing else — a total mis-route that still answers 200 for the
  index and looks like it works. The three shapes here were translated as:
  identity-prefix and bare-host passthrough to `$request_uri`; exact-match
  locations to their literal path plus `$is_args$args`; and the five that already
  spelled out `$uri$is_args$args` were left as they were.
- **`envsubst` does not eat `$bb_app`.** The nginx entrypoint substitutes only
  names that exist in the environment, which is why `$uri` and `$args` already
  survive rendering. A new nginx variable needs no escaping — but it does need to
  not collide with an env var name.
- **The same mistake is waiting in any future `proxy_pass`.** A literal hostname
  added later reintroduces this bug for that one route only, which is harder to
  spot than a whole-origin outage. The comment block above the `resolver` says so
  in the file.
- **`docker compose up -d --build` may not restart anything.** It rebuilt both
  images and left both containers running on the old ones; `--force-recreate` was
  needed to adopt them, and that is what moved the addresses. Worth knowing
  before concluding a rebuild did nothing.
