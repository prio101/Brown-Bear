# Bug: Redis cache hit rate is always zero

**Status:** Open — diagnosed, not fixed
**Severity:** Medium — no data loss, but the dashboard presents a metric that cannot move, and a whole service earns its keep by doing nothing
**Points:** 3
**Branch:** `fix/bb-201-redis-unused`
**Date:** 2026-08-03

---

## Symptom

The dashboard's cache hit rate never shows a value. Reported as "cannot get any
redis cache hit".

```
$ docker exec redis redis-cli -a *** INFO stats | grep keyspace
keyspace_hits:0
keyspace_misses:0

$ docker exec redis redis-cli -a *** DBSIZE
0

$ curl -s localhost:8080/api/cache | jq '.current.lifetime_hit_rate'
null
```

Always, not intermittently. `total_commands_processed:834` — Redis is being
talked to, but only by health checks.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Component | `jungle/app/brownbear/connectors/redis_conn.py` |
| Service | `redis:7-alpine`, container `redis`, port `6379`, password-protected |
| Read by | `GET /api/cache`, `GET /api/health`, `GET /metrics`, `collector.py` |
| Surfaced on | `/` (hit-rate tile) and `/cache` |
| First seen | Since the stack was built — this has never worked |

---

## Reproduction

1. Run the stack and use it normally for any length of time.
2. Check Redis directly:
   ```bash
   docker exec redis redis-cli -a "$REDIS_PASSWORD" DBSIZE      # 0
   docker exec redis redis-cli -a "$REDIS_PASSWORD" KEYS '*'     # empty
   ```
3. Check the dashboard's cache tile: "no samples".

**Expected:** some keys, and a hit rate that moves as the cache is used.
**Actual:** zero keys, zero hits, zero misses, forever.

---

## Root cause

**Nothing in the application ever writes a Redis key.** `redis_conn.py` exposes
exactly two operations — `ping()` and `info()` — and every other reference to
Redis in the codebase reads INFO counters for reporting:

```
$ grep -rE '\.(set|get|setex|hset|expire|incr)\(' brownbear/ | grep -i redis
(no matches)
```

`keyspace_hits` counts key lookups that found something. With no key ever
written, and no lookup ever performed, the counter is pinned at 0 by
construction. The 834 commands processed are the health check's `PING`/`INFO`
and the collector's 30-second sampling.

So the symptom is not a fault in Redis, the connector, or the dashboard. The
dashboard is reporting the truth accurately — BB-107 deliberately renders it as
"no samples" rather than `0%` precisely so that a nothing-to-report state cannot
be mistaken for a failing cache.

**What the symptom actually exposes:** Redis is in the stack, password-protected,
persisted to a volume, health-checked, sampled every 30s, retained for 7 days,
charted on two pages and exported to Prometheus — and does no work. The metric
is real; the thing it measures does not exist.

`CLAUDE.md` claims Redis provides "Caching, sessions, queues". None of the three
is implemented.

---

## Fix

This is a design decision, not a one-line patch. Three options, and the choice
belongs to whoever owns the roadmap:

- [ ] **A — Use it.** Give Redis a real job. The obvious candidate is the
      embedding cache: `/ext/context` embeds every incoming prompt through Ollama
      on every request, and identical prompts are common in a coding loop.
      Keying `sha256(prompt) → embedding` with a TTL would cut a model call per
      repeat and make the hit rate meaningful. Second candidate: caching
      `/api/tokens/*` aggregates, which are recomputed per page load.
- [ ] **B — Remove it.** Drop `redis`, `redisinsight`, the connector, the
      sampling, the retention job, the two charts and the Prometheus gauges.
      Frees a container and ~1MB of resident memory, and deletes a metric nobody
      can act on.
- [ ] **C — Label it.** Keep Redis for future use, but stop presenting an
      unusable metric as an operational one: the tile should say "not in use"
      rather than "no samples", which currently reads as "not yet" when the
      truth is "never".

**Recommendation: A, then C as the interim.** The embedding cache is a genuine
win — it is the only per-request model call in the gateway's hot path — and C is
a ten-minute change that stops the dashboard implying a fault where none exists.

### Regression test

- [ ] Whichever option is chosen, assert it: for A, a test that a repeated
      embedding request produces a Redis hit; for B, that no Redis reference
      survives; for C, that the tile renders the "not in use" copy when
      `DBSIZE` is 0 and no writer is configured.

---

## Acceptance Criteria

- [ ] The dashboard no longer presents a metric that cannot move
- [ ] `CLAUDE.md`'s claim about Redis matches what the code does
- [ ] If Redis is kept: at least one code path writes and reads a key, and the
      hit rate changes under use
- [ ] If Redis is removed: `grep -ri redis jungle/ edge/ compose.yaml` finds no
      live reference, and `/api/cache` is removed or repurposed rather than left
      returning a permanently empty payload
- [ ] The distinction from the semantic cache is documented — see
      [BB-202](BB-202-semantic-cache-never-hits.md)

---

## Implementation Notes

- **Do not "fix" this by making the tile show 0%.** `null` is correct; the whole
  point of BB-107's null handling is that absence of evidence is not evidence of
  failure. The bug is upstream of the display.
- **The semantic cache is a different thing entirely** and lives in ChromaDB.
  Anyone chasing "no cache hits" will hit both this and BB-202, and they have
  nothing in common but the word "cache".
- **If option A:** the embedding cache key must include the embedding model name.
  A cached `nomic-embed-text` vector is not valid for a different model, and
  serving one silently would corrupt every similarity score computed from it.
