# Roadmap: Brown Bear Implementation Plan

**Status:** Planning
**Date:** 2026-07-30
**Covers:** specs 001–004

---

## Goal

Turn Brown Bear from an infrastructure-only stack (`compose.yaml`) into a running Python application that monitors, meters, exposes, and maintains the local AI stack.

**Current state:** 6 containers running; zero lines of application code; 32 unchecked subtasks across 4 specs.

---

## Decisions required before any code (blocking)

The four specs were written independently and disagree in four places. Each must be settled once, because every later task inherits the answer.

| # | Conflict | Where | Recommendation |
|---|---|---|---|
| D1 | **Token schema defined twice.** 001 §1.2 defines `token_usage`; 003 §3.3 defines `token_events` + `token_periods` + `model_pricing` for the same data. | 001 vs 003 | Drop `token_usage`. 003's schema is the superset (cost, currency, aggregation). 001 reads from 003's tables. |
| D2 | **Database engine.** 001 §1.2 says "SQLite/PostgreSQL"; 002/003/004 assume PostgreSQL. | 001 vs rest | PostgreSQL only. SQLite can't serve concurrent scheduler + API writers. |
| D3 | **Which PostgreSQL database.** The `postgres` container hosts `vdbms`, owned by VectorAdmin's own migrations. | compose.yaml vs all specs | Create a separate `brownbear` database in the same container. Never add tables to `vdbms` — VectorAdmin migrations may drop or conflict with them. |
| D4 | **One app or many.** 001 implies a `dashboard` service; 002 §2.x says the gateway "can be a separate app or extend the dashboard." | 001 vs 002 | One FastAPI app, one container, mounted routers (`/api`, `/ext`). Split later only if the tunnel needs independent scaling. |

Two more choices worth locking now: **APScheduler** as the single scheduler (four specs each introduce one — 001 §1.4, 002 §2.5, 003 §3.4, 004 §4.7), and **ChromaDB API version** — the specs target `/api/v1` but current `chromadb/chroma:latest` serves `/api/v2`; verify against the running container and pin the image tag.

---

## Dependency graph

```
        ┌──────────────────────────┐
        │  Phase 0 — Foundation    │  app skeleton, DB, migrations,
        │  (blocks everything)     │  config, scheduler, connectors
        └────────────┬─────────────┘
                     │
        ┌────────────┴─────────────┐
        │  Phase 1 — Metering      │  003: token events + cost
        │  (spec 003 core)         │
        └────────────┬─────────────┘
                     │
        ┌────────────┴─────────────┐
        │  Phase 2 — Dashboard     │  001: API + UI over 003's data
        │  (spec 001)              │  ← every other spec renders here
        └──────┬────────────┬──────┘
               │            │
   ┌───────────┴────┐  ┌────┴──────────────┐
   │ Phase 3        │  │ Phase 4           │
   │ Maintenance    │  │ External Gateway  │
   │ (spec 004)     │  │ (spec 002)        │
   └────────────────┘  └───────────────────┘
               │            │
        ┌──────┴────────────┴──────┐
        │  Phase 5 — Hardening     │  alerting, retention, security
        └──────────────────────────┘
```

**Why this order.** Metering (003) precedes the dashboard (001) because 001's headline feature is token analytics — building the UI first means building it against empty tables. The dashboard precedes 002 and 004 because both terminate in dashboard pages (§2.6, §4.8). The gateway (002) is last of the feature phases because it is the only one that exposes the stack to the internet, and it should not go live until auth, rate limiting, and audit logging have a working dashboard to be observed through.

---

## Phase 0 — Foundation

**Not in any spec.** Every spec assumes this exists; nobody owns it. Skipping it means building the same scaffolding four times.

