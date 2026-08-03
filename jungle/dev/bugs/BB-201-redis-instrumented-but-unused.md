# Bug: Redis cache hit rate is always zero

**Status:** Fixed — 2026-08-04 via option A, see *Resolution* at the end
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

---

## Resolution — 2026-08-04

**Option A: Redis now caches prompt embeddings.** Chosen over removing the
service or merely relabelling the tile, because embedding the prompt is the only
per-request model call in the gateway's hot path and prompts repeat constantly in
a coding loop. Option C became unnecessary: the metric is real now, so there is
nothing to relabel.

**Files:** `brownbear/embeddings.py` (new), `brownbear/connectors/redis_conn.py`
(`cache_get`/`cache_set`), `brownbear/config.py`, `brownbear/routers/ext.py`,
`brownbear/gateway.py`, `tests/test_embeddings.py`, `CLAUDE.md`, `QWEN.md`.

**Measured on the live stack.** Two identical `/ext/context` calls:

```
call 1: 1044 ms      (miss — the embedding model ran)
call 2:   80 ms      (hit  — 13x faster)
```

Then four distinct prompts asked twice each:

```
keyspace_hits:   6
keyspace_misses: 5
dbsize:          5
key:  bb:emb:nomic-embed-text:8e98ea7dd7836cc1…
ttl:  604783        (7 days, counting down)
```

The dashboard tile went from **"no samples"** to **"Cache hit rate 66.7%"** —
the first time that number has ever been able to move.

**Two rules make it safe to trust:**

1. **The model name is in the key** (`bb:emb:{model}:{sha256(text)}`). A
   `nomic-embed-text` vector is meaningless to another model, and serving one
   silently would corrupt every similarity score the gateway then compares to a
   0.95 cutoff. This was the one real correctness risk in the change.
2. **Every cache failure is a miss, never an error.** Redis down, a timeout, an
   unparseable payload, or a value that is the wrong shape all fall through to
   Ollama. Spec 005 requires that Brown Bear being unwell degrades context rather
   than blocking work, and a cache that can break what it accelerates is worse
   than no cache. Twenty tests cover this, including six poisoned-payload shapes.

**Wired at two call sites**, and the second is the higher-value one: the client
calls `/ext/context` and then `/ext/exchange` with the *same* prompt, so the
store path's embedding was computed moments earlier by the lookup. That pairing
alone halves the gateway's model calls.

**Document ingestion deliberately does not use the cache.** Chunks are
near-unique, so caching them would spend memory on entries that never repeat, and
ingestion is already idempotent by content id.

**The collection-creation probe also stays uncached** (`ollama.embed_one("dimension
probe")`). It exists to prove the embedder is actually alive; serving it from
cache would defeat the check.

**TTL is 7 days** and mandatory — an embedding cache without expiry grows without
bound on a box that is also running a model server. Embeddings are deterministic
for a fixed model, so the TTL is memory management rather than freshness, and it
also means a re-pulled model's stale vectors age out on their own.

`CLAUDE.md` and `QWEN.md` claimed Redis provided "Caching, sessions, queues".
Now corrected to what the code does: an embedding cache, no sessions, no queues.

Tests: 138 pass, up from 118.

### Still open

- [ ] **`QWEN.md` is a byte-identical duplicate of `CLAUDE.md`.** Both were
      updated here to keep them consistent, but two copies of the same document
      will drift. Worth deleting one or making it a symlink — a separate decision.
- [ ] **A second candidate remains:** `/api/tokens/*` aggregates are recomputed on
      every page load and would cache well. Not done here; this ticket only needed
      one real consumer to stop the metric being fictional.
