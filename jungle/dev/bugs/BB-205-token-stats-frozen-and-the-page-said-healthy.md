# Bug: Token stats stopped moving, and the dashboard reported itself healthy

**Status:** Open — the dashboard half is fixed (see *Fix*); the reporting machine is not this repo's to change
**Severity:** High — not because a number was wrong, but because a dead feed was indistinguishable from a quiet day for eighteen hours
**Points:** 3
**Branch:** `fix/bb-205-usage-reporting-staleness`
**Date:** 2026-08-19

---

## Symptom

Reported as: the API is being used through the hooks, and it is not affecting the
stats.

```
GET /api/tokens/summary        tokens_in 0, tokens_out 0, request_count 0
last token_event               2026-08-18 15:01:07 UTC   (~18h earlier)
overview page                  no banner, every panel green
```

Continuous. Every other part of the dashboard looked normal throughout, which is
the part that matters.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Components | `jungle/web/src/app/page.tsx`, `jungle/web/src/app/tokens/page.tsx`, `jungle/app/brownbear/routers/tokens.py` |
| Reporting path | client Stop hook → `POST /ext/exchange` → `token_events` |
| Environment | dashboard behind the edge; the reporting machine reaches it through the Cloudflare tunnel |
| First seen | 2026-08-19, silence beginning 2026-08-18 15:01 UTC |

---

## Reproduction

Not reproducible on demand — it is a client-side condition, recorded here as it
was found. What established it:

1. Compare what arrives at the edge:
   ```bash
   docker logs brownbear-edge | grep -oE "POST /ext/[a-z]+" | sort | uniq -c
   ```
   `/ext/context` present and answering 200; `/ext/exchange` **absent entirely**
   across the container's whole 14.6h log.
2. Confirm the stack agrees:
   ```sql
   select max(timestamp) from token_events;          -- 2026-08-18 15:01:07+00
   select status, rows_written from aggregation_runs  -- hourly, completed, 0 rows
     order by id desc limit 3;
   ```
3. Send the same request the Stop hook sends, with and without a User-Agent:
   ```bash
   # 403, error code 1010          <- default python-urllib UA
   # 422, the app's own validation <- User-Agent: brown-bear-client/1.0
   ```

**Expected:** usage reported after each turn.
**Actual:** every report rejected at Cloudflare, and no trace of it anywhere.

---

## Root cause

Two independent faults, one on each side. Only the second one is this repo's.

**1. The reporting machine's Stop hook sends no `User-Agent`, and Cloudflare
refuses those.** `~/.claude/hooks/brownbear-exchange.py` is a hand-rolled hook
that predates `df35b0c fix(clients): send a User-Agent, or Cloudflare silently
eats every hook call`; it builds its request with `Content-Type` and
`Authorization` only. Cloudflare answers `403 error 1010` to the default
`python-urllib` agent, and the hook's own `except Exception: return 0` swallows
it — by design, because a metering failure must not wedge a session. The
installer's `bb_exchange.py` sets the agent correctly; `settings.json` on that
machine points at the older path instead. The `PostToolUse` media hook beside it
*does* set the agent, which is why file ingestion kept working and made the
silence look narrower than it was.

**2. Nothing on the dashboard could tell a dead feed from a quiet day.** This is
the real bug, and it is ours. The overview's liveness is derived from the
collector's freshness — and the collector samples this host from inside the
container every 30s, so it was perfectly fresh for the entire incident. What had
stopped was arriving from a different machine over a path nothing measured. The
token pages showed `0` with a provenance badge and a fetch time, both accurate,
and no answer to the only question a reader had: *is anything still arriving?*

`LivenessBanner`'s own docstring had already stated the principle — "an empty
dashboard is ambiguous, absence of data is never evidence of health, and something
has to say so out loud" — and the token feed was never wired to it.

---

## Fix

- [x] `GET /api/tokens/summary` returns `last_event_at`, `last_event_source` and
      `stale_after_hours`. Deliberately **not** scoped to the requested window: the
      window says what happened today, these say whether anything is still arriving.
- [x] `usage_stale_hours` (default 24) in `config.py`, reported by the endpoint so
      the page holds no private opinion about what stale means — the same pattern the
      agent inventory uses.
- [x] `lib/api/reporting.ts` — one rule, two pages. Returns a banner state plus a
      note, with `unknown` for never-reported kept distinct from `stale`.
- [x] The overview carries a **second** liveness banner for reporting, beside the
      collector's. Separate, not merged: the two fail independently and a reader has
      to know which one did.
- [x] `/tokens` carries the same banner, and the age rides on the tiles as a note —
      a zero has to be readable where it is read, not only at the top of the page.
- [ ] The reporting machine: repoint `settings.json` at the installed
      `~/.claude/bb/bb_exchange.py`, or add the `User-Agent` header to the hook it
      currently runs. Outside this repo.

### Regression test

- [x] `jungle/app/tests/test_tokens_summary.py::TestLastReport` — five cases, the
      load-bearing one being `test_the_last_report_is_not_scoped_to_the_window`:
      today's total zero and yesterday's report both survive into one response.
      Fails on the old payload, which had no such field.
- [x] `jungle/web/src/lib/api/__tests__/reporting.test.ts` — a quiet day, a dead
      feed and a never-used instance must produce three different outputs, and the
      threshold must come from the server.

---

## Acceptance Criteria

- [x] A zero on `/tokens` or `/` is accompanied by the age of the last report
- [x] Never-reported reads differently from stale, and neither reads as healthy
- [x] The collector's own liveness is unchanged and still independent
- [ ] Usage from the reporting machine lands again (blocked on the client fix)

---

## Implementation Notes

- **The banner would not have fired on this incident, and that is deliberate.**
  The silence ran ~18h against a 24h window. The note — "Last report 17 hours ago
  from remote_api" next to a zero — is what makes it visible; the banner is for
  silence long enough to be suspicious on its own. A threshold tight enough to
  fire overnight would be ignored within a fortnight, which is how a real warning
  gets scrolled past.
- **Two failures wearing one costume.** Because the media hook still worked and
  `/ext/context` still answered, the dashboard had recent files, recent context
  events and a healthy collector. Every visible signal was live except the one
  that had died.
- **The numbers already recorded are inflated, separately from this.** The old
  hook sums `input + cache_read + cache_creation` across every assistant message
  in a turn — 104 events averaging 2.8M input tokens, one at 26.3M — and sends no
  bucket split, so 108 of 109 events are priced `flat` with cache reads billed as
  fresh input. Switching that machine to the installer's hook fixes both going
  forward; the historical rows stay wrong and are not worth re-deriving.
