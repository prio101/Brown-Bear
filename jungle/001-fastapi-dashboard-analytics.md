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
- [ ] Create `jungle/dashboard/` directory with FastAPI project structure
- [ ] Initialize `pyproject.toml` with dependencies (fastapi, uvicorn, sqlalchemy, redis, httpx, jinja2)
- [ ] Add `Dockerfile` and update `compose.yaml` with `dashboard` service
- [ ] Configure environment variables (database URLs, API keys, service endpoints)

### 1.2 — Database & Models
- [ ] Design SQLite/PostgreSQL schema for analytics tables:
  - `token_usage` (model, tokens_in, tokens_out, session_id, timestamp, source: local|remote)
  - `query_logs` (collection, query_text, latency_ms, result_count, timestamp)
  - `cache_events` (hit/miss, key_pattern, timestamp)
  - `system_snapshots` (cpu, memory, disk, timestamp)
- [ ] Create SQLAlchemy models and Alembic migrations
- [ ] Seed database with test data

### 1.3 — Service Connectors
- [ ] Ollama connector — poll `/api/tags` and `/api/ps` for model stats
- [ ] ChromaDB connector — fetch collection stats via `/api/v1/collections`
- [ ] Redis connector — use `INFO` command for memory, keyspace, hit/miss stats
- [ ] PostgreSQL connector — connection pool stats

### 1.4 — Background Collector
- [ ] Background task ( APScheduler or asyncio ) that periodically:
  - Polls all service health endpoints
  - Records system snapshots every 30s
  - Aggregates token usage counters every 5min
- [ ] Store collected metrics in analytics database

### 1.5 — API Endpoints
- [ ] `GET /api/health` — system health summary
- [ ] `GET /api/tokens` — token usage with filters (model, period, source)
- [ ] `GET /api/cache` — cache performance stats
- [ ] `GET /api/collections` — ChromaDB collection overview
- [ ] `GET /api/metrics` — Prometheus-compatible `/metrics` endpoint
- [ ] `GET /api/export` — CSV/JSON export of analytics

### 1.6 — Dashboard UI
- [ ] Build responsive admin dashboard (FastAPI + Jinja2 + HTMX or standalone React)
- [ ] Overview page: service health cards, key metrics at a glance
- [ ] Token usage page: interactive charts (Chart.js or Plotly)
- [ ] Cache analytics page: hit/miss graphs, memory usage
- [ ] Collections page: ChromaDB document counts, storage, query volume
- [ ] Settings page: configure polling intervals, alert thresholds

### 1.7 — Alerting (Optional)
- [ ] Configurable thresholds (e.g., token budget exceeded, cache hit rate drops below X%)
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
