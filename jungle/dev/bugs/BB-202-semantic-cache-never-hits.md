# Bug: The semantic cache never returns a hit

**Status:** Fixed — 2026-08-03, see *Resolution* at the end
**Severity:** High — this is the reason the stack exists (spec 005), and it has never served a single hit
**Points:** 5
**Branch:** `fix/bb-202-cache-scope-fragmentation`
**Date:** 2026-08-03
**Related:** [BB-201](BB-201-redis-instrumented-but-unused.md) — a different cache, same complaint

---

## Symptom

`/ext/context` never answers `hit: true`. Claude Code never prints
`Brown Bear cache hit`. Storing works — the corpus grows — but nothing is ever
served back.

Asking the same question twice, verbatim, from this repository:

```
$ curl -s -XPOST localhost:8080/ext/context -H 'Content-Type: application/json' \
    -d '{"prompt":"how do I rotate the edge token","project":"Brown-Bear","model":"claude-opus-5"}'
{"hit":false,"reason":"no candidates","score":null,"matched_prompt":null,
 "near_miss":false,"threshold":0.95,"chunks":[]}
```

`"no candidates"`, not `"below threshold"` — the vector search returned **nothing
at all**, despite 15 documents in `conversations`. Always.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Component | `jungle/app/brownbear/gateway.py` — `_scope_filter()`, `lookup_cache()` |
| Collection | `conversations`, id `3c35c870-6994-4ea6-be0b-e4df198d4308`, cosine, 768-dim |
| Client hook | `clients/claude-code/bb_context.py` — `project_for()` |
| Threshold | `0.95` cosine (`cache_similarity_threshold`, runtime-tunable) |
| Candidates fetched | `n_results=3`, filtered by a Chroma `where` clause |
| First seen | Since spec 005 landed — this has never worked |

**The scope filter** restricts every lookup to one project and one model by exact
equality:

```python
clauses = [{"project": {"$eq": project}}]
if model:
    clauses.append({"model": {"$eq": model}})
```

**The client derives `project` from the git root's basename** (`project_for()`),
overridable with `BB_PROJECT`. From this repository that is `Brown-Bear`. When
the cwd is not a git repo it falls back to the directory's own name.

---

## Reproduction

1. From this repo, ask Claude Code anything twice with the hooks installed.
2. Observe no cache hit, ever.
3. Query directly with the scope the hook sends:
   ```bash
   curl -s -XPOST localhost:8080/ext/context -H 'Content-Type: application/json' \
     -d '{"prompt":"anything","project":"Brown-Bear","model":"claude-opus-5"}'
   ```

**Expected:** a hit on the second identical prompt, or at minimum
`"reason":"below threshold"` with a score.
**Actual:** `"reason":"no candidates"` — the filter excluded every document.

---

## Root cause

**Cache scope fragmentation.** The 15 stored documents are spread across **eight
mutually invisible project scopes**, and the scope a query arrives under holds no
documents at all.

| documents | project | model |
|---|---|---|
| 4 | `OS-20-ST1` | `claude-opus-5` |
| 3 | `prio` | `claude-opus-5` |
| 2 | `brownbear` | `claude-opus-5` |
| 2 | `brownbear` | `some-paid-model` |
| 1 | `tunnel-demo` | `claude-opus-5` |
| 1 | `hook-test` | `claude-opus-5` |
| 1 | `hook-roundtrip` | `claude-opus-5` |
| 1 | `bb` | `claude-opus-5` |
| **0** | **`Brown-Bear`** | — ← what this repo's hook sends |

Three separate things went wrong, and each alone is enough to guarantee a miss:

1. **The querying scope is empty.** The hook sends `Brown-Bear`; nothing was ever
   stored under it. `$eq` is exact — `Brown-Bear`, `brownbear` and `brown-bear`
   are three different caches. The `brownbear` documents were seeded by hand on
   2026-07-30, not written by the client.
2. **Real use is fragmenting further.** `project='prio'` (3 documents, one written
   today at 17:27) is the non-git fallback firing: work in `/home/prio` outside a
   repo scopes the cache to the *home directory's name*. Every non-repo directory
   becomes its own cache, and `prio` will accumulate unrelated answers from
   everywhere.
3. **Even a scope-matched query cannot clear the bar.** With the correct
   `project=brownbear`, the closest match to a genuinely related question scored
   **0.351** against a **0.95** cutoff:
   ```
   {"hit":false,"reason":"below threshold","score":0.350816,
    "matched_prompt":"Which database stores metadata in Brown Bear?"}
   ```
   A scope holding 1–4 unrelated documents will essentially never contain a
   near-identical prior question. The threshold is not yet the binding
   constraint — the corpus is.

**What the symptom suggested versus what was true.** "No cache hits" reads as a
threshold that is too strict, and 0.95 is conspicuous enough to look guilty. It
is not the cause. Lowering it would have changed nothing here, because the filter
removes every candidate before a score is computed — and it would have quietly
raised the risk of a wrong hit later, once the corpus fills. **`"no candidates"`
and `"below threshold"` are the two distinct signals that tell these apart, and
the API already reports which one applies.** Read the `reason` before touching the
threshold.

---

## Fix

- [ ] **Normalise the scope key.** Lower-case and strip non-alphanumerics before
      storing and before querying, so `Brown-Bear`, `brownbear` and `brown_bear`
      are one cache. Apply in `gateway.py` so it holds regardless of client
      version, and in `project_for()` so what the client reports matches.
- [ ] **Migrate the existing documents** to normalised keys, or accept the loss
      and say so. 15 documents is not worth a migration; deleting the seeded ones
      is defensible. Decide explicitly rather than leaving two conventions.
