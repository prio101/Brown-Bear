# Feature: Design System Foundation (Material Design 3 Tokens)

**Status:** Done — 2026-08-03, see *Delivered* at the end
**Priority:** High — every page ticket depends on these tokens existing
**Points:** 3
**Branch:** `feat/bb-102-design-tokens`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** BB-101 — the Next.js app must exist

---

## Overview

Implement the project design system as code: a generated Material Design 3 theme,
the type scale, spacing, shape, state layers, and motion, exposed as CSS custom
properties and typed helpers. This is the token layer only — no page, no chart, no
component with business meaning.

The normative specification is
[`../design/DESIGN-BOOK.md`](../design/DESIGN-BOOK.md). Where this ticket and the
book disagree, the book wins.

---

## Context

**Reads required:** this file, plus `../design/DESIGN-BOOK.md` §2–§7 (normative
spec, referenced by design — not sprint context).

| Fact | Value |
|---|---|
| App directory | `jungle/web/` |
| Theme seed | `#7A5230` |
| Theme generator | `@material/material-color-utilities` |
| Chart surface (fixed, not themed) | light `#fcfcfb` · dark `#1a1a19` |
| Page plane | light `#f9f9f7` · dark `#0d0d0d` |
| Status colors (reserved) | good `#0ca30c` · warning `#fab219` · serious `#ec835a` · critical `#d03b3b` |
| Spacing scale | `4, 8, 12, 16, 24, 32, 48, 64` |
| Radius scale | `0, 4, 8, 12, 16, 28, 9999` |
| Elevation used | levels `0, 1, 3` of `0,1,3,6,8,12` dp |
| Breakpoints | compact `<600` · medium `600–1023` · expanded `≥1024` |
| Font stack | `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` |
| Min touch target | `48px` |

**Constraints:**

- The theme is **generated from the seed**, never hand-authored. Regenerating is
  the only supported way to change theme color.
- Chart surfaces and the series palette are **fixed and not themed**. The series
  palette is validated for contrast against those exact surfaces; a theme-tinted
  chart surface would invalidate that. A reseed must not alter them.
- Dark mode is a designed set of values, **not** a filter inversion or a
  lightness flip.
- Status colors are reserved: never themed, never used as a chart series.

---

## Subtasks

### 102.1 — Generate the M3 theme

- [ ] Add `@material/material-color-utilities` as a dependency
- [ ] Build-time script `jungle/web/scripts/gen-theme.ts`:
  - input: seed `#7A5230`
  - output: `jungle/web/src/styles/theme.generated.css` — light and dark role
    values as CSS custom properties
- [ ] Emit the full role set: `primary`, `on-primary`, `primary-container`,
      `on-primary-container`, and the same for `secondary`, `tertiary`, `error`;
      plus `surface`, `on-surface`, `surface-variant`, `on-surface-variant`,
      `surface-container-lowest|low|base|high|highest`, `outline`,
      `outline-variant`, `inverse-surface`, `scrim`
- [ ] Wire the script into `prebuild` so the file is never stale
- [ ] Commit the generated file — reviewers must see theme diffs

### 102.2 — Static token layer

- [ ] `tokens.css` with the non-generated values: spacing, radius, elevation
      shadows, state-layer opacities, motion durations and easing curves,
      breakpoints, font stack
- [ ] `chart-tokens.css` with the fixed chart surfaces, ink, gridline, axis,
      delta, and the 8-slot series palette for both modes
- [ ] Dark values declared under **both** `@media (prefers-color-scheme: dark)`
      and a `:root[data-theme="dark"]` scope, so an explicit user toggle beats the
      OS setting in both directions

### 102.3 — Type scale

- [ ] All 15 M3 roles as utility classes or a typed `<Text role="...">`
      component: display/headline/title large-medium-small, body
      large-medium-small, label large-medium-small
- [ ] Exact size / line-height / weight / tracking per the Design Book §3
- [ ] `tabular-nums` available as a modifier — for table columns and axis ticks
      only, not for standalone figures

### 102.4 — Interaction primitives

- [ ] State-layer utility: hover 8%, focus 10%, pressed 10%, dragged 16%,
      disabled content 38% / container 12%
- [ ] Focus ring: 3px `primary` at 2px offset, on every interactive element.
      `outline: none` without a replacement is a review rejection
- [ ] `prefers-reduced-motion: reduce` drops transitions to opacity-only

### 102.5 — Theme toggle

- [ ] Light / dark / system toggle, stamping `data-theme` on the root element
- [ ] Choice persisted in `localStorage`
- [ ] No flash of the wrong theme on first paint

### 102.6 — Token conformance check

- [ ] Lint rule or CI grep rejecting a raw hex, px font size, or off-grid spacing
      value in component source — the token layer is only useful if bypassing it
      fails the build
