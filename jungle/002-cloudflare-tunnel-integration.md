# Feature: Cloudflare Tunnel Integration

**Status:** Open
**Priority:** High
**Date:** 2026-07-30

---

## Overview

Integrate Cloudflare Tunnel (formerly Argo Tunnel) so that the local Brown Bear stack can be securely exposed to the internet. External machines can then fetch and store data for AI usage via a stable Cloudflare URL, without port forwarding or dynamic DNS. The tunnel URL is persisted in the database and managed through the dashboard.

---

## Requirements

### Tunnel Management
- Automate `cloudflared` tunnel creation and lifecycle
- Store tunnel URL, credentials, and status in PostgreSQL
- Support wildcard or named subdomains (e.g., `ai.yourdomain.com`)
- Auto-reconnect on tunnel drops with exponential backoff

### External API Gateway
- Expose a secure REST API through the tunnel for external clients
- API key authentication for external callers
- Rate limiting per API key (configurable)
- Request/response logging for audit trail

### Data Sync
- External machines can:
  - **Push** embeddings/documents to ChromaDB via tunnel
  - **Pull** query results from ChromaDB via tunnel
  - **Push** raw text for local embedding + storage
  - **Pull** cached data from Redis via tunnel
- Sync jobs can be scheduled or triggered on-demand
- Conflict resolution for concurrent writes

### Security
- mTLS or API key authentication for all tunnel traffic
- IP allowlisting (optional)
- Request payload size limits
- CORS configuration for browser-based clients

---

## Subtasks

### 2.1 — Cloudflare Setup & Tunnel Automation
- [ ] Create `jungle/gateway/` module for tunnel management
- [ ] Document Cloudflare account setup and API token requirements
- [ ] Script `cloudflared tunnel create`, `route dns`, `tunnel run`
- [ ] Store tunnel credentials (cert.pem, tunnel.json) securely in Docker volume
- [ ] Add `cloudflared` service to `compose.yaml` (or run as sidecar)
- [ ] Implement tunnel health check and auto-restart

### 2.2 — Tunnel Database Schema
- [ ] Create `tunnels` table:
  - `id`, `name`, `cloudflare_tunnel_id`, `url`, `status`, `credentials_path`
  - `created_at`, `updated_at`, `expires_at`
- [ ] Create `api_keys` table:
  - `id`, `key_hash`, `name`, `rate_limit`, `permissions`, `created_at`, `last_used_at`
- [ ] Create `sync_jobs` table:
  - `id`, `source`, `destination`, `status`, `last_run`, `schedule`, `config_json`
- [ ] Alembic migration scripts

### 2.3 — API Gateway Layer
- [ ] FastAPI middleware for API key validation
- [ ] Rate limiting middleware (token bucket or sliding window)
- [ ] Request/response logging middleware (store in `audit_logs` table)
- [ ] Payload validation (max size, content-type checks)
- [ ] CORS middleware configuration

### 2.4 — External API Endpoints
- [ ] `POST /ext/documents` — push documents for embedding + storage
- [ ] `GET /ext/documents/{id}` — fetch stored document
- [ ] `POST /ext/query` — semantic search against ChromaDB
- [ ] `POST /ext/cache/set` — write to Redis cache
- [ ] `GET /ext/cache/{key}` — read from Redis cache
- [ ] `GET /ext/sync/status` — check sync job status
- [ ] `POST /ext/sync/trigger` — trigger on-demand sync

### 2.5 — Sync Engine
- [ ] Define sync job configuration schema (source, destination, filters, transforms)
- [ ] Implement push sync: external → local ChromaDB
- [ ] Implement pull sync: local → external
- [ ] Scheduled sync via APScheduler or cron-like system
- [ ] Conflict resolution strategy (last-write-wins, merge, manual)
- [ ] Sync progress tracking and resumability

### 2.6 — Dashboard Integration
- [ ] Tunnel status display in dashboard (connected/disconnected, uptime)
- [ ] API key management page (create, revoke, view usage)
- [ ] Sync job configuration UI (create, edit, run, view history)
- [ ] External API usage analytics (calls per key, error rates)

### 2.7 — Security Hardening
- [ ] API key rotation mechanism
- [ ] IP allowlist support (stored in DB, enforced in middleware)
- [ ] Request signing (HMAC) for sensitive operations
- [ ] Audit log viewer in dashboard

---

## Acceptance Criteria

- [ ] Cloudflare tunnel starts and exposes local services at a stable URL
- [ ] External machines can authenticate and call API endpoints through the tunnel
- [ ] Rate limiting prevents abuse (configurable per API key)
- [ ] Documents can be pushed/pulled via external API
- [ ] Semantic queries work through the tunnel
- [ ] Sync jobs can be created, scheduled, and monitored
- [ ] Tunnel status is visible in the dashboard
- [ ] API keys can be created and revoked from the dashboard
- [ ] All external API calls are logged for audit
- [ ] Tunnel auto-reconnects on failure

---

## Implementation Notes

- **Cloudflare Tunnel:** Use `cloudflared` Docker image (`cloudflare/cloudflared:latest`)
- **Credentials:** Store tunnel cert in a Docker volume, not in env vars
- **Gateway service:** Can be a separate FastAPI app or extend the dashboard app
- **Rate limiting:** Use `slowapi` or custom Redis-based sliding window
- **Domain config:** User provides their Cloudflare zone + API token via `.env`
