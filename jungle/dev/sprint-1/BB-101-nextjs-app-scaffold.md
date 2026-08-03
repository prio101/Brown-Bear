# Feature: Next.js App Scaffold + Container

**Status:** Done — 2026-08-03, see *Delivered* at the end
**Priority:** High — every other sprint-1 ticket is blocked on this
**Points:** 3
**Branch:** `feat/bb-101-nextjs-scaffold`
**Date:** 2026-08-03
**Sprint:** 1

---

## Overview

Create the Next.js application that will replace the Jinja dashboard, and wire it
into the existing Docker Compose stack as a new service. This ticket delivers a
running, containerised, empty-but-correct app shell — no pages, no styling, no
data. It deliberately does **not** touch the FastAPI app, the edge, or any
existing service.

---

## Context

**Reads required:** this file only.

| Fact | Value |
|---|---|
| New app directory | `jungle/web/` (sibling of `jungle/app/`) |
| New compose service | `web`, container name `brownbear-web` |
| Container port | `3000` |
| Host publish | `127.0.0.1:3001` — loopback only, matching how `edge` is bound. **Not 3000**: that port is unbindable on this host (see *Delivered*) |
| Compose file | `compose.yaml` at repo root |
| Backend base URL (inside Docker network) | `http://app:8080` |
| Existing app service | `app`, container `brownbear-app`, port `8080`, built from `./jungle/app` with `target: runtime` |
| Existing edge service | `edge`, container `brownbear-edge`, `127.0.0.1:8081` |
| Node version | `22-alpine` |
| Framework | Next.js (App Router) + TypeScript + React server components |

**Constraints:**

- The stack runs on one machine alongside Ollama and ChromaDB. Image size and
  memory matter: use a multi-stage build and `output: "standalone"`.
- Do **not** publish this service on `0.0.0.0`. Public access is the edge's job,
  and the edge is not part of this ticket.
- Compose interpolates `.env` on every command, so any new environment variable
  must use the `${VAR:-default}` form or `docker compose up` breaks for anyone
  without that variable set.
- The existing `app` service and its Dockerfile are out of scope. Changing them
  is a different ticket.

---

## Subtasks

### 101.1 — Create the application

- [ ] `jungle/web/` with Next.js App Router + TypeScript, React server components
- [ ] `next.config.ts` with `output: "standalone"` and `reactStrictMode: true`
- [ ] `BB_API_URL` read from the environment, defaulting to `http://app:8080`
- [ ] Root layout with `<html lang="en">` and a `color-scheme` declaration
- [ ] Placeholder route at `/` rendering the app name and version — no data yet
- [ ] `.gitignore` entries for `node_modules/`, `.next/`

### 101.2 — Dockerfile