- [ ] Documented allowlist for the two legitimate exceptions: the generated theme
      file and `chart-tokens.css`

---

## Acceptance Criteria

- [ ] Every value in Design Book §2–§7 is reachable as a token; none is hardcoded
      in a component
- [ ] Regenerating with a different seed changes theme colors and leaves chart
      surfaces, the series palette, and status colors untouched
- [ ] Explicit dark selection wins over OS light, and explicit light wins over OS
      dark
- [ ] Every interactive element shows a visible focus ring under keyboard
      navigation
- [ ] With `prefers-reduced-motion: reduce`, no transform or position transition
      runs
- [ ] The conformance check fails a deliberately introduced raw hex
- [ ] No page or data-bound component was added — this ticket ships tokens only

---

## Implementation Notes

- **Why generate rather than copy M3 baseline values:** the baseline scheme is
  built from Google's default purple seed. Copying it and calling it themed is the
  usual failure; generating from `#7A5230` is one script and makes a reseed a
  one-line change.
- **Why chart color is a separate file:** it enforces the separation the Design
  Book requires. Two files make "a reseed cannot repaint a series" checkable at a
  glance.
- **State layers over custom hovers:** fixed opacity layers are what make an
  unfamiliar control feel predictable. Bespoke hover colors per component are the
  thing this replaces.
- **No CSS-in-JS runtime.** Server components render most of this; a runtime
  styling library costs client JS for no benefit here.

---

## Delivered — 2026-08-03

**Files:** `scripts/gen-theme.mjs`, `scripts/check-tokens.mjs`,
`src/styles/{theme.generated.css,tokens.css,chart-tokens.css,type.css,interaction.css,global.css}`,
`src/components/{Text.tsx,ThemeToggle.tsx}`, `src/app/{layout.tsx,page.tsx}`,
`package.json`, `.gitignore`.

**Generated:** 30 M3 roles × 2 modes from seed `#7A5230` → `--bb-primary: #88511e`.

**Verified:**

- **Reseed independence, measured not assumed.** Reseeded to `#1E88E5`,
  regenerated: `theme.generated.css` CHANGED (`--bb-primary: #39608f`),
  `chart-tokens.css` and `tokens.css` **UNCHANGED**. Restored to brown.
- **Conformance check works in both directions.** Clean on the real tree; a probe
  file with `#ff0000`, `font-size: 13px` and `padding: 13px` produced 4 violations
  and a non-zero exit.
- **Served bundle** carries the token layer, 3 `prefers-color-scheme: dark`
  blocks, 3 `[data-theme="dark"]` scopes, the reduced-motion block, the dark
  series step `#3987e5` (a selected value, not a flip), and the type-scale classes.
  The no-FOUC init script is inlined in the HTML.
- `typecheck` clean, `build` clean, container rebuilt and serving.

**Three deviations:**

1. **`gen-theme.mjs`, not `.ts`, and bundled by esbuild before it runs.**
   `@material/material-color-utilities` publishes ESM with **extensionless
   internal imports** (`scheme_content.js` imports `../dynamiccolor/dynamic_scheme`
   with no extension), which plain Node ESM cannot resolve — it throws
   `ERR_MODULE_NOT_FOUND` no matter which entry point you use, and `require()`
   fails with `ERR_REQUIRE_ESM`. The package assumes a bundler. So `esbuild` is a
   new devDependency and `gen:theme` bundles to `.gen/` before running. Plain JS
   rather than TS avoids also needing a TS runner in the build.
2. **Roles emitted as `--bb-*`, curated to the book's 30.** Used
   `SchemeTonalSpot` + `MaterialDynamicColors` rather than the legacy `Scheme`,
   because the `surface-container-*` roles the book requires only exist on the
   dynamic-color API. The list is explicit, not "every role the library exposes" —
   an unused token is one someone reaches for without checking what it means here.
3. **The off-grid rule checks multiples of 4, not membership of the spacing
   scale.** First draft flagged `min-width: 120px` and `@media (min-width: 600px)`,
   which are both legitimately on the 4px grid; widths and breakpoints do not come
   from the spacing scale. It also had a regex bug — `(\d+)px` matched `0.5px` as
   `5px`, reporting a tracking value as an off-grid length. Both fixed; hairlines
   (1–3px) and fractional tracking are allowed.

**Not verified — needs a browser.** The acceptance list asks for a visual check in
light and dark and a keyboard focus-ring pass. Both are confirmed *structurally*
(the rules and both dark scopes are in the served bundle, the focus rule targets
every interactive element) but **no one has looked at it in a browser yet**. The
token page at `http://127.0.0.1:3001/` exists for exactly that check — type scale,
theme roles, all 8 series slots, status chips, focus states, and a working
light/dark/system toggle. It needs five minutes of human eyes before BB-105 builds
on it.
