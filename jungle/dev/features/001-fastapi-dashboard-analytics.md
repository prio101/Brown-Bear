# Feature: FastAPI Dashboard & Analytics

**Status:** Open
**Priority:** High
**Date:** 2026-07-30

---

## Overview

Build a Python FastAPI application that serves as a real-time dashboard and analytics layer for the Brown Bear AI stack. The dashboard monitors token consumption (local Ollama + remote API calls), data served through ChromaDB, cached data in Redis, and provides historical analytics with exportable reports.

---

## Requirements

### Core Dashboard
- FastAPI app with Jinja2/HTMX or React frontend (admin panel style)
- Real-time system health overview (all services: Ollama, ChromaDB, Redis, PostgreSQL)
- Live connection status indicators for each service
- System resource monitoring (CPU, memory, disk usage per container)

### Token Analytics
- Track token consumption per model, per session, per time period
- Distinguish between local (Ollama) and remote (external API) token usage
- Token cost estimation (configurable pricing per model)
- Token usage graphs: hourly, daily, weekly, monthly views
- Per-user / per-session token breakdown

### Data & Cache Analytics
- ChromaDB collection stats (document count, embedding dimensions, storage size)
- Cache hit/miss ratios from Redis
- Cache memory usage and eviction tracking
- Data ingestion rate (documents added per minute/hour)
- Query volume and latency tracking

### Reporting
- Export analytics as CSV / JSON
- Scheduled report generation (daily summary emails or webhooks)
- API endpoints for external monitoring tools (Prometheus-compatible metrics)

---

## Subtasks

### 1.1 — Project Scaffolding
Landed as `jungle/app/` rather than `jungle/dashboard/`: roadmap decision D4 makes
dashboard, tracker, maintenance and gateway routers of one app, not four services.
- [x] Create FastAPI project structure (`jungle/app/brownbear/`)
- [x] Initialize `pyproject.toml` with dependencies (fastapi, uvicorn, sqlalchemy, redis, httpx, jinja2)
- [x] Add `Dockerfile` and update `compose.yaml` with the `app` service
- [x] Configure environment variables (database URLs, API keys, service endpoints)

### 1.2 — Database & Models
PostgreSQL only (roadmap D2): SQLite cannot serve a concurrent scheduler and API writer.
- [x] Analytics schema:
  - ~~`token_usage`~~ — superseded by spec 003's `token_events` / `token_periods` (roadmap D1)
  - `query_logs` (collection, query_text, latency_ms, result_count, timestamp) — created,
    stays empty until spec 002's `/ext/query`
  - `cache_samples` — replaces `cache_events`. An event-shaped table presumes the app sits in
    the path of Redis traffic; it does not. Redis exposes cumulative counters, so the honest
    shape is a periodic sample with rates derived from deltas.
  - `system_snapshots` (cpu, memory, disk, timestamp) — **host-scoped**, not per-container.
    Per-container stats need the Docker socket mounted in, which is root-equivalent host access.
- [x] Create SQLAlchemy models and Alembic migrations
- [ ] Seed database with test data — deliberately not done. Seeded rows in the same tables the
      dashboard reports on would misstate real usage; verification data was removed after each run.

### 1.3 — Service Connectors
- [x] Ollama connector — poll `/api/tags` and `/api/ps` for model stats
- [x] ChromaDB connector — fetch collection stats. **`/api/v1` now returns 410 Gone**;
      the connector uses v2's tenant-scoped path and the version is a setting
- [x] Redis connector — use `INFO` command for memory, keyspace, hit/miss stats
- [x] PostgreSQL connector — connection pool stats

### 1.4 — Background Collector
- [x] APScheduler jobs that periodically:
  - Sample Redis counters (30s, configurable)
  - Record system snapshots every 30s (configurable)
  - Aggregate token usage — **hourly, not every 5 minutes**: the smallest bucket is an hour, so
    a 5-minute job would re-run the same window twelve times to no effect
  - Prune monitoring rows daily (added: at 30s these tables grow ~5,800 rows/day each)
- [x] Store collected metrics in the analytics database

### 1.5 — API Endpoints
- [x] `GET /api/health` — system health summary (plus `/api/health/live` for liveness)
- [x] `GET /api/tokens/*` — usage with filters (model, period, source); see spec 003 §3.6
- [x] `GET /api/cache` — cache performance stats (window deltas + per-interval series)
- [x] `GET /api/collections` — ChromaDB collection overview
- [x] `GET /api/system` — host resource series (added; the dashboard needs it)
- [x] `GET /api/metrics` and `/metrics` — Prometheus exposition format
- [x] `GET /api/export` — streaming CSV/JSON export

### 1.6 — Dashboard UI
Jinja2 shells plus hand-rolled inline-SVG charts — **not Chart.js or Plotly**. This stack is
built to run without internet, so a CDN tag is out and vendoring a charting bundle would dwarf
the dashboard. Every page reads the same JSON API any other client uses.
- [x] Responsive dashboard, light and dark, no external assets
- [x] Overview page: service health cards, key metrics at a glance
- [x] Token usage page: interactive charts with crosshair, tooltip and keyboard navigation
- [x] Cache analytics page: hit/miss graphs, memory usage
- [x] Collections page: ChromaDB document counts
- [x] Settings page: polling intervals (applied live) and alert thresholds (stored for §1.7)

Colour follows the validated reference palette, run through the validator all-pairs in both
modes. Every chart carries a legend and a table twin, so no value is reachable by hover alone.

### 1.7 — Alerting (Optional)
- [x] Configurable thresholds — daily cost budget, cache hit rate floor, disk ceiling; stored
      and editable, but **nothing evaluates them yet**. The settings page says so explicitly.
- [ ] Alert via webhook, email, or log
- [ ] Alert history and acknowledgment

---

## Acceptance Criteria

- [ ] FastAPI app starts and serves dashboard on configured port
- [ ] All services (Ollama, ChromaDB, Redis) are monitored with live status indicators
- [ ] Token usage is tracked per model and per source (local/remote)
- [ ] Cache hit/miss ratios are calculated and displayed
- [ ] Charts render with accurate historical data
- [ ] Analytics can be exported as CSV/JSON
- [ ] Prometheus-compatible metrics endpoint responds
- [ ] Dashboard is responsive (desktop + mobile)
- [ ] Background collector runs without manual intervention
- [ ] All endpoints have basic error handling and input validation

---

## Implementation Notes

- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, Redis (redis-py), httpx, Jinja2/HTMX
- **Charts:** Chart.js (lightweight) or Plotly (interactive) for frontend visualization
- **Metrics format:** Follow Prometheus exposition format for `/metrics`
- **Auth:** Basic API key auth for initial version; upgrade to OAuth later
- **Container:** Multi-stage Docker build; share network with other compose services
