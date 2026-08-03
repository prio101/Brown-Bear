import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { EDGE_DENIED, get } from "../client";
import { CacheSchema } from "../schemas";

const Probe = z.object({ value: z.number() });

function respondWith(body: unknown, init: { status?: number } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(typeof body === "string" ? body : JSON.stringify(body), {
        status: init.status ?? 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("get", () => {
  it("returns data and a fetch timestamp on success", async () => {
    respondWith({ value: 42 });

    const result = await get("/probe", Probe);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.value).toBe(42);
    expect(result.fetchedAt).toBeInstanceOf(Date);
  });

  it("reports a non-200 as a status error rather than throwing", async () => {
    respondWith({ detail: "nope" }, { status: 503 });

    const result = await get("/probe", Probe);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("status");
    expect(result.error.status).toBe(503);
    expect(result.error.endpoint).toBe("/probe");
  });

  it("reports a malformed body as a shape error and names the endpoint", async () => {
    respondWith({ value: "not a number" });

    const result = await get("/probe", Probe);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("shape");
    // Naming the endpoint is the point: a bare zod message sends the reader
    // hunting through components for the source of the data.
    expect(result.error.detail).toContain("/probe");
    expect(result.error.detail).toContain("value");
  });

  it("reports unparseable JSON as a network error, not a crash", async () => {
    respondWith("<html>gateway timeout</html>");

    const result = await get("/probe", Probe);

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("network");
  });

  it("times out rather than hanging, and says how long it waited", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: { signal?: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          });
        }),
      ),
    );

    const result = await get("/probe", Probe, { timeoutMs: 20 });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("timeout");
    expect(result.error.detail).toContain("20ms");
  });

  it("never caches: a dashboard read must not be served from a stale cache", async () => {
    // Parameters are declared so the recorded calls are typed; an inferred
    // zero-arg mock makes mock.calls a tuple of length 0.
    const spy = vi.fn(async (_url: string | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ value: 1 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);

    await get("/probe", Probe);

    expect(spy.mock.calls[0]?.[1]).toMatchObject({ cache: "no-store" });
  });

  it("appends only defined query parameters", async () => {
    const spy = vi.fn(async (_url: string | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ value: 1 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);

    await get("/probe", Probe, { params: { minutes: 60, period: undefined } });

    const url = String(spy.mock.calls[0]?.[0]);
    expect(url).toContain("minutes=60");
    expect(url).not.toContain("period");
  });
});

describe("nullable rates", () => {
  it("keeps a null hit_rate null instead of coercing it to zero", async () => {
    // `null` means "no samples". Rendering it as 0% turns "we have no idea" into
    // "the cache is failing", which is a worse lie than showing nothing.
    respondWith({
      window_minutes: 60,
      samples: 2,
      current: null,
      window: null,
      series: [
        { timestamp: "2026-08-03T15:00:00+00:00", hits: 0, misses: 0, hit_rate: null },
        { timestamp: "2026-08-03T15:00:30+00:00", hits: 3, misses: 1, hit_rate: 0.75 },
      ],
    });

    const result = await get("/api/cache", CacheSchema);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.series[0]?.hit_rate).toBeNull();
    expect(result.data.series[1]?.hit_rate).toBe(0.75);
  });

  it("accepts a cold window: samples 0 and current null are valid, not an error", async () => {
    respondWith({ window_minutes: 60, samples: 0, current: null, window: null, series: [] });

    const result = await get("/api/cache", CacheSchema);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.samples).toBe(0);
    expect(result.data.current).toBeNull();
  });
});

describe("edge-denied routes", () => {
  it("documents the write paths the frontend must never call", () => {
    // These succeed server-side on the Docker network, which is exactly why the
    // denial has to live in code rather than in a comment.
    expect(EDGE_DENIED).toContain("PUT /api/settings");
    expect(EDGE_DENIED).toContain("POST /api/tokens/aggregate");
    expect(EDGE_DENIED).toContain("GET /metrics");
  });

  it("exposes no write helper at all", async () => {
    const client = await import("../client");
    const endpoints = await import("../endpoints");

    for (const exported of [...Object.keys(client), ...Object.keys(endpoints)]) {
      expect(exported).not.toMatch(/^(put|post|patch|delete|write|update|set)[A-Z]?/i);
    }
  });
});
