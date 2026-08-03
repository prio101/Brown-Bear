# Brown Bear Design Book

**Status:** Active — v1.0
**Date:** 2026-08-03
**Audience:** implementers, human and LLM
**Companion:** [DESIGN-GUIDE.md](DESIGN-GUIDE.md) — the principles and their
reasoning. This book is the specification: concrete values, no argument.

---

## 0. How to use this book

This file is written to be executed, not interpreted. It is the single source of
truth for every visual and behavioural decision in a Brown Bear interface.

**Contract for an implementing agent:**

1. Values in this book are **normative**. Never substitute a "close enough" hex,
   size, or duration.
2. **MUST / NEVER** are hard rules — a violation is a bug, not a style
   preference. **SHOULD** allows a documented exception.
3. If this book does not cover a case, derive from the nearest documented
   pattern and add the new case here in the same change. Do not invent
   silently.
4. Where this book and Material Design 3 differ, **this book wins** — the
   differences are deliberate and annotated.
5. Never introduce a color, type size, spacing value, or radius outside §2–§6.

**Machine-readable token export:** §12.

---

## 1. System summary

| Layer | Choice | Notes |
|---|---|---|
| Principles | Google PAIR (People + AI Guidebook) | see DESIGN-GUIDE Part 1 |
| Components | Material Design 3 | token-based, role-referenced |
| Framework | Next.js (App Router) + React | sprint-1 |
| Charts | hand-rolled inline SVG | no charting library; see §9 |
| Theming | M3 tonal palette from one seed | generated, not hand-authored |
| Modes | light + dark, both explicitly designed | dark is not an inversion |

---

## 2. Color

### 2.1 Theme colors (M3 roles)