| Task | Description | Size |
|---|---|---|
| F1 | `jungle/app/` package: FastAPI entrypoint, router mounting, health endpoint | M |
| F2 | `pyproject.toml` — fastapi, uvicorn, sqlalchemy, alembic, redis, httpx, jinja2, apscheduler, psutil | S |
| F3 | Settings module: env-driven config (service URLs, DB DSN, Redis password, API keys) | S |
| F4 | Create `brownbear` database (D3); SQLAlchemy engine + session management | S |
| F5 | Alembic initialised with one baseline migration | S |
| F6 | Dockerfile (multi-stage) + `app` service in `compose.yaml`, joined to the existing network | M |
| F7 | Shared scheduler singleton (APScheduler, job store in PostgreSQL) | M |
| F8 | Shared service connectors — Ollama, ChromaDB, Redis, PostgreSQL (001 §1.3, reused by all) | M |
| F9 | Test harness: pytest + httpx test client; connectors faked, not live | M |
| F10 | `.env.example` and replace every placeholder credential in `compose.yaml` | S |

**Milestone 0:** `docker compose up -d` starts a seventh container; `GET /api/health` returns live status for all four backing services.

---

## Phase 1 — Metering (spec 003)

Foundation for everything measurable. Build the write path before the read path.

| Task | Spec | Description | Size |
|---|---|---|---|
| M1 | §3.3 | Schema: `token_events`, `token_periods`, `model_pricing` (per D1) + migrations | M |
| M2 | §3.3 | Index `token_events (timestamp, model, source)` for range queries | S |
| M3 | §3.1 | Ollama proxy/middleware capturing `prompt_eval_count` / `eval_count` | L |
| M4 | §3.5 | Pricing config + cost-at-write-time; local models cost 0 | M |
| M5 | §3.4 | Hourly + daily aggregation jobs, idempotent, with run tracking | L |
| M6 | §3.4 | Weekly/monthly rollups derived from daily | M |
| M7 | §3.6 | Read endpoints: `/summary`, `/history`, `/by-model`, `/by-source` | M |
| M8 | §3.2 | Remote-API webhook + dedup, and SDK wrappers for OpenAI/Anthropic | L |

**Decision inside M3:** capturing tokens requires traffic to pass through the app. Either clients call the app instead of Ollama directly (reliable, but a breaking change for existing callers), or the app polls `/api/ps` (non-invasive, lossy). Recommend the proxy, with Ollama's host port closed once it works.

**Milestone 1:** an Ollama chat call through the app produces a `token_events` row with correct in/out counts and cost; after an hour, a matching `token_periods` row exists.

---

## Phase 2 — Dashboard (spec 001)

| Task | Spec | Description | Size |
|---|---|---|---|
| D1t | §1.2 | Remaining tables: `query_logs`, `cache_events`, `system_snapshots` | M |
| D2t | §1.4 | Collector jobs: 30s system snapshots, service health polls | M |
| D3t | §1.5 | `/api/cache`, `/api/collections` endpoints | M |
| D4t | §1.6 | UI shell — layout, nav, service health cards | L |
| D5t | §1.6 | Token pages: charts by period/model/source (consumes Phase 1) — also closes §3.8 | L |
| D6t | §1.6 | Cache + collections pages | M |
| D7t | §1.5 | Prometheus `/metrics` endpoint | M |
| D8t | §1.5 | CSV/JSON export | S |
| D9t | §1.6 | Settings page: polling intervals, thresholds | M |

**Milestone 2:** dashboard renders live health for all services and accurate historical token charts; `/metrics` scrapes clean.

---

## Phase 3 — Maintenance (spec 004)

Ordered deliberately: **read-only detection ships before anything can delete.**

| Task | Spec | Description | Size |
|---|---|---|---|
| P1 | §4.3 | Schema: `maintenance_jobs`, `pruned_documents`, `maintenance_schedules` | M |
| P2 | §4.1, §4.4 | `StalenessDetector` + rules (age, access, relevance, orphan, size) with AND/OR | L |
| P3 | §4.1, §4.6 | Dry-run only: `/candidates` + `/prune?dry_run=true` — **no deletion path yet** | M |
| P4 | §4.5 | Pre-prune JSON backup + soft-delete via `_soft_deleted` metadata flag | L |
| P5 | §4.1 | Real batched deletion (100/batch) with progress + scope caps | M |
| P6 | §4.5, §4.6 | Grace-period expiry and `/restore/{id}` | M |
| P7 | §4.2 | `CollectionCompactor` — export, recreate, reinsert, verify integrity | L |
| P8 | §4.2 | `CollectionMerger` and `ReEmbedder` | L |
| P9 | §4.7 | Scheduling: maintenance window, priority queue, single-job concurrency lock | M |
| P10 | §4.8, §4.9 | Maintenance pages, collection health scores, job history, metrics | L |

