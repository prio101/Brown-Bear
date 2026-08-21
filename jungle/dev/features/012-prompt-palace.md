# Feature: Prompt Palace

**Status:** Done — 2026-08-21, see *Delivered* at the end. Browser verification still owed.
**Priority:** Medium — the stack can say how many prompts arrived and what they cost, but not what was asked. The corpus that decides every cache hit and every retrieval is the one thing with no surface of its own.
**Points:** 5
**Branch:** `feat/012-prompt-palace`
**Date:** 2026-08-21
**Depends on:** spec 005 — `/ext/exchange`, the `conversations` collection, and the cache threshold this scores against. BB-301 — the similarity expansion this borrows its floor and its honesty rules from.

---

## Overview

A page at `/prompts` showing what this memory has been asked, from wherever it was
asked: the prompt, the answer, the machine that reported it, and — the point — what
each prompt sits *near*. Two neighbour lists per prompt, kept apart: prior prompts,
scored against the cache cutoff, and knowledge chunks, which are what a retrieval
lookup would have injected.

Together those answer a question nothing else in the stack can: **did the memory
already hold this?** A near-miss at 0.93 against a 0.95 cutoff is invisible today,
and it is exactly the case worth seeing — it is either a cutoff that is too tight or
two prompts that only look alike.

**What it deliberately does not do.** It does not verify anything. Brown Bear never
sees the model call: a client posts the finished exchange, so the prompt, the answer
and the machine name are all claims, and the machine name cannot be checked against
anything — the edge authenticates one shared secret for every machine. It also does
not stream: Chroma has no change feed, so the page refreshes rather than pushing.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Page | `/prompts`, label **Prompt Palace** — `jungle/web/src/app/prompts/page.tsx` |
| Component | `jungle/web/src/components/PromptPalace.tsx` |
| Module | `jungle/app/brownbear/prompts.py`, router `jungle/app/brownbear/routers/prompts.py` |
| Listing | `GET /api/prompts?limit&offset&project&model&machine` |
| One exchange | `GET /api/prompts/{exchange_id}` — adds the full answer |
| Neighbours | `GET /api/prompts/{exchange_id}/related?min_similarity&limit` |
| Exchange id | `x_<sha256(project\0model\0prompt)[:32]>` — pinned as `^x_[0-9a-f]{8,64}$` in the router |
| Where prompts live | Chroma collection `conversations`. Document = the **answer**; metadata = `prompt`, `project`, `model`, `created_at`, `cacheable`, `embedding_model`, `stale_after`, and now `machine` |
| Where chunks live | Chroma collection `knowledge`. Metadata = `source`, `project`, `chunk_index`, `chunk_count`, `file_id` |
| Cache cutoff | `gateway.threshold()`, 0.95 — the score above which an answer may be *served* |
| Relatedness floor | 0.50, measured on this corpus — prompts score lower against each other than documents do (see *Implementation Notes*) |
| Written by | `clients/claude-code/bb_exchange.py`, the Claude Code Stop hook |
| Edge | `^/(…|prompts)$` for the page, `^/api/prompts(/[^/]+(/related)?)?$` for the API, both GET-only |

Two constraints that would otherwise have to be rediscovered:

**Chroma has no ordering.** `get` returns documents in an unspecified order, so
"newest first" can only ever mean "newest among those read". Every count in the
response exists to keep that visible.

**A similarity is only meaningful in cosine space.** `gateway.similarity()` returns
`None` for anything else, and `None` must render as "cannot be scored" — never 0.

---

## Decisions (locked)

| Decision | Choice | Consequence |
|---|---|---|
| How "from other machines" is known | **An optional `machine` on `/ext/exchange`, sent by the hook** | Attribution is a self-declared claim, like a file's `extracted_by`. Only prompts stored after the hook is redeployed carry one; everything older reads "not recorded" |
| What the listing fetches | **Metadata only** | The prompt is in the metadata, so listing 100 prompts costs no answers. A new `with_documents=False` on the Chroma connector |
| Prompts and chunks in one list, or two | **Two, never merged** | A ranked mixture invites reading a retrieved passage as an answer — the failure spec 005 split the collections to prevent. Costs a tab control |
| Ordering | **Newest first among those scanned**, with `total`, `scanned` and `matched` reported separately | A capped scan can miss the newest prompt, and the page says so rather than implying completeness |
| Freshness | **Auto-refresh**, like `/cache` and `/tokens` | A prompt from another machine appears within the interval. No streaming: Chroma has no change feed, so a "live" feed would be server-side polling with an invented cursor |
| Unattributed prompts | **A selectable filter** | How you find a client that is not sending its name, rather than that just looking like a gap |

