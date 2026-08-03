# Brown Bear Design Guide

**Status:** Active
**Scope:** Universal — every surface in this project, current and future
**Date:** 2026-08-03
**Companion:** [DESIGN-BOOK.md](DESIGN-BOOK.md) — the machine-readable spec. This
file is the *why*; the book is the *what*.

---

## What this guide is for

Brown Bear is an AI system with a user interface, and those are harder to design
than either half suggests. The interface reports on things that are probabilistic
(a semantic cache hit at cosine 0.95), partial (token metering that depends on a
remote client choosing to report), and silently absent (hooks that fail open and
produce nothing at all). A conventional dashboard design language has no opinion
about any of that. This guide supplies one.

Two sources, doing different jobs:

- **[The People + AI Guidebook](https://pair.withgoogle.com/guidebook/) (Google
  PAIR)** — the principles. It governs *what we show and how we frame it*: when
  to show confidence, how to explain a machine decision, how to fail visibly.
- **[Material Design 3](https://m3.material.io/)** — the component system. It
  governs *what things look like and how they behave*: color roles, type scale,
  elevation, states, motion, touch targets.

They do not conflict, because they operate at different layers. Where they seem
to, PAIR wins: Material will happily render a confident-looking number that PAIR
says we have no right to display.

---

## Part 1 — PAIR principles, applied to Brown Bear

The Guidebook's six chapters, each reduced to the rules this project actually has
to follow. The rules are not paraphrases of Google's text; they are what its
chapters imply for *this* stack.

### 1. User needs + defining success

PAIR's first question is whether AI belongs in the solution at all — augment
where the user benefits from a probabilistic assist, automate only where being
wrong is cheap.

- **Do not use the semantic cache where determinism is available.** A token
  count, a collection size, a health status are facts. Render them as facts. The
  cache exists for one job — reusing prior answers — and must not leak into
  surfaces that have exact answers.
- **Define success asymmetrically.** For this system a false positive (a wrong
  cache hit shown as an answer) costs far more than a false negative (a miss the
  user never sees). Every design tradeoff resolves in favour of the miss.
- **Success is not the hit rate.** A UI that celebrates hit rate optimises the
  wrong thing. Report hit rate beside its risk: threshold, score distribution,
  and how many hits were near the cutoff.

### 2. Data + collection and evaluation

Data is a design material, and its provenance is part of the interface.

- **Label the source of every number.** This stack has three kinds: measured
  locally (the Ollama proxy counts its own tokens), *reported* by a remote client
  (spec 005's `/ext/exchange`, which is the only party that sees the Anthropic
  response), and derived (aggregations, cost estimates from a price table).
  These are not equally trustworthy and must not share a visual treatment.
- **Reported data is a claim, not a measurement.** A remote machine can under-
  report by setting `BB_NO_STORE=1` or simply not running the hook. Surfaces that
  total tokens across sources must say so.
- **Show the corpus honestly.** Retrieval quality is bounded by what is in
  `conversations` and `knowledge`. An empty collection is a fact the user needs,
  not an empty state to decorate.

### 3. Mental models

Users arrive with expectations, and the fastest way to lose trust is to violate
one silently.

- **Never let the two collections blur.** A cache hit is a *prior answer*;
  retrieval is *supporting context*. They come from separate collections at
  separate thresholds by design, and the UI must keep that distinction visible —
  a mixed presentation invites exactly the failure the split was built to
  prevent.
- **Explain the benefit, not the mechanism.** "Answered from a previous
  conversation" lands; "cosine similarity 0.9731 against collection
  `conversations`" is for the detail view, not the headline.
- **Do not anthropomorphise.** Brown Bear retrieves and meters. It does not
  "think", "know", or "understand". Copy that implies otherwise sets an
  expectation the system cannot meet.

### 4. Explainability + trust

The chapter's hardest lesson: showing confidence can *reduce* calibration if the
number is presented without its consequence.

- **A cache hit must always carry its evidence.** Score, the matched prior
  prompt, and its age. A hit shown without the prompt it matched is unfalsifiable
  by the user — they cannot tell a good hit from a bad one, which is the only
  judgement that matters here.
- **Explain the cutoff, not just the score.** `0.95` means nothing alone. Show
  where this hit sits relative to the threshold.
- **Cosine only.** Similarity is comparable to a 0.95 cutoff only in cosine
  space; the codebase returns `None` for any other space rather than serving a
  meaningless number. The UI must render that `None` as "cannot be scored" — never
  as `0`, and never by hiding the row.
- **Never present a retrieved chunk as an answer.** Provenance formatting is not
  decoration; it is the guardrail.

### 5. Feedback + control

- **The user must be able to reject a hit.** `BB_CACHE_MODE=block` returns a
  cached answer *instead of* calling Claude — the one mode where a wrong hit is
  shown as though it were the real answer. Any surface that can produce that
  needs a visible, one-action escape.
- **Make the control's effect legible.** Changing the threshold or TTL changes
  future behaviour; say what it will affect before it is saved.
- **Settings are read-only remotely, by design.** The edge allows `GET
  /api/settings` and denies `PUT`. The UI must render this as a deliberate
  boundary — a disabled control with a stated reason, not a control that fails
  when pressed.
- **Prefer implicit feedback the user already generates.** Hits used versus hits
  dismissed is a better signal than a thumbs-up widget nobody touches.

### 6. Errors + graceful failure

This is where Brown Bear's real risk lives, because its default failure is
*silence*.

- **Distinguish "nothing to show" from "not working".** The client hooks fail
  open: an unreachable gateway, a wrong token, a timeout and a genuine no-match
  all produce no output. An empty panel is therefore ambiguous, and the UI must
  resolve the ambiguity — last successful contact, last error, and when it was
  checked.
- **Never let an error page be the only signal.** A silent misconfiguration can
  persist for days. Surfaces that depend on remote clients must show liveness,
  not just data.
- **Degrade, don't block.** Brown Bear being down should cost context, not work.
  Panels fail independently; one dead connector must not blank a page.
- **Name the three error kinds separately** — system (a connector is down), user
  (a malformed input), and context (the corpus is empty, the model changed, the
  vectors are stale). They need different words and different recovery paths.

---

## Part 2 — Material Design 3 as the component system

M3 supplies the component layer. Adopt it as a system rather than a look: take
its token architecture, states, and accessibility floors, not just its rounded
corners.

**What we adopt**

- **Color by role, never by literal.** Components reference `primary`,
  `on-primary`, `surface`, `surface-container`, `outline`, `error` — never a hex.
  The theme is generated from one seed via M3 tonal palettes, so a reseed is a
  one-line change instead of a find-and-replace.
- **The type scale as-is.** Display / headline / title / body / label at large /
  medium / small. Nine roles is enough; a tenth size is a smell.
- **State layers, not custom hovers.** Hover, focus, pressed and dragged are
  fixed opacity layers over the base color. This is what makes an unfamiliar
  control feel predictable.
- **Elevation as hierarchy.** Levels 0–5 express layering, not decoration. A
  dashboard needs about three.
- **The 48dp touch target floor**, and the 4dp/8dp spacing grid.
- **Motion with intent.** M3's emphasized and standard easing sets, short
  durations, and a hard rule: nothing animates a number the user is trying to
  read.

**Where PAIR overrides M3**

- **Confidence is never a bare progress bar.** M3's linear indicator invites
  reading a similarity score as a completion percentage. Score gets its own
  treatment, with the threshold marked.
- **Status color is reserved and always paired.** M3 has `error`; this project
  needs four states (good / warning / serious / critical), each shipping with an
  icon *and* a label so meaning never rests on hue.
- **Snackbars do not carry AI failures.** A transient toast is the wrong vehicle
  for "the gateway has been unreachable for two days" — a dismissible transient
  is exactly how silent failure stays silent.

**Where M3 gets out of the way**

Charts are not M3 components. The chart layer has its own validated palette,
kept deliberately separate from the theme so a reseed cannot repaint a series or
let a series color impersonate a status. See the Design Book's chart section — and
note that the current Jinja dashboard already implements this correctly, so the
Next.js port carries it over rather than redesigning it.

---

## Part 3 — Non-negotiables

The short list. Everything above is reasoning; these are the rules.

1. A cache hit is never shown without its score, its matched prompt, and its age.
2. An unscoreable similarity renders as "cannot be scored", never as `0`, never
   hidden.
3. Empty and broken are visually distinct states, always.
4. Every number carries its provenance: measured, reported, or derived.
5. Status meaning never rests on color alone — icon plus label, every time.
6. Charts: legend present for ≥2 series, a table twin always, text never wears a
   series color.
7. Remote write paths are shown as deliberately disabled, with the reason.
8. Panels fail independently. One dead connector never blanks a page.
9. No component invents a color, a type size, or a spacing value outside the
   token set.
10. Copy does not claim the system thinks, knows, or understands.

---

## Reading order for a new contributor

1. This file, Part 3 first — the ten rules are most of the value.
2. [DESIGN-BOOK.md](DESIGN-BOOK.md) for the concrete values and component specs.
3. The PAIR Guidebook chapter matching whatever you are building, if it touches
   cache, retrieval, or metering.