**Access-based pruning depends on query logging** (`query_logs`, task D1t) having accumulated real history — the rule is meaningless until then. Ship age- and orphan-based rules first.

**Milestone 3:** dry-run lists correct candidates; a real prune deletes them, frees space, and any document is restorable within the grace period.

---

## Phase 4 — External Gateway (spec 002)

**Security-gated: 4.3 must precede 4.4.** No external route opens before auth, limits, and logging are in place.

| Task | Spec | Description | Size |
|---|---|---|---|
| G1 | §2.2 | Schema: `tunnels`, `api_keys` (hashed), `sync_jobs`, `audit_logs` | M |
| G2 | §2.3 | API-key auth middleware | M |
| G3 | §2.3 | Redis-backed sliding-window rate limiting per key | M |
| G4 | §2.3 | Audit logging, payload size limits, CORS | M |
| G5 | §2.1 | `cloudflared` service, credentials in a volume, DNS route, health check + backoff reconnect | L |
| G6 | §2.4 | `/ext` endpoints: documents, query, cache read/write | L |
| G7 | §2.5 | Sync engine: push/pull, scheduling, conflict resolution, resumability | L |
| G8 | §2.6 | Dashboard: tunnel status, key management, sync config, per-key analytics | L |
| G9 | §2.7 | Key rotation, IP allowlist, HMAC signing, audit viewer | M |

**Milestone 4:** an external machine pushes a document through the tunnel URL, queries it back semantically, and every call appears in the audit log with its key attributed and rate limit enforced.

---

## Phase 5 — Hardening

| Task | Spec | Description | Size |
|---|---|---|---|
| H1 | §3.7 | Retention: prune raw `token_events` after 30 days, keep aggregates 1 year, aggregate-before-delete | M |
| H2 | §3.5, §1.7 | Budget thresholds and alerting (webhook/email/log), alert history + acknowledgment | L |
| H3 | §1.5 | Scheduled reports — daily summary via email or webhook | M |
| H4 | — | Backup strategy for `brownbear` DB and Chroma volume | M |
| H5 | — | Load test: aggregation and dashboard queries against ~1M `token_events` | M |

---

## Cross-cutting risks

| Risk | Impact | Mitigation |
|---|---|---|
| ChromaDB v1→v2 API drift | Breaks 001, 002, 004 connectors at once | Pin the image tag; isolate all Chroma calls behind the F8 connector so a version change is a one-file fix |
| Ollama proxy becomes a bottleneck | All inference latency rises | Async passthrough with streaming preserved; log tokens after response completes, never in the hot path |
| VectorAdmin migrations touch shared tables | Silent data loss | D3 — separate `brownbear` database |
| Pruning deletes live data | Unrecoverable embedding loss | Dry-run first (P3 before P5), backup (P4), scope caps, soft-delete grace |
| Tunnel exposes an unauthenticated stack | Internet-facing Ollama and ChromaDB | Phase 4 ordering; keep host ports bound to `127.0.0.1` |
| Scheduler jobs overlap on restart | Duplicate aggregates, concurrent prunes | Idempotent aggregation (M5), PostgreSQL job store, single-job lock (P9) |

---

## Suggested first slice

Phase 0 tasks F1–F6 plus M1 and M3 in one branch. That produces the smallest thing that is genuinely useful on its own: a running container that records every Ollama call's token usage. Everything after it is additive.

## Progress tracking

Spec subtask checkboxes in `001`–`004` remain the source of truth — tick them as tasks here complete. This file tracks sequencing and cross-spec decisions only.
