<!--
Bug report template. Copy, don't edit in place:

    cp TEMPLATE.md BB-<id>-short-slug.md

A bug file is a record of a wrong belief, not just a broken line. The Root cause
section is worth more than the Fix section — write down what the symptom
suggested as well as what was actually wrong, because the gap between those two
is the reusable part. See spec 005's blocker 1 for the house example: a 501
saying "Start it with --embeddings" was not a missing server flag at all.

Sections marked OPTIONAL earn their place or get deleted.
-->

# Bug: <One line, the symptom — not the suspected cause>

**Status:** Open
**Severity:** <Critical | High | Medium | Low> — <blast radius: who or what is affected>
**Points:** <n>
**Branch:** `fix/<id>-<short-slug>`
**Date:** <YYYY-MM-DD>
<!-- OPTIONAL:
**Regression in:** <commit | spec | version that introduced it>
**Blocks:** <ticket ids>
-->

---

## Symptom

<What is observed, in the reporter's terms. Verbatim error text in a fence —
paraphrased errors are unsearchable. Say how often: always, intermittently, or
once. "Intermittently" is itself a clue and must not be smoothed away.>

```
<exact error output, log line, or status code>
```

---

## Context

<!-- Everything needed to work this bug, restated here. A competent
implementer — human or LLM — opens this file and nothing else. -->

**Reads required:** this file only.

| Fact | Value |
|---|---|
| Component | `<service / module / file>` |
| Environment | `<host, container, browser, version>` |
| Reachable via | `<url or command>` |
| Auth | `<header form, if any>` |
| First seen | `<YYYY-MM-DD>` |

---

## Reproduction

<!-- Numbered, from a known-clean start, with the commands inline. If it cannot
be reproduced on demand, say so explicitly and record the conditions under which
it appeared — an unreproducible bug documented honestly is more useful than a
confident guess. -->

1. <Step>
   ```bash
   <command>
   ```
2. <Step>

**Expected:** <what should happen>
**Actual:** <what happens instead>

---

## Root cause

<!-- Fill in when known; leave the "Not yet diagnosed" line until then rather
than speculating in a way that later reads as fact. Name the mechanism, not the
symptom. -->

**Not yet diagnosed.**

<!-- When diagnosed, replace with:
**<The mechanism, in one bold clause.>** <What the symptom suggested, why that
reading was wrong, and what was actually happening.>
-->

---

## Fix

- [ ] <Change, naming the file and the behaviour that changes>
- [ ] <Anything that must change with it: migration, config, edge allowlist entry>

### Regression test

<!-- Non-optional for anything that reached a running service. A fix with no
test is a fix that comes back. Name the test file and what it asserts. -->

- [ ] `<tests/test_x.py::test_name>` — <asserts what, and would have failed before>

---

## Acceptance Criteria

- [ ] The reproduction above no longer produces the symptom
- [ ] The regression test fails on the unfixed code and passes on the fix
- [ ] <What must stay unchanged — the behaviour a careless fix would break>
- [ ] <How the component behaves now when the same input goes wrong again>

---

## Implementation Notes

<!-- OPTIONAL. Traps found on the way: a library default that is wrong for us, a
misleading error string, a place the same mistake is waiting to be made again. -->

- **<Topic>:** <what to know>
