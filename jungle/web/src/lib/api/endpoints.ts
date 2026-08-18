/**
 * Typed accessors, one per endpoint the dashboard reads (BB-103).
 *
 * Read paths only. There is deliberately no write path in this layer: the edge
 * publishes `GET /api/settings` and denies `PUT`, and `POST /api/tokens/aggregate`
 * is denied outright. Both would succeed from here on the Docker network, so the
 * absence is the enforcement.
 */

import "server-only";

import { get, type ApiResult, type GetOptions } from "./client";
import {
  AgentConfigListSchema,
  AgentConfigSchema,
  AgentInventorySchema,
  AggregationSchema,
  CacheSchema,
  CollectionsSchema,
  ExtHealthSchema,
  FileListSchema,
  FileSchema,
  GraphSchema,
  HealthSchema,
  InfoSchema,
  RecentLogsSchema,
  SavingsSchema,
  SettingsSchema,
  SystemSchema,
  TokenHistorySchema,
  TokenSummarySchema,
  TokensByModelSchema,
  TokensBySourceSchema,
  type AgentConfig,
  type AgentConfigList,
  type AgentInventory,
  type Aggregation,
  type Cache,
  type Collections,
  type ExtHealth,
  type FileList,
  type FileRecord,
  type Graph,
  type Health,
  type Info,
  type RecentLogs,
  type Savings,
  type Settings,
  type System,
  type TokenHistory,
  type TokenSummary,
  type TokensByModel,
  type TokensBySource,
} from "./schemas";

/** Embedding a document runs a model, so the gateway gets a longer leash. */
const GATEWAY_TIMEOUT_MS = 15_000;

export const getInfo = (): Promise<ApiResult<Info>> => get("/api/info", InfoSchema);

export const getHealth = (): Promise<ApiResult<Health>> => get("/api/health", HealthSchema);

export const getSystem = (minutes?: number): Promise<ApiResult<System>> =>
  get("/api/system", SystemSchema, { params: { minutes } });

export const getCache = (minutes?: number): Promise<ApiResult<Cache>> =>
  get("/api/cache", CacheSchema, { params: { minutes } });

export const getCollections = (): Promise<ApiResult<Collections>> =>
  get("/api/collections", CollectionsSchema);

export const getTokenSummary = (period?: string): Promise<ApiResult<TokenSummary>> =>
  get("/api/tokens/summary", TokenSummarySchema, { params: { period } });

export const getTokenHistory = (period?: string): Promise<ApiResult<TokenHistory>> =>
  get("/api/tokens/history", TokenHistorySchema, { params: { period } });

export const getTokensByModel = (period?: string): Promise<ApiResult<TokensByModel>> =>
  get("/api/tokens/by-model", TokensByModelSchema, { params: { period } });

export const getTokensBySource = (period?: string): Promise<ApiResult<TokensBySource>> =>
  get("/api/tokens/by-source", TokensBySourceSchema, { params: { period } });

export const getAggregation = (): Promise<ApiResult<Aggregation>> =>
  get("/api/tokens/aggregation", AggregationSchema);

export const getSettings = (): Promise<ApiResult<Settings>> =>
  get("/api/settings", SettingsSchema);

export const getExtHealth = (options: GetOptions = {}): Promise<ApiResult<ExtHealth>> =>
  get("/ext/health", ExtHealthSchema, { timeoutMs: GATEWAY_TIMEOUT_MS, ...options });

/** The memory graph (BB-301). Slower than a row lookup — it reads every document
 * in both collections — so it gets the gateway's longer timeout rather than the
 * 5s default meant for counters. */
export const getGraph = (): Promise<ApiResult<Graph>> =>
  get("/api/graph", GraphSchema, { timeoutMs: GATEWAY_TIMEOUT_MS });

export const getRecentLogs = (limit?: number): Promise<ApiResult<RecentLogs>> =>
  get("/api/logs/recent", RecentLogsSchema, { params: { limit } });

/** Ingested files (spec 007). The list deliberately omits extracted text — a
 * corpus of extractions would be megabytes nobody reads on a list view. */
export const getFiles = (
  params: { project?: string; status?: string; limit?: number } = {},
): Promise<ApiResult<FileList>> =>
  get("/ext/files", FileListSchema, { params, timeoutMs: GATEWAY_TIMEOUT_MS });

export const getFile = (fileId: string): Promise<ApiResult<FileRecord>> =>
  get(`/ext/files/${encodeURIComponent(fileId)}`, FileSchema, {
    timeoutMs: GATEWAY_TIMEOUT_MS,
  });

/** Agent configuration (spec 008). The inventory is grouped in the database, so
 * this response stays the same size whether a machine has ten files or a thousand. */
export const getAgentInventory = (): Promise<ApiResult<AgentInventory>> =>
  get("/ext/agents", AgentInventorySchema, { timeoutMs: GATEWAY_TIMEOUT_MS });

/** One branch's files. Deliberately without their content: a machine's whole
 * configuration would be megabytes of payload for a list nobody reads in full. */
export const getAgentConfigs = (
  params: { machine?: string; scope?: string; project?: string; tool?: string; limit?: number } = {},
): Promise<ApiResult<AgentConfigList>> =>
  get("/ext/agents/files", AgentConfigListSchema, { params, timeoutMs: GATEWAY_TIMEOUT_MS });

export const getAgentConfig = (configId: string): Promise<ApiResult<AgentConfig>> =>
  get(`/ext/agents/files/${encodeURIComponent(configId)}`, AgentConfigSchema, {
    timeoutMs: GATEWAY_TIMEOUT_MS,
  });

/** What the shared memory served and what it actually avoided. */
export const getSavings = (days = 30): Promise<ApiResult<Savings>> =>
  get("/api/tokens/savings", SavingsSchema, { params: { days } });
