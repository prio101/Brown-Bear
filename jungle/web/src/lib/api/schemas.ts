/**
 * Response schemas for every endpoint the dashboard reads (BB-103 §103.1).
 *
 * These are validated at runtime, not merely declared. The types describe what
 * the backend promised; validation catches what it actually sent, and this seam
 * is the only place that gap is cheap to find. A shape change fails here with the
 * endpoint named, instead of rendering NaN three components deep.
 *
 * Shapes were read off the running app on 2026-08-03, not inferred from the
 * Python source — the two disagree more often than anyone expects.
 *
 * Nullable means nullable. `hit_rate: null` means "no samples", which is not
 * zero, and the types force every consumer to decide what to do about it.
 */

import { z } from "zod";

/* --- primitives ---------------------------------------------------------- */

/** ISO-8601 with offset, as FastAPI emits it. */
const Timestamp = z.string();

/** A rate that is null when there were no samples to compute it from. */
const NullableRate = z.number().nullable();

/* --- /api/info ----------------------------------------------------------- */

export const InfoSchema = z.object({
  name: z.string(),
  version: z.string(),
});

/* --- /api/health --------------------------------------------------------- */

export const ServiceHealthSchema = z.object({
  name: z.string(),
  healthy: z.boolean(),
  latency_ms: z.number().nullable().optional(),
  error: z.string().nullable().optional(),
  detail: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const HealthSchema = z.object({
  healthy: z.boolean(),
  services: z.record(z.string(), ServiceHealthSchema),
});

/* --- /api/system --------------------------------------------------------- */

export const SystemSchema = z.object({
  scope: z.string(),
  window_minutes: z.number(),
  samples: z.number(),
  current: z
    .object({
      timestamp: Timestamp,
      cpu_percent: z.number(),
      memory_percent: z.number(),
      memory_used_bytes: z.number(),
      memory_total_bytes: z.number(),
      disk_percent: z.number(),
      disk_used_bytes: z.number(),
      disk_total_bytes: z.number(),
    })
    .nullable(),
  series: z.array(
    z.object({
      timestamp: Timestamp,
      cpu_percent: z.number(),
      memory_percent: z.number(),
      disk_percent: z.number(),
    }),
  ),
});

/* --- /api/cache ---------------------------------------------------------- */

export const CacheSchema = z.object({
  window_minutes: z.number(),
  samples: z.number(),
  // Both null on a cold window. That is a valid response, not an error.
  current: z
    .object({
      timestamp: Timestamp,
      used_memory_bytes: z.number(),
      total_keys: z.number(),
      connected_clients: z.number(),
      keyspace_hits: z.number(),
      keyspace_misses: z.number(),
      lifetime_hit_rate: NullableRate,
    })
    .nullable(),
  window: z.unknown().nullable(),
  series: z.array(
    z.object({
      timestamp: Timestamp,
      hits: z.number(),
      misses: z.number(),
      hit_rate: NullableRate,
      used_memory_bytes: z.number().optional(),
      total_keys: z.number().optional(),
      connected_clients: z.number().optional(),
    }),
  ),
});

/* --- /api/collections ---------------------------------------------------- */

export const CollectionSchema = z.object({
  id: z.string(),
  name: z.string(),
  // Null on a collection created outside the gateway — which is exactly the
  // case BB-107 has to flag rather than render as fine.
  metadata: z
    .object({
      dimension: z.number().optional(),
      embedding_model: z.string().optional(),
      role: z.string().optional(),
    })
    .nullable(),
  dimension: z.number().nullable(),
  count: z.number(),
  error: z.string().nullable(),
});

export const CollectionsSchema = z.object({
  available: z.boolean(),
  api_version: z.string(),
  collection_count: z.number(),
  document_count: z.number(),
  collections: z.array(CollectionSchema),
});

/* --- /api/tokens/* ------------------------------------------------------- */

export const TokenSummarySchema = z.object({
  period: z.string(),
  period_start: Timestamp,
  period_end: Timestamp,
  live: z.boolean(),
  source: z.string(),
  tokens_in: z.number(),
  tokens_out: z.number(),
  total_tokens: z.number(),
  cost: z.number(),
  currency: z.string(),
  request_count: z.number(),
});

export const TokenHistorySchema = z.object({
  period: z.string(),
  start: Timestamp,
  end: Timestamp,
  count: z.number(),
  // True means the series was capped. A chart drawn from a truncated series
  // without saying so is lying, so this must not be swallowed.
  truncated: z.boolean(),
  results: z.array(
    z.object({
      period_start: Timestamp,
      tokens_in: z.number().optional(),
      tokens_out: z.number().optional(),
      total_tokens: z.number().optional(),
      cost: z.number().optional(),
      request_count: z.number().optional(),
    }),
  ),
});

const GroupedTotals = {
  tokens_in: z.number(),
  tokens_out: z.number(),
  total_tokens: z.number(),
  cost: z.number(),
  request_count: z.number(),
};

export const TokensByModelSchema = z.object({
  period: z.string(),
  start: Timestamp,
  end: Timestamp,
  results: z.array(z.object({ model: z.string(), ...GroupedTotals })),
});

export const TokensBySourceSchema = z.object({
  period: z.string(),
  start: Timestamp,
  end: Timestamp,
  results: z.array(z.object({ source: z.string(), ...GroupedTotals })),
});

export const AggregationSchema = z.object({
  latest_completed: z.record(z.string(), Timestamp.nullable()),
  recent_runs: z.array(
    z.object({
      id: z.number(),
      period: z.string(),
      window_start: Timestamp,
      window_end: Timestamp,
      status: z.string(),
      rows_written: z.number().nullable(),
      error: z.string().nullable(),
      started_at: Timestamp.nullable(),
      completed_at: Timestamp.nullable(),
    }),
  ),
});

/* --- /api/settings ------------------------------------------------------- */

export const SettingSchema = z.object({
  key: z.string(),
  label: z.string(),
  value: z.union([z.string(), z.number(), z.boolean(), z.null()]),
  default: z.union([z.string(), z.number(), z.boolean(), z.null()]),
  /** Which layer supplied the effective value — the provenance BB-108 shows. */
  source: z.string(),
  minimum: z.number().nullable().optional(),
  maximum: z.number().nullable().optional(),
  unit: z.string().nullable().optional(),
  help: z.string().nullable().optional(),
  effect: z.string().nullable().optional(),
  type: z.string(),
});

export const SettingsSchema = z.object({
  settings: z.array(SettingSchema),
});

/* --- /ext/health --------------------------------------------------------- */

export const ExtHealthSchema = z.object({
  ready: z.boolean(),
  collections: z.record(
    z.string(),
    z.object({
      id: z.string(),
      // Only cosine distances are comparable to the threshold. Anything else
      // must render as unscoreable, never as a number.
      space: z.string(),
    }),
  ),
  embedding_model: z.string(),
  threshold: z.number(),
  top_k: z.number(),
  ttl_days: z.number(),
});

/* --- inferred types ------------------------------------------------------ */

export type Info = z.infer<typeof InfoSchema>;
export type Health = z.infer<typeof HealthSchema>;
export type ServiceHealth = z.infer<typeof ServiceHealthSchema>;
export type System = z.infer<typeof SystemSchema>;
export type Cache = z.infer<typeof CacheSchema>;
export type Collection = z.infer<typeof CollectionSchema>;
export type Collections = z.infer<typeof CollectionsSchema>;
export type TokenSummary = z.infer<typeof TokenSummarySchema>;
export type TokenHistory = z.infer<typeof TokenHistorySchema>;
export type TokensByModel = z.infer<typeof TokensByModelSchema>;
export type TokensBySource = z.infer<typeof TokensBySourceSchema>;
export type Aggregation = z.infer<typeof AggregationSchema>;
export type Setting = z.infer<typeof SettingSchema>;
export type Settings = z.infer<typeof SettingsSchema>;
export type ExtHealth = z.infer<typeof ExtHealthSchema>;