The UI theme is **generated** from a single seed with
[`@material/material-color-utilities`](https://github.com/material-foundation/material-color-utilities)
at build time.

```
seed:   #7A5230        /* brown — the project's namesake */
scheme: M3 tonal palettes (primary, secondary, tertiary, neutral,
        neutral-variant, error), light + dark
```

MUST reference roles, NEVER literals:

```
primary            on-primary            primary-container      on-primary-container
secondary          on-secondary          secondary-container    on-secondary-container
tertiary           on-tertiary           tertiary-container     on-tertiary-container
error              on-error              error-container        on-error-container
surface            on-surface            surface-variant        on-surface-variant
surface-container-lowest / low / (base) / high / highest
outline            outline-variant       inverse-surface        scrim
```

NEVER hand-author tonal values. Regenerating from the seed is the only supported
way to change theme color. A reseed MUST NOT alter §2.2 or §2.3.

### 2.2 Chart surfaces (fixed, not themed)

Charts render on fixed neutral surfaces, independent of the generated theme:

| Role | Light | Dark |
|---|---|---|
| Chart surface | `#fcfcfb` | `#1a1a19` |
| Page plane | `#f9f9f7` | `#0d0d0d` |

**Why fixed:** the series palette in §2.3 is validated for contrast *against
these exact surfaces*. A theme-tinted chart surface invalidates that validation.
Changing either value MUST be accompanied by a re-run of the palette validator
and an update to §9.1.

### 2.3 Chart ink and chrome

| Role | Light | Dark |
|---|---|---|
| Primary ink | `#0b0b0b` | `#ffffff` |
| Secondary ink | `#52514e` | `#c3c2b7` |
| Muted (axis/labels) | `#898781` | `#898781` |
| Gridline (hairline) | `#e1e0d9` | `#2c2c2a` |
| Baseline / axis | `#c3c2b7` | `#383835` |
| Delta ↑ good | `#006300` | `#0ca30c` |
| Border (hairline ring) | `rgba(11,11,11,0.10)` | `rgba(255,255,255,0.10)` |

### 2.4 Status palette (reserved — never themed, never a series)

| Role | Hex | Use |
|---|---|---|
| good | `#0ca30c` | healthy, connected, within budget |
| warning | `#fab219` | degraded, approaching a limit |
| serious | `#ec835a` | stale data, unreachable client |
| critical | `#d03b3b` | connector down, destructive confirmation |

MUST ship with an **icon and a text label**. NEVER color alone. On the light
surface `warning` (1.79:1) and `serious` (2.57:1) are sub-3:1 by design — the
icon+label pairing is the mitigation, not an oversight.

NEVER reuse a status color as a chart series color.

---

## 3. Typography

Type roles are M3's scale, unmodified. Font stack:

```
--bb-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
```

| Role | Size / line-height | Weight | Tracking |
|---|---|---|---|
| display-large | 57 / 64 | 400 | -0.25 |
| display-medium | 45 / 52 | 400 | 0 |
| display-small | 36 / 44 | 400 | 0 |
| headline-large | 32 / 40 | 400 | 0 |
| headline-medium | 28 / 36 | 400 | 0 |
| headline-small | 24 / 32 | 400 | 0 |
| title-large | 22 / 28 | 400 | 0 |
| title-medium | 16 / 24 | 500 | 0.15 |
| title-small | 14 / 20 | 500 | 0.1 |
| body-large | 16 / 24 | 400 | 0.5 |
| body-medium | 14 / 20 | 400 | 0.25 |
| body-small | 12 / 16 | 400 | 0.4 |
| label-large | 14 / 20 | 500 | 0.1 |
| label-medium | 12 / 16 | 500 | 0.5 |
| label-small | 11 / 16 | 500 | 0.5 |

Units are px. NEVER add a size outside this scale.

**Numerals.** Large standalone figures (stat-tile values, hero numbers) use
default proportional figures. `font-variant-numeric: tabular-nums` is reserved
for values that must align vertically: table columns and axis ticks.

---

## 4. Spacing, shape, elevation

**Spacing** — 4px base grid, 8px preferred rhythm:
`4, 8, 12, 16, 24, 32, 48, 64`. NEVER an off-grid value.

**Shape** (M3 scale, px): `none 0 · extra-small 4 · small 8 · medium 12 ·
large 16 · extra-large 28 · full 9999`

| Element | Radius |
|---|---|
| Card, panel | medium (12) |
| Button, chip, input | full / small per variant |
| Dialog, sheet | extra-large (28) |
| Chart data-end cap | 4 (see §9.2) |

**Elevation** (M3 levels → dp): `0 · 1 · 3 · 6 · 8 · 12`

This dashboard uses three: **0** page plane, **1** cards and panels, **3**
menus/dialogs/raised. Levels 4–5 are unused; introducing one requires a note
here.

---

## 5. State layers

Interactive components MUST express state as a fixed-opacity layer of the
relevant `on-*` color over the base:

| State | Opacity |
|---|---|
| hover | 8% |
| focus | 10% |
| pressed | 10% |
| dragged | 16% |
| disabled (content) | 38% |
| disabled (container) | 12% |

**Focus visibility is non-negotiable.** Every interactive element MUST have a
visible focus indicator: a 3px `primary` ring at 2px offset. NEVER
`outline: none` without a replacement.

---

## 6. Motion

| Token | Duration |
|---|---|
| short-1 … short-4 | 50 / 100 / 150 / 200 ms |
| medium-1 … medium-4 | 250 / 300 / 350 / 400 ms |
| long-1 … long-4 | 450 / 500 / 550 / 600 ms |

| Easing | Curve |
|---|---|
| standard | `cubic-bezier(0.2, 0, 0, 1)` |
| emphasized-decelerate | `cubic-bezier(0.05, 0.7, 0.1, 1.0)` |
| emphasized-accelerate | `cubic-bezier(0.3, 0.0, 0.8, 0.15)` |

Rules:

- NEVER animate a number the user is reading. Counting-up animations on token
  totals are prohibited.
- Chart entry animation: `medium-2` at most, opacity and scale only, NEVER a
  value tween that shows wrong intermediate numbers.
- MUST honour `prefers-reduced-motion: reduce` — drop to opacity-only or none.

---

## 7. Layout

| Breakpoint | Width | Navigation |
|---|---|---|
| compact | < 600px | bottom bar |
| medium | 600–1023px | navigation rail |
| expanded | ≥ 1024px | navigation rail (labelled) |

- Content max width `1440px`, centered; gutters `16px` compact, `24px` medium+.
- Dashboard grid: 12 columns, `24px` gap at expanded.
- Panel minimum height is fixed per panel type so a loading or error state does
  not reflow the page.

---

## 8. Component inventory

M3 components, with the project's constraints. Each MUST support: default,
hover, focus, pressed, disabled, loading, empty, error.

| Component | M3 variant | Brown Bear rules |
|---|---|---|
| Button | filled / filled-tonal / outlined / text | one filled button per view; destructive actions are outlined + `critical`, never filled |
| Icon button | standard / toggle | 48dp min target even at 24dp icon |
| Card | elevated (level 1) | the panel primitive; owns its own error state |
| Chip | assist / filter / input | filter chips carry the active dimension |
| Text field | outlined | outlined only, for density consistency |
| Select / combobox | menu | dimension filters (§9.5) |
| Switch | — | settings only; NEVER for a destructive toggle |
| Dialog | basic / full-screen | destructive confirmation MUST name the object and the count |
| Snackbar | — | transient success only. NEVER an AI or connector failure (see §11) |
| Banner (custom) | — | persistent failures. Not an M3 component; specified in §11 |
| Navigation rail | — | primary nav at medium+ |
| Navigation bar | — | primary nav at compact |
| Data table | — | tabular-nums, sortable headers, sticky header, the chart table twin (§9.6) |
| Progress indicator | linear / circular | NEVER for a similarity score (§10.2) |
| Tooltip | plain / rich | rich for provenance detail |

### 8.1 Stat tile

The dashboard's most-used primitive. A single number with its identity and its
trust context.

```
┌──────────────────────────────┐
│ LABEL                    (i) │  label-medium, muted · info affordance
│ 1,284,392                    │  display-small, proportional figures
│ ↑ 12% vs last 7d             │  body-small; delta color = delta good/bad only
│ ● measured · 2 min ago       │  label-small; provenance badge (§10.1)
└──────────────────────────────┘
```

MUST: label, value, provenance badge, freshness. SHOULD: delta with an explicit
comparison window — a delta without its window is meaningless.
NEVER: a sparkline inside a tile whose value is already the headline, and never a
bare number with no provenance.

---

## 9. Charts

Charts are **not** M3 components. Hand-rolled inline SVG — no charting library.
The existing Jinja implementation (`brownbear/static/charts.js`) is conformant;
the Next.js port MUST preserve its conventions rather than redesign them.

### 9.1 Series palette (validated — do not modify without re-validating)

Assign slots in **fixed order, never cycled**. Color follows the entity, never
its rank: a filter that changes the series count MUST NOT repaint the survivors.

| Slot | Hue | Light | Dark |
|---|---|---|---|
| 1 | blue | `#2a78d6` | `#3987e5` |
| 2 | orange | `#eb6834` | `#d95926` |
| 3 | aqua | `#1baf7a` | `#199e70` |
| 4 | yellow | `#eda100` | `#c98500` |
| 5 | magenta | `#e87ba4` | `#d55181` |
| 6 | green | `#008300` | `#008300` |
| 7 | violet | `#4a3aa7` | `#9085e9` |
| 8 | red | `#e34948` | `#e66767` |

**Validation results** (validated 2026-08-03 against the §2.2 surfaces):

- Adjacent pairs, light: worst CVD ΔE **9.1**, worst normal-vision ΔE **19.6** — pass
- Adjacent pairs, dark: worst CVD ΔE **8.4**, worst normal-vision ΔE **19.3** — pass
- First three slots, all-pairs, light: CVD ΔE **9.2**, normal-vision **24.0** — pass
- Light-mode contrast: aqua (2.74), yellow (2.11), magenta (2.62) fall below 3:1
  → **relief rule applies**: those series MUST carry visible direct labels or the
  table twin. The table twin is mandatory anyway (§9.6), so relief is satisfied
  by default.

**Series cap.** Forms where any two series can appear adjacent (scatter, bubble,
small multiples) are capped at **3 series**; past three, fold into "Other" or
facet. Slots 4+ are for adjacent-only forms (stacked bars, lines, grouped bars).
A 9th series is NEVER a generated hue.

Sequential (magnitude): single hue **blue**, light→dark, `#cde2fb` → `#0d366b`.
Diverging (polarity): **blue ↔ red** with a neutral gray midpoint (`#f0efec`
light / `#383835` dark). NEVER a rainbow; NEVER a hue at the midpoint.

### 9.2 Marks

- Lines 2px; markers ≥8px; bars thin with a **4px rounded data-end** anchored to
  the baseline (the rounded end is the data end only — never both ends).
- **2px surface-colored gap** between adjacent fills (stacked segments and
  neighbouring bars alike); 2px surface ring on overlapping marks.
- Grid and axes recessive: hairline gridlines, muted ticks.
- Direct labels are **selective** — the first, last, and extreme points. NEVER a
  number on every point.
- **Text wears text tokens, never the series color.** A colored mark beside a
  label carries the identity.

### 9.3 Form selection

| Data job | Form |
|---|---|
| single headline value | stat tile (§8.1) — not a chart |
| change over time | line; area only when the total is meaningful |
| magnitude across categories | horizontal bar, sorted by value |
| part-to-whole over time | stacked area/bar (≤4 series) |
| composition, one point in time | stacked bar — NEVER a pie or donut |
| two measures, different scales | two charts — NEVER a dual axis |
| distribution (e.g. hit scores) | histogram, with the threshold marked |

**One axis. NEVER a dual-axis chart.** This is the most consequential chart rule
in the book.

### 9.4 Interaction

Every chart with a plot ships a hover layer by default:

- Line/area: crosshair + tooltip showing all series at that x.
- Bar/dot/cell: per-mark tooltip.
- Hit targets larger than the mark itself.
- Bare stat tiles are the only exception.

### 9.5 Filters

One row of filter controls **above** the charts, never interleaved. Date range as
preset rows (today, last 7 / 30 / 90 days, month-to-date) with custom range
behind a divider. Dimension filters are standard comboboxes.

### 9.6 Accessibility (mandatory per chart)

- Legend present for **≥2 series**; a single series needs none (the title names
  it). At ≤4 series, also direct-label them.
- **A table twin always exists** — same data, reachable and announced, not
  visually hidden with no affordance.
- `role="img"` with a meaningful `aria-label` on the SVG.
- Dark mode uses the §9.1 dark column — *selected steps*, never a filter flip.
- Texture fill available for CVD / print / `forced-colors`: one directional line
  fill at 45° and its 135° mirror, ordered on value scales. Never decorative,
  never on by default.
- Empty state renders the words "No data yet" inside the plot frame, not a blank
  box.

---

## 10. AI-specific components

These have no M3 equivalent. They exist because Brown Bear reports on
probabilistic and partial data, and they are where the PAIR rules become code.

### 10.1 Provenance badge

Every number that is not a local fact carries one.

| Kind | Marker | Meaning |
|---|---|---|
| measured | `●` filled dot | counted locally (e.g. the Ollama proxy) |
| reported | `◐` half dot | claimed by a remote client via `/ext/exchange` |
| derived | `∿` | computed — aggregation, cost estimate from a price table |

MUST include the freshness ("2 min ago"). A totals row combining kinds MUST show
the weakest kind present, and say so in its tooltip.

### 10.2 Similarity score display

NEVER a progress bar — it reads as completion. Use a threshold-marked scale:

```
0.5                    0.95 ┊              1.0
├──────────────────────────┊────●───────────┤
                      threshold  0.973
```

MUST show: the score to 3 decimals, the threshold's position, and whether the
score is above it. An unscoreable similarity (non-cosine collection → `None`
from `gateway.similarity()`) renders as the literal text **"cannot be scored"**.
NEVER `0`, NEVER `—`, NEVER a hidden row.

### 10.3 Cache-hit card

A hit is never shown without its evidence.

```
┌────────────────────────────────────────────────┐
│ ⟳ Answered from a previous conversation        │
│   ┌──────────────────────────────────────────┐ │
│   │ matched: "how do I rotate the edge token"│ │  ← the prior prompt, verbatim
│   │ asked 6 days ago · score 0.973 (≥ 0.95)  │ │
│   └──────────────────────────────────────────┘ │
│   <the cached answer>                          │
│                                                │
│   [ Not what I asked ]          [ Use this ]   │  ← reject is always present
└────────────────────────────────────────────────┘
```

MUST: matched prompt verbatim, age, score with threshold, and a one-action
reject. NEVER present a *retrieved chunk* with this component — retrieval is
supporting context and uses a distinct, clearly subordinate treatment.

### 10.4 Liveness banner

Resolves the empty-versus-broken ambiguity. Persistent, not a snackbar.

States: `healthy` (no banner) · `stale` (serious — last contact > expected
interval) · `unreachable` (critical) · `unknown` (warning — never contacted).

MUST state: what is affected, when it last worked, and one next step. Client
hooks fail open and produce silence on misconfiguration, so absence of data is
never sufficient evidence of health.

### 10.5 Corpus state

Retrieval quality is bounded by the corpus. Collection surfaces MUST show
document count, embedding model, dimension, and distance space per collection. A
non-cosine space MUST be flagged: every score from it is meaningless.

---

## 11. Error and empty states

**Three error kinds, three treatments** — never merged:

| Kind | Example | Treatment |
|---|---|---|
| system | connector down, gateway unreachable | banner (§10.4) + per-panel error |
| user | malformed input, bad range | inline field error |
| context | empty collection, model changed, stale vectors | in-panel explanation with a next step |

Rules:

- **Empty ≠ broken.** Distinct copy, distinct iconography, always.
- **Panels fail independently.** One dead connector NEVER blanks a page.
- Every error state names one next action.
- NEVER a snackbar for a persistent failure — dismissible transients are how
  silent failure stays silent.
- A remotely-denied write (the edge allows `GET /api/settings`, denies `PUT`)
  renders as a **disabled control with its reason stated**, never as a control
  that fails on press.

**Copy rules.** Say what happened, then what to do. No blame, no apology, no
exclamation marks. Never claim the system "thinks", "knows", or "understands".

| Don't | Do |
|---|---|
| "Oops! Something went wrong." | "Couldn't reach ChromaDB. Retried 3× over 40s." |
| "No results!" | "No documents in `knowledge` yet. Ingest one to enable retrieval." |
| "Brown Bear thinks this matches." | "Matches a question you asked 6 days ago." |
| "Error 500" | "The collector failed. Last successful run: 14:02." |

---

## 12. Machine-readable tokens

```json
{
  "version": "1.0",
  "theme": { "seed": "#7A5230", "generator": "material-color-utilities", "scheme": "m3-tonal" },
  "chartSurface": { "light": "#fcfcfb", "dark": "#1a1a19" },
  "pagePlane":    { "light": "#f9f9f7", "dark": "#0d0d0d" },
  "ink": {
    "primary":   { "light": "#0b0b0b", "dark": "#ffffff" },
    "secondary": { "light": "#52514e", "dark": "#c3c2b7" },
    "muted":     { "light": "#898781", "dark": "#898781" },
    "gridline":  { "light": "#e1e0d9", "dark": "#2c2c2a" },
    "axis":      { "light": "#c3c2b7", "dark": "#383835" },
    "deltaGood": { "light": "#006300", "dark": "#0ca30c" }
  },
  "series": {
    "light": ["#2a78d6","#eb6834","#1baf7a","#eda100","#e87ba4","#008300","#4a3aa7","#e34948"],
    "dark":  ["#3987e5","#d95926","#199e70","#c98500","#d55181","#008300","#9085e9","#e66767"],
    "allPairsCap": 3,
    "validated": "2026-08-03"
  },
  "sequential": { "hue": "blue", "from": "#cde2fb", "to": "#0d366b" },
  "diverging":  { "poles": ["blue","red"], "midpoint": { "light": "#f0efec", "dark": "#383835" } },
  "status": { "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b" },
  "spacing": [4, 8, 12, 16, 24, 32, 48, 64],
  "radius": { "none": 0, "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 28, "full": 9999 },
  "elevationDp": [0, 1, 3, 6, 8, 12],
  "elevationUsed": [0, 1, 3],
  "stateLayerOpacity": { "hover": 0.08, "focus": 0.10, "pressed": 0.10, "dragged": 0.16,
                         "disabledContent": 0.38, "disabledContainer": 0.12 },
  "duration": { "short": [50,100,150,200], "medium": [250,300,350,400], "long": [450,500,550,600] },
  "easing": { "standard": "cubic-bezier(0.2,0,0,1)",
              "emphasizedDecelerate": "cubic-bezier(0.05,0.7,0.1,1.0)",
              "emphasizedAccelerate": "cubic-bezier(0.3,0,0.8,0.15)" },
  "breakpoints": { "compact": 0, "medium": 600, "expanded": 1024 },
  "contentMaxWidth": 1440,
  "minTouchTargetPx": 48,
  "font": "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif",
  "typeScale": {
    "display-large":   { "size": 57, "line": 64, "weight": 400, "tracking": -0.25 },
    "display-medium":  { "size": 45, "line": 52, "weight": 400, "tracking": 0 },
    "display-small":   { "size": 36, "line": 44, "weight": 400, "tracking": 0 },
    "headline-large":  { "size": 32, "line": 40, "weight": 400, "tracking": 0 },
    "headline-medium": { "size": 28, "line": 36, "weight": 400, "tracking": 0 },
    "headline-small":  { "size": 24, "line": 32, "weight": 400, "tracking": 0 },
    "title-large":     { "size": 22, "line": 28, "weight": 400, "tracking": 0 },
    "title-medium":    { "size": 16, "line": 24, "weight": 500, "tracking": 0.15 },
    "title-small":     { "size": 14, "line": 20, "weight": 500, "tracking": 0.1 },
    "body-large":      { "size": 16, "line": 24, "weight": 400, "tracking": 0.5 },
    "body-medium":     { "size": 14, "line": 20, "weight": 400, "tracking": 0.25 },
    "body-small":      { "size": 12, "line": 16, "weight": 400, "tracking": 0.4 },
    "label-large":     { "size": 14, "line": 20, "weight": 500, "tracking": 0.1 },
    "label-medium":    { "size": 12, "line": 16, "weight": 500, "tracking": 0.5 },
    "label-small":     { "size": 11, "line": 16, "weight": 500, "tracking": 0.5 }
  }
}
```

---

## 13. Conformance checklist

Run before any UI change is called done.

- [ ] No hex, size, spacing, or radius outside §2–§6
- [ ] Light and dark both checked; dark uses selected values, not a flip
- [ ] Every interactive element has a visible focus ring
- [ ] Touch targets ≥ 48dp
- [ ] Text contrast ≥ 4.5:1 (≥ 3:1 for ≥ 24px or bold ≥ 19px)
- [ ] Status meaning never color-alone — icon + label present
- [ ] Charts: fixed slot order, legend for ≥2 series, table twin, `aria-label`
- [ ] No dual-axis chart, no pie chart
- [ ] Every non-local number carries a provenance badge and freshness
- [ ] Cache hits show matched prompt, age, score vs threshold, and a reject
- [ ] Unscoreable similarity renders "cannot be scored"
- [ ] Empty and broken states are visually distinct
- [ ] Panels fail independently
- [ ] `prefers-reduced-motion` honoured; no animated numbers
- [ ] Remote-denied writes are disabled with a stated reason

---

## 14. Changing this book

The book is versioned with the code. Changes to §2.2, §2.3, or §9.1 MUST include
the validator output in the commit message:

```bash
node scripts/validate_palette.js "<hex,…>" --mode light  --surface "#fcfcfb"
node scripts/validate_palette.js "<hex,…>" --mode dark   --surface "#1a1a19"
```

Palette changes without validator output are rejected at review. Every other
section: state the rule, and if it overrides Material Design 3, annotate why.
