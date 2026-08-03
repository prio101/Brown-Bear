/**
 * Panel state (BB-103 §103.3).
 *
 * Four states, modelled as a union so a component cannot render one while
 * forgetting another. `empty` and `error` are separate variants on purpose:
 * collapsing them is the specific bug this models away. Brown Bear's client hooks
 * fail open — an unreachable gateway, a wrong token, a timeout and a genuine
 * no-match all produce silence — so "nothing to show" and "not working" must never
 * look alike (DESIGN-BOOK.md §11).
 */

import type { ApiError, ApiResult } from "./client";

export type PanelState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T; fetchedAt: Date }
  | { status: "empty"; fetchedAt: Date; reason: string }
  | { status: "error"; error: ApiError };

/**
 * Turn a fetch result into a panel state.
 *
 * `isEmpty` is required rather than optional: whether a successful response
 * counts as empty is a per-panel judgement (`samples: 0` on a cold cache window,
 * an empty `results` array), and defaulting it would quietly render every empty
 * response as though it held data. Pass `() => false` when a panel has no empty
 * case.
 */
export function toPanelState<T>(
  result: ApiResult<T>,
  isEmpty: (data: T) => boolean,
  emptyReason: string,
): PanelState<T> {
  if (!result.ok) return { status: "error", error: result.error };
  if (isEmpty(result.data)) {
    return { status: "empty", fetchedAt: result.fetchedAt, reason: emptyReason };
  }
  return { status: "ready", data: result.data, fetchedAt: result.fetchedAt };
}

/**
 * Issue several requests concurrently.
 *
 * A page that awaits its endpoints in sequence is as slow as their sum. Every
 * result is independent, so one slow or failing endpoint degrades one panel.
 */
// The `| []` in the constraint is load-bearing: it is what makes TypeScript infer
// an array literal as a tuple rather than widening it to a union array. Without
// it every destructured result collapses to the same type, which is silent and
// deeply confusing at the call site. This mirrors lib.es2015's own Promise.all
// signature for that reason.
export function all<T extends readonly unknown[] | []>(
  requests: T,
): Promise<{ -readonly [K in keyof T]: Awaited<T[K]> }> {
  return Promise.all(requests) as Promise<{ -readonly [K in keyof T]: Awaited<T[K]> }>;
}
