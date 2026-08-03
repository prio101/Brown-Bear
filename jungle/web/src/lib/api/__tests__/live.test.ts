/**
 * Schemas versus the real backend.
 *
 * Skipped unless BB_LIVE_API is set, so the default suite stays hermetic and
 * cannot be made red by whether the stack happens to be up:
 *
 *   BB_LIVE_API=1 BB_API_URL=http://127.0.0.1:8080 npx vitest run live
 *
 * Worth having because the schemas were written from observed responses, and the
 * failure this catches — a backend field that changed shape — is invisible to
 * every mocked test in the suite.
 */

import { describe, expect, it } from "vitest";

import {
  getAggregation,
  getCache,
  getCollections,
  getExtHealth,
  getHealth,
  getInfo,
  getSettings,
  getSystem,
  getTokenHistory,
  getTokenSummary,
  getTokensByModel,
  getTokensBySource,
} from "../endpoints";

const live = process.env.BB_LIVE_API ? describe : describe.skip;

live("live API conforms to its schemas", () => {
  const cases = [
    ["/api/info", getInfo],
    ["/api/health", getHealth],
    ["/api/system", () => getSystem(60)],
    ["/api/cache", () => getCache(60)],
    ["/api/collections", getCollections],
    ["/api/tokens/summary", () => getTokenSummary("daily")],
    ["/api/tokens/history", () => getTokenHistory("daily")],
    ["/api/tokens/by-model", () => getTokensByModel("daily")],
    ["/api/tokens/by-source", () => getTokensBySource("daily")],
    ["/api/tokens/aggregation", getAggregation],
    ["/api/settings", getSettings],
    ["/ext/health", () => getExtHealth()],
  ] as const;

  for (const [name, call] of cases) {
    it(`${name} validates`, async () => {
      const result = await call();
      if (!result.ok) {
        // Surface the schema mismatch itself, not a bare "expected true".
        throw new Error(`${name} failed: [${result.error.kind}] ${result.error.detail}`);
      }
      expect(result.ok).toBe(true);
    });
  }
});
