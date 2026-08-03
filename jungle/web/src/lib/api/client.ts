/**
 * The one way the dashboard talks to the backend (BB-103 §103.2).
 *
 * Two design decisions carry most of the weight:
 *
 * 1. **Results, not exceptions.** A thrown error in a server component takes out
 *    the whole render subtree, and the Design Book requires panels to fail
 *    independently. That is a type decision, not a try/catch habit, so `get`
 *    returns a discriminated union and never rejects.
 *
 * 2. **Server-side only.** Calls go to app:8080 on the Docker network, which the
 *    browser cannot reach and does not need to: no API credential ever reaches
 *    client JS. Importing this from a client component is a build error.
 */

import "server-only";

import type { z } from "zod";

import { API_URL } from "@/lib/config";

/** Endpoints the edge denies. Never call them, even though they would succeed
 * server-side on the Docker network — which is precisely why this list exists in
 * code rather than in a comment. */
export const EDGE_DENIED = [
  "PUT /api/settings",
  "POST /api/tokens/aggregate",
  "GET /metrics",
  "POST /ollama/api/pull",
  "POST /ollama/api/create",
  "POST /ollama/api/copy",
  "DELETE /ollama/api/delete",
  "POST /ollama/api/push",
] as const;

export type ApiError = {
  /** The path asked for, so an error message can name it. */
  endpoint: string;
  kind: "timeout" | "status" | "shape" | "network";
  /** HTTP status when there was one. */
  status?: number;
  detail: string;
  /** When the failure was observed — feeds the "last checked" display. */
  at: Date;
};

export type ApiResult<T> =
  | { ok: true; data: T; fetchedAt: Date }
  | { ok: false; error: ApiError };

/** Live operational data. 5s is generous for a local hop and short enough that
 * one wedged connector cannot hold a page open. */
const DEFAULT_TIMEOUT_MS = 5_000;

export type GetOptions = {
  /** Query parameters, appended only when defined. */
  params?: Record<string, string | number | undefined>;
  timeoutMs?: number;
};

function buildUrl(path: string, params: GetOptions["params"]): string {
  const url = new URL(path, API_URL);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }
  return url.toString();
}

/**
 * GET a JSON endpoint and validate it.
 *
 * Reads are never cached: Next caches `fetch` aggressively by default, and a
 * cached token total on an operations dashboard is a correctness bug.
 */
export async function get<S extends z.ZodType>(
  path: string,
  schema: S,
  options: GetOptions = {},
): Promise<ApiResult<z.infer<S>>> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(buildUrl(path, options.params), {
      signal: controller.signal,
      cache: "no-store",
      headers: { accept: "application/json" },
    });

    if (!response.ok) {
      return {
        ok: false,
        error: {
          endpoint: path,
          kind: "status",
          status: response.status,
          detail: `${path} returned ${response.status}`,
          at: new Date(),
        },
      };
    }

    const body: unknown = await response.json();
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      // Name the endpoint. A bare "invalid_type at results.0.cost" sends the
      // reader hunting through components for the source of the data.
      const first = parsed.error.issues[0];
      const where = first?.path.join(".") || "(root)";
      return {
        ok: false,
        error: {
          endpoint: path,
          kind: "shape",
          detail: `${path} response did not match its schema at ${where}: ${first?.message ?? "unknown"}`,
          at: new Date(),
        },
      };
    }

    return { ok: true, data: parsed.data, fetchedAt: new Date() };
  } catch (cause) {
    const aborted = cause instanceof Error && cause.name === "AbortError";
    return {
      ok: false,
      error: {
        endpoint: path,
        kind: aborted ? "timeout" : "network",
        detail: aborted
          ? `${path} did not respond within ${timeoutMs}ms`
          : `${path} was unreachable: ${cause instanceof Error ? cause.message : String(cause)}`,
        at: new Date(),
      },
    };
  } finally {
    clearTimeout(timer);
  }
}
