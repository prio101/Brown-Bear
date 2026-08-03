# Feature: Token Consumption Tracking

**Status:** Open
**Priority:** High
**Date:** 2026-07-30

---

## Overview

Implement a precise token consumption tracking system that calculates, records, and persists token usage across all AI operations (local Ollama inference and remote API calls). Token data is aggregated by configurable time periods (hourly, daily, weekly, monthly) and stored for billing, budgeting, and analytics purposes.

---

## Requirements

### Token Counting
- Accurate token counting for all Ollama requests (prompt + completion tokens)
- Support for remote API token tracking (OpenAI, Anthropic, etc.) via webhook/callback
- Per-model token tracking (different models have different tokenization)
- Track both input (prompt) and output (completion) tokens separately

### Period Aggregation
- Aggregate token counts into configurable periods:
  - **Hourly** — for real-time monitoring
  - **Daily** — for budget tracking
  - **Weekly** — for trend analysis
  - **Monthly** — for billing and reporting
- Auto-aggregation: raw events roll up into period summaries automatically
- Retention policy: raw events older than N days are pruned (configurable)

### Cost Calculation
- Configurable pricing per model (tokens → cost conversion)
- Support per-token pricing (input vs output may differ)
- Currency configuration (USD, BDT, etc.)
- Budget alerts when spending exceeds threshold

### Persistence
- All token data persisted in PostgreSQL (survives restarts)
- Periodic snapshots for fast dashboard queries
- Historical data available for at least 90 days (configurable)

---

## Subtasks

### 3.1 — Token Tracking Middleware
Implemented as a proxy (`/ollama/*`) rather than middleware — see roadmap M3.
Clients must call the app instead of Ollama directly; close Ollama's host port
once they have migrated.
- [x] Create tracker module (`brownbear/tracking.py`, `brownbear/routers/ollama_proxy.py`)
- [x] Intercept Ollama API calls
- [x] Extract token counts from Ollama response (`prompt_eval_count`, `eval_count`)
- [x] Log each request to `token_events` table with:
  - `model`, `tokens_in`, `tokens_out`, `total_tokens`
  - `source` (local_ollama | remote_api)
  - `session_id`, `user_id` (if applicable)
  - `request_id`, `timestamp`
  - `cost_usd` (calculated at write time)

### 3.2 — Remote API Token Tracking
- [ ] Webhook endpoint for external API providers to report token usage
- [ ] SDK helper functions that wrap OpenAI/Anthropic calls and log tokens
- [ ] Support batch token reporting (multiple requests in one call)
- [ ] Validate and deduplicate reported events

### 3.3 — Database Schema
- [x] `token_events` table (raw events):
  - `id`, `model`, `tokens_in`, `tokens_out`, `total_tokens`
  - `source`, `session_id`, `user_id`, `request_id`
  - `cost_usd`, `currency`, `timestamp`
- [x] `token_periods` table (aggregated), unique on
      `(period_type, period_start, model, source)` so aggregation is idempotent:
  - `id`, `period_type` (hourly|daily|weekly|monthly)
  - `period_start`, `period_end`
  - `model`, `source`
  - `total_tokens_in`, `total_tokens_out`, `total_tokens`
  - `total_cost_usd`, `request_count`
- [x] `model_pricing` table:
  - `model_name`, `input_cost_per_1k`, `output_cost_per_1k`, `currency`
  - `effective_date`, `is_active`
- [x] Alembic migrations (`0001_token_schema`)

### 3.4 — Aggregation Engine
- [x] Background scheduler that runs aggregation jobs:
  - Hourly aggregation: runs at :05, aggregates closed hours
  - Daily aggregation: runs at 00:15, aggregates the previous day
  - Weekly/Monthly: roll up from daily summaries (00:30 Mon / 00:45 on the 1st)
- [x] Idempotent aggregation (safe to re-run without duplicates) — upsert on the
      `token_periods` unique key, and stale `(model, source)` rows are removed on re-run
- [x] Aggregation progress tracking — `aggregation_runs` keeps run history, not just
      a last_run column, so "did that window run, and when" stays answerable

Two rules worth carrying into later work:
- **Only closed windows are aggregated.** The in-flight bucket is served live from raw
  events by `/api/tokens/summary` instead.
- **Jobs are self-healing.** The scheduler fills forward from the newest completed run
  rather than assuming "the last hour", so downtime needs no manual backfill.

> **Known gap for 3.2:** catch-up moves forward from a cursor, so an event written with a
> timestamp *older* than the newest completed run gets no hourly/daily bucket. Proxied
> calls are always current, but the remote webhook can report backdated usage — it needs
> to invalidate and re-run the affected windows.

### 3.5 — Cost Calculation
- [x] Model pricing configuration (loaded from DB, seeded by the baseline migration)
- [x] Auto-calculate cost per event using `tokens_in * input_rate + tokens_out * output_rate`,
      resolved at write time — rates change, what a call cost does not
- [x] Support free/local models (cost = 0) via a `*` fallback pricing row
- [ ] Budget threshold configuration per user/session/model
- [ ] Alert when budget threshold exceeded (webhook, log, dashboard notification)

### 3.6 — API Endpoints
- [x] `GET /api/tokens/summary` — current period, read live from raw events
- [x] `GET /api/tokens/history` — historical data with period granularity
- [x] `GET /api/tokens/by-model` — breakdown by model
- [x] `GET /api/tokens/by-source` — local vs remote comparison
- [x] `GET /api/tokens/aggregation` + `POST /api/tokens/aggregate` — run visibility and
      manual catch-up (not in the original spec; needed to operate 3.4)
- [ ] `POST /api/tokens/config` — update pricing / budget settings
- [ ] `GET /api/tokens/budget` — current budget status vs threshold

### 3.7 — Data Retention & Pruning
- [ ] Configurable retention period for raw events (default: 30 days)
- [ ] Scheduled pruning job (daily) that deletes old raw events
- [ ] Aggregated data retained longer (default: 1 year)
- [ ] Pruning respects referential integrity (aggregate before delete)

### 3.8 — Dashboard Integration
- [ ] Token usage widget on dashboard overview
- [ ] Token usage charts (line graph over time, bar chart by model)
- [ ] Cost breakdown pie chart
- [ ] Budget progress bar with alert indicator
- [ ] Period selector (hourly/daily/weekly/monthly)

---

## Acceptance Criteria

- [ ] Every Ollama API call is logged with accurate token counts
- [ ] Remote API token usage can be reported via webhook
- [ ] Token events are aggregated into hourly/daily/weekly/monthly periods
- [ ] Cost is calculated accurately based on configured model pricing
- [ ] Budget alerts trigger when threshold is exceeded
- [ ] Historical data is queryable via API and dashboard
- [ ] Raw events are pruned after configurable retention period
- [ ] Aggregated data survives raw event pruning
- [ ] Dashboard shows real-time and historical token usage
- [ ] All endpoints handle edge cases (no data, zero tokens, unknown models)

---

## Implementation Notes

- **Ollama token counting:** Use `prompt_eval_count` and `eval_count` from Ollama API response
- **Remote tracking:** Provide a simple Python SDK wrapper for common providers
- **Aggregation:** Use SQL window functions or materialized views for fast queries
- **Pricing config:** Ship with sensible defaults (Llama = free, GPT-4 = $0.03/1k in, $0.06/1k out)
- **Performance:** Index `token_events` on `(timestamp, model, source)` for fast range queries