### Why attribution is a claim and not a fact

The edge authenticates one shared secret for every machine — a boundary control,
not per-client identity (the roadmap's open G2). So `machine: "mac-studio"` means
*a client said it was mac-studio*, and any client holding the token could say
anything. That is worth showing anyway, for the same reason `extracted_by` is worth
showing on a file: it is almost always true, and it is the only way to tell a
two-machine corpus apart. But it is shown as a claim, with the reason in the
tooltip, and `null` renders as "not recorded" — never as this host, which is the one
answer that is certainly wrong.

Verified attribution needs per-machine credentials at the edge. That is G2, it is a
security feature rather than a page, and it is not this ticket.

---

## Requirements

### The listing

- Newest first among those scanned; an exchange with no `created_at` sorts last
  rather than being handed the epoch and made to claim it is the oldest
- Reports `total`, `scanned` and `matched` as three numbers, and `truncated` when
  the scan cap was reached
- Filters by project, model and machine, including `machine=unattributed`
- Offers the machines, projects and models it actually saw, derived from the same
  scan as the rows — so the filter list cannot disagree with the list
- Fetches no answers

### A prompt

- The whole answer, fetched on selection
- `cacheable: false` is visible in the list, not just the detail: it is why a hit
  gets refused despite a high score
- The machine, the storage time, the TTL and the embedding model that produced the
  vector

### What it sits near

- Prior prompts, each with its cosine score, and whether it **would** have been
  served — which needs the score above the cutoff *and* a cacheable entry
- Knowledge chunks, each with its score and its source document, quoted as a
  passage and never presented as an answer
- Scores always shown with the cutoff they are judged against
- An unscoreable neighbour is listed with "cannot be scored", not dropped, not zero
- A prompt with no stored vector says so, rather than returning an empty list that
  reads as "nothing is similar"
- Nothing similar is stated as a finding — an isolated prompt means the memory had
  nothing to offer, which is information
- The two lookups fail independently of the answer and of each other

---

## Subtasks

### 12.1 — Attribution

- [x] `machine` on `ExchangeIn`, max 128 chars, optional
- [x] `gateway.store_exchange(machine=…)` → Chroma metadata, omitted when absent
- [x] `bb_exchange.py`: `machine_name()`, `os.uname().nodename` with a
      `socket.gethostname()` fallback for Windows, overridable with `BB_MACHINE`
- [x] `tests/test_ext.py` — stored when sent, absent when not, 422 when overlong

### 12.2 — Reading the corpus

- [x] `chroma.get_documents(with_documents=False)` — metadata-only reads
- [x] `brownbear/prompts.py`: `listing()`, `detail()`, `related()`
- [x] `_newest_first()` — two passes, so a missing date sorts last rather than first
- [x] `tests/test_prompts.py` — 20 assertions

### 12.3 — API

- [x] `GET /api/prompts`, `/api/prompts/{id}`, `/api/prompts/{id}/related`
- [x] Declared in `api_contract.py` under a new **Prompt Palace** group
- [x] Edge allowlist: the page and the API, GET-only, with the long timeout on the
      API because expanding a prompt runs two vector searches

### 12.4 — The page

- [x] `/prompts` with `AutoRefresh`, four stat tiles, and the truncation notice
- [x] `PromptPalace.tsx` — list, answer, and the two neighbour panes
- [x] Nav entry "Prompt Palace"
- [x] `Score` and `Attribution` — the two honesty rules, in one place each
- [x] Styles in `files.css`; no new colour, size or spacing token
- [x] `PromptPalace.test.tsx` — 16 assertions

---

## Acceptance Criteria

- [x] A prompt reported with a machine name shows it; one without shows "not
      recorded", and never the host serving the page
- [x] `machine=unattributed` finds exactly the prompts with no machine
- [x] The listing issues no request that fetches answers
- [x] The newest prompt is first; an undated one is last
- [x] A capped scan reports `truncated`, and the page states that the newest prompt
      may be missing
- [x] Every neighbour carries its score and the cutoff; one above the cutoff *and*
      cacheable is marked "would hit", and one above it but volatile is not
- [x] In a non-cosine collection every neighbour reads "cannot be scored", no `0`
      appears, and no row is hidden
- [x] A knowledge chunk renders as a quoted passage inside a non-interactive row
- [x] A failed similarity lookup leaves the answer on screen and says the answer is
      unaffected
- [x] Nothing published that was not meant to be: the API is GET-only at the edge,
      and `check_edge_contract.py` agrees with all 57 declared endpoints
- [ ] **Owed: browser verification.** Every criterion above is asserted against
      happy-dom, which has no layout engine. What it cannot see: whether the score
      chips are legible in both themes, whether a 200-prompt list scrolls well, and
      whether the auto-refresh interval feels right for a prompt arriving from
      another machine

---

## Implementation Notes

- **The listing sorts descending, which a single sort key gets wrong.**
  `reverse=True` over a `(has_date, timestamp)` key flips the undated group to the
  top — the opposite of what a missing date should mean. Two passes instead: dated
  rows sorted descending, undated appended. The first version had this backwards
  and the test caught it.
- **A path parameter needs `Path`, not `Query`.** FastAPI asserts on it at import
  time: `Cannot use `Query` for path param`. The whole app fails to boot, which is
  at least a loud failure.
- **`with_documents=False` was a connector change, not a filter.** Chroma's
  `include` decides what comes back over the wire; filtering after the fact would
  have transferred every answer and then thrown them away.
- **`would_hit` is two conditions, not one.** A score above the cutoff is not a hit
  if the entry is not cacheable — which is exactly the case the flag exists for. A
  single-condition badge would claim a hit that the gateway would refuse.
- **The edge matches the id as `[^/]+`, not `x_<hex>`.** `check_edge_contract.py`
  probes declared paths literally, so a regex pinned to hex would not match
  `/api/prompts/{exchange_id}` and would read as drift. The router pins the format
  instead and answers 422, which is the layer that can say why.
- **The graph's 0.60 floor is wrong for prompts, and wrong in the direction that
  looks like an empty corpus.** Measured against the live stack — 140 conversations,
  1642 knowledge chunks, nomic-embed-text — a prompt's nearest genuine neighbour
  scores 0.52–0.56, not the 0.66–0.69 BB-301 measured between documents. Shipped at
  0.60 the panel said "nothing else in the corpus resembles this prompt" about a
  prompt with a real neighbour at 0.558. Lowered to 0.50, and the number is in the
  module with the measurement beside it so the next person does not inherit it
  blind. This was caught by querying the live corpus after deploying, not by any
  test — every test fixture supplies its own distances.
- **A new contract group must be added to `GROUPS`.** Two tests fail otherwise, and
  they are right to: an undeclared group renders in an undefined position.

---

## Open questions

- **Attribution is unverifiable until G2.** Per-machine credentials at the edge
  would make `machine` a fact instead of a claim, and would let the page show
  *which* machine a prompt could not have come from. Until then every surface has
  to keep saying "reported".
- **`machine` is not filterable inside Chroma.** The scan filters in Python, which
  is fine at a few hundred exchanges and wrong at a hundred thousand. A `where`
  clause on the metadata would push it down to Chroma, at the cost of not being
  able to offer the machine list and the rows from one read.
- **Near-misses are visible per prompt but not aggregated.** "Every prompt within
  0.02 of the cutoff" is the query that would actually retune the threshold, and it
  is a different page — spec 005 §5.7 already owes queryable near-misses.

---

## Delivered

**2026-08-21.** All of 12.1–12.4. One optional contract field, one connector
parameter, one backend module, three endpoints, one page, one component, two edge
allowlist entries, and 39 new assertions (20 prompts, 3 exchange, 16 component).
Backend 446 passed; frontend 167 passed; `check_edge_contract.py` clean at 57
endpoints; `/prompts` compiles through the deployment image.

Found by writing it rather than by planning it: the descending sort's undated group,
and that `machine` had to be *omitted* rather than written as `""` — "not recorded"
and "reported as blank" are different facts, and only one of them is true.

Still owed: someone opening the page in a browser, and redeploying the hook on each
connected machine before any prompt carries a name.