- [ ] **Fix the non-git fallback.** `Path(cwd).name` for a non-repo directory is
      actively harmful — `/home/prio` becomes scope `prio`. Prefer an explicit
      `default` scope, or refuse to store outside a repo, over silently scoping to
      a home-directory name.
- [ ] **Surface the reason in the dashboard.** `no candidates` vs
      `below threshold` vs `expired` vs `not cacheable` is the single most
      diagnostic field the gateway produces and nothing displays it. A panel on
      `/cache` showing recent lookups by outcome would have made this a
      five-minute diagnosis instead of an investigation.
- [ ] **Do not lower the threshold as part of this fix.** Once scopes are merged,
      re-measure with the near-miss log before touching it.

### Regression test

- [ ] `test_gateway.py`: storing under `Brown-Bear` and querying under
      `brownbear` finds the candidate — would fail today.
- [ ] A verbatim-repeat lookup within one scope returns `hit: true`.
- [ ] `project_for()` on a non-git directory returns the default scope, not the
      directory's name.

---

## Acceptance Criteria

- [ ] Asking an identical question twice in one project returns `hit: true`
- [ ] Scope keys differing only in case or separators resolve to one cache
- [ ] A non-git working directory does not create a scope named after its parent
- [ ] `no candidates` and `below threshold` remain distinguishable in the API and
      become visible in the UI
- [ ] The threshold is unchanged by this fix, and any later change cites
      near-miss data
- [ ] Storing still works — the corpus grew as recently as 2026-08-03 17:27 and
      must not regress

---

## Implementation Notes

- **Storing was never broken.** The newest document is from today, so the Stop
  hook and `/ext/exchange` work. Only retrieval is affected, which is why this
  looked like a threshold problem: the corpus visibly grows while never being
  used.
- **The scope filter is right in principle.** An answer about one repository must
  not be served for another, and a model's answer is not automatically valid for
  another model. The defect is the key's *stability*, not the filtering.
- **Model scoping compounds it.** `BB_MODEL` must match across machines or each
  gets its own scope — `REMOTE-SETUP.md` already warns about this, which suggests
  the fragility was anticipated for the model and missed for the project.
- **Watch the `prio` scope.** It holds three documents written from outside a
  repo and will keep collecting unrelated answers under a home-directory name.
  Those are the documents most likely to produce a *wrong* hit once a threshold
  is ever lowered, because they share no subject matter at all.

---

## Resolution — 2026-08-03

**Files:** `brownbear/gateway.py` (`normalise_project`, `normalise_model`),
`brownbear/routers/ext.py` (`_Scoped` validator mixin),
`clients/claude-code/bb_context.py`, `clients/claude-code/bb_exchange.py`,
`scripts/migrate_scope_keys.py`, `tests/test_gateway.py`, `tests/test_ext.py`.

**Proof it works.** Stored an exchange under `Brown-Bear`, looked it up under
`brownbear` — the exact pair that disabled the cache:

```
hit:     True
score:   1.0
matched: What distance space do the Brown Bear collections use…
```

**Isolation still holds**, which matters more than the hit: the same prompt under
a different project returns `no candidates`, and under a different model returns
`no candidates`. The fix merges spellings, not projects.

**Normalisation happens at the request boundary**, in a Pydantic validator mixin,
not at each use. The scope key reaches three destinations that must agree — the
Chroma `where` filter, the `content_id`/`exchange_id` hashes, and the stored
metadata — and a store path writing an un-normalised key is precisely how the
original bug survived. `_scope_filter` deliberately does **not** normalise, so a
caller that forgets fails visibly in a test instead of silently widening scope.

**Case and punctuation are dropped, not collapsed to a dash.** Collapsing yields
`brown-bear`, which still does not match `brownbear` — and matching those two was
the entire bug. The accepted cost is that `my-app` and `myapp` become one cache.

**Migration ran.** `scripts/migrate_scope_keys.py --apply` re-keyed **8 of 17**
documents, including the four written from the remote machine
(`OS-20-ST1` → `os20st1`), which would otherwise have been orphaned by their own
fix. The original spelling is preserved in `project_original`, since re-keying is
otherwise irreversible. Idempotent — a second run reports 0. Scopes are now:
`brownbear` 4, `os20st1` 4, `prio` 3, `tunneldemo` 1, `hooktest` 1,
`hookroundtrip` 1, `bb` 1.

**Non-git fallback fixed.** Both hooks now return `"default"` outside a
repository instead of the directory's own name, which is what created the `prio`
scope. The three documents already in `prio` are left alone; nothing new joins them.

**Threshold untouched at 0.95**, as the diagnosis required. Now that scopes merge,
the near-miss log is the thing to read before anyone changes it.

Tests: 118 pass, up from 102 — 16 new, covering every spelling of the reported
pair, model punctuation that must survive (`smollm2:135m`), id stability across
spellings, and the boundary validators.

### Still open, deliberately

- [ ] **Surface the lookup `reason` in the dashboard.** `no candidates` vs
      `below threshold` vs `expired` vs `not cacheable` is the most diagnostic
      field the gateway produces, and nothing displays it — which is why this bug
      needed an investigation rather than a glance. Needs an endpoint over the
      query log plus a panel on `/cache`; separable from the fix, and worth its
      own ticket.
- [ ] **Clean up the junk scopes** (`hooktest`, `hookroundtrip`, `bb`,
      `tunneldemo`, and the three `prio` documents). Harmless while the threshold
      is 0.95; they are the documents most likely to produce a *wrong* hit if it
      is ever lowered, because they share no subject matter with anything.

### Action required on the remote machine

`bb_context.py` and `bb_exchange.py` changed. Until they are updated there, that
machine keeps sending the old non-git fallback. Re-run `install-remote.sh`, or
copy both files to `~/.claude/bb/`. Its `OS-20-ST1` scope is already migrated, so
its existing cache survives either way.
