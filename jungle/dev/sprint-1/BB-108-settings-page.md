# Feature: Settings Page (Read-Only)

**Status:** Open
**Priority:** Low — smallest page, but the clearest test of the "disabled with a
reason" rule
**Points:** 1
**Branch:** `feat/bb-108-settings-page`
**Date:** 2026-08-03
**Sprint:** 1
**Depends on:** BB-102 (tokens), BB-103 (API client)

---

## Overview

The `/settings` page renders the stack's effective configuration. It is
deliberately read-only: the edge publishes `GET /api/settings` and denies `PUT`,
so configuration changes happen on the host. The design work here is making that
boundary read as intentional rather than broken.

---

## Context

**Reads required:** this file, plus `../design/DESIGN-BOOK.md` (normative spec).

| Fact | Value |
|---|---|
| Route | `/settings` in `jungle/web/` |
| Endpoint | `GET /api/settings` → `{settings: [...]}` |
| Denied at the edge | `PUT /api/settings` → `403` from the default-deny |
| Why denied | the edge's allowlist stops an authenticated remote caller from reconfiguring the stack; reads are published, writes are not |
| Where changes happen | on the host — `compose.yaml`, `.env`, or the host-local API |

**Constraints:**

- **Never render an editable control that cannot save.** A remotely-denied write
  is shown as a **disabled control with its reason stated**, never as a control
  that fails when pressed.
- Most credentials in this stack are **hardcoded in `compose.yaml`, not
  interpolated from `.env`** — only `CLOUDFLARE_TUNNEL_TOKEN`, `BB_EDGE_TOKEN` and
  `BB_EDGE_BASIC` come from the environment. A settings page that implies editing
  `.env` changes Postgres or Redis would be wrong.
- **Never display a secret value.** Token, password, and key settings render as
  presence-only ("set" / "not set"), never the value, never a masked prefix.
- Values carry provenance: which layer supplied each one.
- No write path is added in this sprint.

---

## Subtasks

### 108.1 — Page

- [ ] `/settings` route, server component, single fetch
- [ ] Settings grouped by concern (gateway, storage, collection, scheduling)
- [ ] Per setting: name, effective value, source layer, and whether it is
      remotely editable
- [ ] `tabular-nums` on numeric values in the table

### 108.2 — The read-only boundary

- [ ] A page-level explanation: configuration is read-only through the tunnel by
      design, and where to change it instead
- [ ] Any control that would write is rendered **disabled with its reason**
      inline — not hidden, not enabled-and-failing
- [ ] Disabled styling uses the token opacities (content 38%, container 12%)

### 108.3 — Secret handling

- [ ] Secret-valued settings render "set" / "not set" only
- [ ] No secret appears in the HTML source, a data attribute, or a client bundle
- [ ] A test asserts no known secret value appears in rendered output

### 108.4 — States and a11y

- [ ] Loading skeleton at a fixed height
- [ ] Error state naming the endpoint and one next step
- [ ] Empty state distinct from the error state
- [ ] Light and dark, all three breakpoints; visible focus rings

---

## Acceptance Criteria

- [ ] All settings from the endpoint render, grouped, with source and value
- [ ] No editable control exists that would fail on save
- [ ] Disabled controls state their reason inline
- [ ] No secret value appears anywhere in output — verified by the test in 108.3
- [ ] `PUT /api/settings` is never called from this page
- [ ] Error and empty states are visually distinct, each naming a next action
- [ ] Light and dark verified at all three breakpoints
- [ ] No value outside the design tokens

---

## Implementation Notes

- **"Disabled with a reason" is the rule being tested here.** A control that
  looks live and returns 403 teaches the user the product is broken; a disabled
  control with one line of explanation teaches them where the boundary is.
- **The `.env` trap is real and documented in the repo:** `.env.example` warns
  that copying it does not change Postgres, Redis, or VectorAdmin because
  `compose.yaml` hardcodes those. Do not build a UI that contradicts that warning.
- **Presence-only for secrets, not masking.** A masked prefix still leaks length
  and first characters, and a page behind one shared token is not the place to
  spend that.
