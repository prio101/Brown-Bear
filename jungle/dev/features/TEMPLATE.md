<!--
Feature spec template. Copy, don't edit in place:

    cp TEMPLATE.md 006-your-feature-slug.md

Numbering is sequential across this directory; 000 is the roadmap. Add the new
spec to 000-roadmap.md (Status table + dependency graph + a phase) in the same
commit — a spec the roadmap does not mention gets forgotten.

Sections marked OPTIONAL earn their place or get deleted. Do not leave an empty
heading behind: a spec with a hollow "Flow" section reads as unfinished rather
than as not-applicable.
-->

# Feature: <Name>

**Status:** Open
**Priority:** <High | Medium | Low> — <why, when the ranking is not self-evident>
**Points:** <n>
**Branch:** `feat/<id>-<short-slug>`
**Date:** <YYYY-MM-DD>
<!-- OPTIONAL metadata — keep only the lines that are true:
**Depends on:** spec <NNN> — <what specifically is needed from it>
**Reorders:** <what this pushes ahead of or behind, and why>
**Supersedes:** spec <NNN> §<n.m>
-->

---

## Overview

<Two or three sentences: what this builds, and what it is for. Name the thing
that becomes possible once it ships. State what it deliberately does NOT do —
the boundary is usually more informative than the feature list, e.g. "Brown Bear
never calls Anthropic; the API key stays on the client.">

---

## Context

<!-- Everything needed to execute this ticket, restated here. The rule: a
competent implementer — human or LLM — opens this file and nothing else. Copy
the port, the endpoint, the header, the path. A cross-reference like "see spec
005" is a context load; an inlined fact is not. Duplication across tickets is
the intended cost. -->

**Reads required:** this file only.

| Fact | Value |
|---|---|
| <Service / port> | `<value>` |
| <Endpoint touched> | `<METHOD /path>` → `<shape>` |
| <Auth> | `<header form>` |
| <Files to change> | `<path>` |

<Any single constraint that would otherwise have to be inferred from another
document — a threshold, a default that is wrong for us, a route that is denied
at the edge.>

---

## Flow

<!-- OPTIONAL. Include when the feature spans more than one process, machine or
network boundary — that is exactly where prose stops being precise. Delete for
self-contained work. ASCII, numbered steps, request shapes on the arrows. -->

```
Client                           boundary              Brown Bear
   │                                │
   │ 1. POST /path ─────────────────►│──► what happens
   │    {field, field}               │    │
   │ ◄───────────────────────────────│    └─► branch ─► outcome
   │   {response shape}                   → what the client does with it
```

<A sentence on the step that carries the real constraint — the one a reader
would otherwise get wrong.>

---

## Decisions (locked)

<!-- OPTIONAL but strongly preferred once anything has been settled. This table
is what stops a decision being silently relitigated three weeks later. The
Consequence column is the point: a choice with no stated cost is not a decision,
it is a preference. -->

| Decision | Choice | Consequence |
|---|---|---|
| <the question that had to be answered> | **<what was chosen>** | <what this now forces, breaks, or requires downstream> |

### <Sub-decision that needs an argument, not a row>

<!-- OPTIONAL. Use when a table cell cannot carry the reasoning — e.g. 005's
"Two collections, never one". State the failure mode the decision prevents. -->

---

## Blockers

<!-- OPTIONAL. Anything that must be true before this spec can start. Strike
through and annotate as they clear, rather than deleting — a cleared blocker
records what was actually wrong, which is often not what it looked like:

1. ~~**Short name.**~~ **Cleared <date>, and the diagnosis was wrong.** <What
   the symptom suggested, what it actually was, what fixed it.>
2. **Short name.** <Still open: what specifically is needed, and from whom.>
-->

---

## Requirements

<!-- What must be true of the finished thing, grouped by concern. Behaviour and
constraints, not tasks — tasks go in Subtasks. Plain bullets, no checkboxes:
requirements are not worked through, they are satisfied. Lead each group with
its non-negotiable where one exists. -->

### <Concern>

- <Observable behaviour, specific enough to disagree with>
- <Constraint, with the number in it: threshold, limit, timeout, default>
- <Failure mode that is explicitly out of bounds>

### <Concern>

- <...>

---

## Subtasks

<!-- The work, in dependency order. `N.M` where N is this spec's number, so
references like "spec 005 §5.6" resolve across documents. Checkboxes here are
the live progress record — tick them as work lands. Name the module, table,
class or endpoint being created; a subtask that does not say what it produces
cannot be verified as done. -->

### <N>.1 — <Foundation: the thing everything else needs>

- [ ] Create `<path/to/module>/`
- [ ] `<ClassName>` — <responsibility in one clause>:
  - <sub-point when the class has distinct parts>
- [ ] <Verification step for this subtask specifically>

### <N>.2 — Database Schema

- [ ] `<table_name>` table:
  - `id`, `<column>` (`<enum|values>`)
  - `<column>`, `<column_json>`
  - `created_at`, `<timestamps>`
- [ ] Alembic migration

### <N>.3 — API Endpoints

- [ ] `<METHOD> /api/<path>` — <what it does>
- [ ] `<METHOD> /api/<path>` — <what it does>
<!-- Anything reachable through the tunnel also needs an entry in
edge/nginx.conf.template — the edge default-denies, so an endpoint that is not
allowlisted there is invisible remotely. Note the method: the edge pins it. -->

### <N>.4 — Dashboard Integration

- [ ] <Page or panel>:
  - <the numbers it shows>
- [ ] <Control, and whether it needs a confirmation dialog>

---

## Acceptance Criteria

<!-- The checklist that decides "done". Each line independently checkable by
someone who did not write the code — an outcome, not an implementation detail.
If a criterion cannot be tested without reading the source, rewrite it. Include
the negative cases: what must NOT happen, what must stay denied, what must
degrade rather than fail. -->

- [ ] <Observable outcome under normal input>
- [ ] <Correct behaviour at the boundary: empty, missing, oversized, concurrent>
- [ ] <What stays unreachable / unchanged / denied>
- [ ] <How it degrades when a dependency is down>
- [ ] <The number is right: cost, count, threshold, token total>

---

## Implementation Notes

<!-- Decisions a reader would otherwise have to rediscover, and the traps.
Bold-key form. Prefer notes that save someone an hour: library quirks, defaults
that are wrong for us, why the obvious approach fails. -->

- **<Topic>:** <the specific choice, and the version or number that matters>
- **<Trap>:** <what looks correct but is not, and what to do instead>
- **<Dependency>:** <what it defaults to, and why we override it>

---

## Open questions

<!-- OPTIONAL, and better present than pretended-away. Anything unresolved that
does not block starting. Move each one into Decisions (locked) as it settles,
rather than answering it here — the table is the record. -->

- <Question, and what the answer would change>
