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
  getAgentConfig,
  getAgentConfigs,
  getAgentInventory,
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
    ["/ext/agents", getAgentInventory],
    ["/ext/agents/files", () => getAgentConfigs({ limit: 5 })],
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

  // Needs an id, so it cannot join the table above. The detail shape is the one
  // that carries `content`, which no other response includes.
  it("/ext/agents/files/{id} validates", async () => {
    const listing = await getAgentConfigs({ limit: 1 });
    if (!listing.ok) throw new Error(`listing failed: ${listing.error.detail}`);
    const first = listing.data.files[0];
    if (!first) return; // nothing synced on this instance; not a failure
    const detail = await getAgentConfig(first.config_id);
    if (!detail.ok) {
      throw new Error(`detail failed: [${detail.error.kind}] ${detail.error.detail}`);
    }
    expect(detail.data.config_id).toBe(first.config_id);
  });
});
