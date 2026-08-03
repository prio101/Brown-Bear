# Feature: Dataset Pruning & Compaction

**Status:** Open
**Priority:** Medium
**Date:** 2026-07-30

---

## Overview

Implement automated pruning and compaction of ChromaDB datasets (collections) to manage storage growth, remove unused/orphaned data, and optimize query performance. This includes detecting stale documents, compacting fragmented collections, and providing manual cleanup tools through the dashboard.

---

## Requirements

### Pruning (Deletion)
- Identify documents that are no longer referenced or accessed
- Configurable staleness criteria:
  - Documents older than N days with no recent queries
  - Documents below a relevance threshold (low similarity scores on recent queries)
  - Orphaned documents (embedding exists but source document deleted)
- Dry-run mode: preview what would be deleted before committing
- Batch deletion with progress tracking

### Compaction (Optimization)
- Rebuild fragmented ChromaDB collections for faster queries
- Merge small collections into larger ones (configurable threshold)
- Re-embed documents if model has been upgraded (re-embedding pipeline)
- Compression of metadata storage

### Scheduling
- Automated pruning/compaction on configurable schedules
- Manual trigger via dashboard or API
- Run during low-traffic periods (configurable maintenance window)

### Safety
- Backup before destructive operations
- Soft-delete with configurable grace period (recoverable for N days)
- Audit log of all pruning/compaction operations
- Size/scope limits to prevent accidental mass deletion

---

## Subtasks

### 4.1 — Pruning Engine
- [ ] Create `jungle/maintenance/` module
- [ ] `StalenessDetector` — identifies documents meeting pruning criteria:
  - Age-based: documents older than threshold
  - Access-based: documents not queried in N days
  - Relevance-based: documents with consistently low similarity scores
  - Orphaned: references to deleted source documents
- [ ] Dry-run mode: return list of candidates without deleting
- [ ] Batch deletion with configurable batch size (default: 100 docs/batch)
- [ ] Progress tracking per pruning job

### 4.2 — Compaction Engine
- [ ] `CollectionCompactor` — rebuilds ChromaDB collection:
  - Read all documents + embeddings
  - Drop and recreate collection
  - Re-insert documents in optimized order
  - Verify integrity post-compaction
- [ ] `CollectionMerger` — merges small collections:
  - Threshold: collections with < N documents
  - Merge into parent/category collection
  - Preserve metadata and IDs
- [ ] `ReEmbedder` — re-embeds documents with new model:
  - Accept target model name as parameter
  - Process in batches to avoid memory issues
  - Compare old vs new embedding dimensions

### 4.3 — Database Schema
- [ ] `maintenance_jobs` table:
  - `id`, `job_type` (prune|compact|merge|reembed)
  - `status` (pending|running|completed|failed)
  - `collection_name`, `criteria_json`, `result_json`
  - `started_at`, `completed_at`, `duration_ms`
- [ ] `pruned_documents` table (soft-delete tracking):
  - `id`, `collection_name`, `document_id`
  - `pruned_at`, `expires_at` (grace period)
  - `reason` (stale|orphaned|low_relevance|manual)
  - `restored_at` (null if not restored)
- [ ] `maintenance_schedules` table:
  - `id`, `job_type`, `cron_expression`
  - `is_enabled`, `last_run`, `next_run`
- [ ] Alembic migrations

### 4.4 — Staleness Detection Rules
- [ ] Rule: Age-based pruning (documents older than X days)
- [ ] Rule: Access-based pruning (not queried in X days)
- [ ] Rule: Low-relevance pruning (avg similarity < threshold on recent queries)
- [ ] Rule: Orphan detection (document ID not in source system)
- [ ] Rule: Size-based pruning (collections exceeding size limit)
- [ ] Configurable rule combination (AND/OR logic)

### 4.5 — Backup & Recovery
- [ ] Pre-prune backup: export collection to JSON before deletion
- [ ] Soft-delete with grace period (configurable, default: 7 days)
- [ ] Restore command: recover soft-deleted documents within grace period
- [ ] Backup storage management (auto-cleanup of old backups)

### 4.6 — API Endpoints
- [ ] `POST /api/maintenance/prune` — trigger pruning (with dry-run option)
- [ ] `POST /api/maintenance/compact` — trigger compaction
- [ ] `POST /api/maintenance/merge` — trigger collection merge
- [ ] `POST /api/maintenance/reembed` — trigger re-embedding
- [ ] `GET /api/maintenance/status` — job status and history
- [ ] `GET /api/maintenance/candidates` — list pruning candidates
- [ ] `POST /api/maintenance/restore/{id}` — restore soft-deleted document
- [ ] `GET /api/maintenance/schedules` — list configured schedules
- [ ] `PUT /api/maintenance/schedules/{id}` — update schedule config

### 4.7 — Scheduling System
- [ ] Cron-like scheduler (APScheduler or custom)
- [ ] Configurable maintenance window (e.g., 2:00 AM - 5:00 AM)
- [ ] Job queue with priority (compact before prune)
- [ ] Concurrency control (one maintenance job at a time)
- [ ] Notification on job completion/failure

### 4.8 — Dashboard Integration
- [ ] Maintenance overview page:
  - Total collections, total documents, total storage size
  - Last pruning run: date, documents removed, space freed
  - Last compaction run: date, duration, improvement
- [ ] Collection health view:
  - Per-collection: document count, storage size, last access time
  - Health score (freshness + access frequency)
- [ ] Maintenance jobs history log
- [ ] Schedule configuration UI
- [ ] Manual trigger buttons with confirmation dialogs

### 4.9 — Metrics & Monitoring
- [ ] Track: documents pruned per run, space reclaimed
- [ ] Track: compaction duration, query performance improvement
- [ ] Track: collection health scores over time
- [ ] Export maintenance reports

---

## Acceptance Criteria

- [ ] Stale documents are correctly identified by configured criteria
- [ ] Dry-run mode shows candidates without deleting
- [ ] Pruning removes documents and frees ChromaDB storage
- [ ] Soft-deleted documents can be restored within grace period
- [ ] Compaction rebuilds collections with no data loss
- [ ] Small collections can be merged into larger ones
- [ ] Re-embedding pipeline works with model upgrades
- [ ] Maintenance jobs run on configured schedules
- [ ] All operations are logged and auditable
- [ ] Dashboard shows collection health and maintenance history
- [ ] Backup is created before destructive operations
- [ ] Concurrency: only one maintenance job runs at a time

---

## Implementation Notes

- **ChromaDB operations:** Use ChromaDB Python client for collection management
- **Batch processing:** Process in chunks of 100-500 documents to avoid memory spikes
- **Soft-delete:** Use metadata flag (`_soft_deleted: true`) rather than actual deletion during grace period
- **Compaction:** For ChromaDB, "compaction" means exporting and re-importing (no built-in compact command)
- **Orphan detection:** Compare ChromaDB document IDs against a source-of-truth registry (configurable)
- **Scheduling:** APScheduler with cron triggers; job state persisted in PostgreSQL
