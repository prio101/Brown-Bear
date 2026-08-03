# Feature: Token Analytics Page + Chart Components

**Status:** Done — 2026-08-03, delivered notes in the commit message
**Priority:** High — the heaviest ticket in the sprint and the critical path
**Points:** 3
**Branch:** `feat/bb-106-token-analytics`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** BB-102 (tokens), BB-103 (API client)

---

## Overview

The `/tokens` page, and with it the React chart layer the rest of the dashboard
reuses. The existing `charts.js` is a hand-rolled inline-SVG implementation that
already satisfies the project's accessibility rules; this ticket ports its
conventions into components with identical output guarantees. It is a port, not a
redesign — no charting library, no new palette.

---

## Context

**Reads required:** this file, plus `../design/DESIGN-BOOK.md` §9 (normative chart
spec).

| Fact | Value |
|---|---|
| Route | `/tokens` in `jungle/web/` |
| Reference implementation | `jungle/app/brownbear/static/charts.js` — inline SVG, table twins, no library |
| Endpoints | `GET /api/tokens/summary?period=`, `/history?period=`, `/by-model`, `/by-source`, `/aggregation` |
| `summary` shape | `{period, period_start, period_end, live, source, tokens_in, tokens_out, total_tokens, cost, currency, request_count}` |
| `history` shape | `{period, start, end, count, truncated, results: [{period_start, ...}]}` |
| Series palette (light) | slot 1 `#2a78d6` · 2 `#eb6834` · 3 `#1baf7a` · 4 `#eda100` |
| Series palette (dark) | slot 1 `#3987e5` · 2 `#d95926` · 3 `#199e70` · 4 `#c98500` |
| Chart surface | light `#fcfcfb` · dark `#1a1a19` (fixed, never themed) |
| Series cap, all-pairs forms | 3 (scatter, bubble, small multiples) |
| Denied at the edge | `POST /api/tokens/aggregate` — read the aggregation state, never trigger it |

**Constraints:**

- **One axis. NEVER a dual-axis chart.** Tokens and cost have different scales:
  two charts, or index to a common base.
- **NEVER a pie or donut.** Composition at one point in time is a stacked bar.
- Assign series slots in **fixed order, never cycled**. Color follows the entity,
  not its rank: changing the filter must not repaint the surviving series.
- **Text never wears a series color.** Values and labels stay in ink tokens; a
  colored mark beside them carries identity.
- Legend present for **≥2 series**; a single series needs none. At ≤4 series,
  direct-label them too.
- **A table twin always exists**, reachable and announced.
- `truncated: true` means the series was capped — say so on the chart, or the
  chart is lying.
- Marks: 2px lines, ≥8px markers, 4px rounded data-end on bars anchored to the
  baseline, 2px surface gap between adjacent fills.
- Light-mode aqua/yellow fall below 3:1 on the light surface — the relief rule
  requires visible direct labels or the table twin. The twin satisfies it.
- No animated value tweens. Entry animation is opacity/scale only, `medium-2` max.

---

## Subtasks

### 106.1 — Chart primitives

- [ ] `<LineChart>` — inline SVG, `role="img"`, meaningful `aria-label`,
      crosshair + multi-series tooltip
- [ ] `<BarChart>` — horizontal, sorted by value, per-mark tooltip, 4px rounded
      data-ends
- [ ] `<StackedBarChart>` — ≤4 series, 2px surface gaps between segments
- [ ] `<ChartFrame>` — title, legend, empty state ("No data yet" inside the plot
      frame), error state, and the table-twin affordance
- [ ] Recessive chrome: hairline gridlines, muted ticks, no chart junk

### 106.2 — Table twin

- [ ] `<ChartTable>` rendering the same data as a real table
- [ ] `tabular-nums` on numeric columns; sortable headers; sticky header
- [ ] Reachable by keyboard and announced — never visually hidden with no
      affordance

### 106.3 — Page composition

- [ ] Stat tiles: tokens in, tokens out, total, cost, request count — each with
      provenance badge and freshness
- [ ] History line chart (tokens over time), one axis
- [ ] Cost as a **separate** chart, never a second axis on the token chart
- [ ] By-model horizontal bar, sorted by value
- [ ] By-source horizontal bar, sorted by value, with reported-versus-measured
      made visible
- [ ] Aggregation state panel — read-only, showing last run and next run
- [ ] Each chart's table twin present

### 106.4 — Filters

- [ ] One filter row **above** the charts, never interleaved
- [ ] Period presets: today, last 7 / 30 / 90 days, month-to-date
- [ ] Custom range behind a divider in the control's footer
- [ ] Filter state in the URL so a view is shareable and reloadable
- [ ] Changing a filter does not repaint surviving series

### 106.5 — Truncation and provenance

- [ ] `truncated: true` renders a visible note on the affected chart
- [ ] Totals mixing measured and reported data show the weakest provenance
      present, explained in the tooltip

### 106.6 — Accessibility pass

- [ ] Legend rules verified per chart
- [ ] Every SVG has `role="img"` and a meaningful label
- [ ] Dark mode uses the dark palette column — selected values, not a filter flip
- [ ] Texture fill available for CVD / print / `forced-colors`, off by default
- [ ] `prefers-reduced-motion` honoured
- [ ] Rendered and **visually inspected** in both modes for label collision and
      overflow — the palette is validated, the layout is not

---

## Acceptance Criteria

- [ ] No dual-axis chart anywhere on the page
- [ ] No pie or donut chart
- [ ] Every chart has a table twin reachable by keyboard
- [ ] Legend present for ≥2 series, absent for one
- [ ] Series colors are stable across filter changes
- [ ] No label, value, or legend text is painted a series color
- [ ] `truncated: true` produces a visible note
- [ ] Empty data renders "No data yet" inside the plot frame, not a blank box
- [ ] Charts render on the fixed chart surface in both modes
- [ ] Dark mode uses the dark palette column
- [ ] No animated value tweens; reduced-motion honoured
- [ ] Screenshots of both modes attached to the PR, visually checked
- [ ] `POST /api/tokens/aggregate` is never called

---

## Implementation Notes

- **Read `charts.js` before writing a line.** Its header comment records why it is
  hand-rolled and what it guarantees. This ticket preserves those guarantees; it
  does not get to relitigate them.
- **Why no charting library:** every mainstream option defaults to behaviour this
  project prohibits — cycled palettes, dual axes, tweened values, no table twin —
  and fighting those defaults costs more than the SVG.
- **Dual axis is the single most consequential rule here.** Tokens and cost on one
  chart with two scales is the most likely mistake and the most misleading.
- **The validator checks color, not layout.** Screenshot both modes and look.
