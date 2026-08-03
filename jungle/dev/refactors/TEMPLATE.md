<!--
Refactor template. Copy, don't edit in place:

    cp TEMPLATE.md BB-<id>-short-slug.md

A refactor changes shape while holding behaviour still. That makes the
"Behaviour contract" section the load-bearing one: it is the list of things that
must be identical before and after, and it is what makes the change reviewable at
all. If behaviour is meant to change too, this is not a refactor — write it as a
feature and say so.

Sections marked OPTIONAL earn their place or get deleted.
-->

# Refactor: <What changes shape>

**Status:** Open
**Priority:** <High | Medium | Low> — <the cost of leaving it as is>
**Points:** <n>
**Branch:** `refactor/<id>-<short-slug>`
**Date:** <YYYY-MM-DD>
<!-- OPTIONAL:
**Depends on:** <ticket id> — <what must land first>
**Removes:** <files, deps, tables, or routes this deletes>
-->

---

## Overview

<What is being restructured and why now. Name the concrete pain: a change that
touches four files where it should touch one, a dependency kept alive for one
call site, two code paths that must be edited in lockstep. Avoid "cleaner" as a
justification on its own — say what becomes possible or cheaper afterwards.>

---

## Context

<!-- Everything needed to execute this ticket, restated here. A competent
implementer — human or LLM — opens this file and nothing else. -->

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Files in scope | `<paths>` |
| Call sites | `<who depends on this today>` |
| Test coverage today | `<file, or "none" — say so plainly>` |
| Routes / ports affected | `<values>` |

---

## Behaviour contract

<!-- What must be observably identical afterwards. This is the whole safety
argument for the change: every line here is something a reviewer can check. Be
concrete — status codes, response shapes, header names, ordering, defaults. -->

Unchanged after this refactor:

- [ ] `<METHOD /path>` returns the same shape and status codes
- [ ] <Ordering, defaults, or timing that callers already rely on>
- [ ] <What stays denied / unauthenticated / private>

Deliberately changed:

- <Anything that does change, and who has to be told. An empty list here is a
  good sign; a long one means this is a feature.>

---

## Current shape → target shape

<!-- OPTIONAL, but a short before/after is usually the fastest way to convey the
change. Trees, not prose, when the change is structural. -->

```
before                          after
<path/thing.py>          ──►    <path/thing/>
  <what it holds>                 <split>
```

---

## Subtasks

### <N>.1 — <Make the new shape exist alongside the old>

- [ ] <Additive step: nothing deleted yet>

### <N>.2 — <Move call sites over>

- [ ] <Per call site, or per module>
- [ ] <Verification that both paths agree, if they coexist>

### <N>.3 — <Delete the old shape>

- [ ] <Remove the dead path, the dep, the route, the table>
- [ ] <Confirm nothing references it: grep, and say what you grepped for>

---

## Migration & rollback

<!-- How this lands without a broken intermediate state, and how it is undone.
Say whether the change is reversible by `git revert` alone — if a migration, a
dropped table, or a rebuilt container image is involved, it is not. -->

- **Lands as:** <one commit | additive-then-cutover across N commits>
- **Rollback:** <what undoes it, and what that does not undo>
- **Data:** <migration required? destructive? reversible?>

---

## Acceptance Criteria

- [ ] Every line of the behaviour contract verified, not assumed
- [ ] Existing tests pass unmodified — <or name the tests changed, and why the
      change is not a weakened assertion>
- [ ] <Nothing references the removed shape: the grep, and its result>
- [ ] <Deleted: the dep / route / file that was the point of the exercise>

---

## Implementation Notes

<!-- OPTIONAL. Order-of-operations traps, coupling discovered mid-change, things
the next person will assume wrongly. -->

- **<Topic>:** <what to know>
