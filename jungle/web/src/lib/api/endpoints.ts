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
  AggregationSchema,
  CacheSchema,
  CollectionsSchema,
  ExtHealthSchema,
  HealthSchema,
  InfoSchema,
  SettingsSchema,
  SystemSchema,
  TokenHistorySchema,
  TokenSummarySchema,
  TokensByModelSchema,
  TokensBySourceSchema,
  type Aggregation,
  type Cache,
  type Collections,
  type ExtHealth,
  type Health,
  type Info,
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