- [ ] `jungle/web/Dockerfile`, multi-stage:
  - `deps` — install from lockfile only (`npm ci`)
  - `builder` — `npm run build`
  - `runtime` — `node:22-alpine`, non-root user (uid `10002`, distinct from the
    app image's `10001`), copies `.next/standalone` + `.next/static` + `public`
- [ ] `EXPOSE 3000`, `CMD ["node", "server.js"]`
- [ ] Explicit `target: runtime` in compose — the app image's Dockerfile has a
      trailing `dev` stage and its comment records that omitting the target
      silently builds the wrong one. Do not repeat that trap here.

### 101.3 — Compose service

- [ ] `web` service in `compose.yaml`:
  ```yaml
  web:
    build:
      context: ./jungle/web
      target: runtime
    container_name: brownbear-web
    ports:
      - "127.0.0.1:3001:3000"
    environment:
      - BB_API_URL=http://app:8080
    depends_on:
      - app
    restart: unless-stopped
  ```
- [ ] Placed after the `app` service, before `edge`, to match reading order

### 101.4 — Verify

- [ ] `docker compose up -d web` builds and starts
- [ ] `curl -s http://127.0.0.1:3000/` returns the placeholder page
- [ ] `docker compose ps` shows `brownbear-web` healthy alongside the nine
      existing containers
- [ ] `docker exec brownbear-web wget -qO- http://app:8080/api/info` resolves —
      confirms the app is reachable on the Docker network by service name

---

## Acceptance Criteria

- [ ] `docker compose up -d` starts the frontend with no manual steps
- [ ] The container runs as a non-root user
- [ ] Runtime image contains no dev dependencies and no source tree
- [ ] `http://127.0.0.1:3000/` renders; the port is **not** reachable from
      another machine on the network
- [ ] The container resolves `http://app:8080` by service name
- [ ] No existing service definition was modified
- [ ] `docker compose config` parses with no `.env` present

---

## Implementation Notes

- **`output: "standalone"`:** produces a self-contained `server.js` with only the
  traced dependencies. Skipping it means shipping all of `node_modules`.
- **Two non-root uids:** the app image uses `10001`; use `10002` here so a shared
  volume, if one is ever added, has unambiguous ownership.
- **`depends_on` is start-order only,** not readiness. The app may still be
  booting when the frontend starts, which is fine — data fetching is a later
  ticket, and pages must tolerate a cold backend anyway.
- **No host `node_modules` mount.** Bind-mounting a host `node_modules` into an
  alpine container breaks native modules.

---

## Delivered — 2026-08-03

**Files:** `jungle/web/` (new — `package.json`, `package-lock.json`,
`next.config.ts`, `tsconfig.json`, `Dockerfile`, `.dockerignore`, `.gitignore`,
`src/app/layout.tsx`, `src/app/page.tsx`, `src/lib/config.ts`), `compose.yaml`.

**Resolved versions:** Next `16.2.12`, React `19.2.8`, TypeScript `6.0.3`.

**Verified:** 10 containers up · `http://127.0.0.1:3001/` → `200` · container
resolves `http://app:8080/api/info` → `{"name":"Brown Bear","version":"0.1.0"}` ·
runs as `uid=10002(brownbear)` · runtime image contains only `node_modules`,
`package.json`, `server.js` — no source tree, no `typescript` · published on
loopback only · image 305MB vs the app's 314MB.

**Three deviations, each forced by the environment:**

1. **Host port 3001, not 3000.** Docker cannot bind `127.0.0.1:3000` on this
   host — `bind: An attempt was made to access a socket in a way forbidden by its
   access permissions` — even though nothing is listening. It falls inside a
   Windows/Hyper-V excluded port range, which is invisible from inside WSL. Probed
   3000/3001/3100/3300: only 3000 is blocked. 3001 also groups the UIs (3001 web,
   3002 vectoradmin). **The container port is still 3000**, so BB-104's
   `proxy_pass http://web:3000` is unaffected.
2. **TypeScript pinned to `^6`, not latest.** `npm install typescript` resolves to
   7.0.2, and the build fails: *"TypeScript 7.0.2 does not provide the compiler API
   required by Next.js. Enable experimental.useTypeScriptCli … or install
   TypeScript 6 instead."* Took the supported path rather than switching on an
   experimental flag to accommodate a too-new compiler. Revisit when Next supports
   TS 7 properly.
3. **`next lint` script dropped.** Next 16 no longer ships that subcommand; a
   linter is a follow-up choice (Biome or ESLint flat config), not something to
   fake here. `typecheck` remains.

**Known, not fixed:** `npm audit` reports 3 high-severity advisories, all in
Next 16's own transitive dependencies — `postcss` (path traversal via
`sourceMappingURL`) and `sharp`/libvips (CVE-2026-33327/33328/35590/35591).
`npm audit fix --force` "fixes" them by installing **next@9.3.3**, a five-major
downgrade, so it was not run. These close with a Next release, not from here. The
app is behind the authenticated edge and uses no `next/image` remote loader.
Re-check on the next Next upgrade.
