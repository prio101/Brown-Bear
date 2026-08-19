/**
 * Is usage still being reported? (BB-205)
 *
 * Token usage is not measured here. A client hook sends it after the model has
 * answered, and those hooks fail open and silent by design — a rejected call, a
 * wrong token, an unreachable gateway and a genuinely quiet afternoon all produce
 * exactly the same thing on this side: nothing. So a zero on the token pages is
 * ambiguous by construction, and it stayed ambiguous through eighteen hours of a
 * dead feed while the page reported itself healthy.
 *
 * The collector's own liveness cannot answer this. It samples the host every 30s
 * from inside the container and was perfectly fresh the whole time; what had
 * stopped was arriving from somewhere else entirely.
 *
 * The rule is deliberately not the collector's. There is no expected interval for
 * a prompt — nobody owes this stack one — so silence is measured against the
 * server's declared window rather than against a multiple of a heartbeat, and
 * "stale" here says *look*, never *broken*.
 */

import { relativeAge } from "./freshness";

import type { LivenessState } from "@/components/LivenessBanner";
import type { TokenSummary } from "./schemas";

export type ReportingHealth = {
  state: LivenessState;
  /** When usage last arrived. Null means it never has. */
  lastWorked: Date | null;
  /** For the banner; empty when healthy. */
  affected: string;
  /** For the banner; empty when healthy. */
  nextStep: string;
  /**
   * One line for the tiles, always present. This is what makes a zero readable:
   * "0 tokens" plus "last report 18 hours ago" is a fact, where "0 tokens" alone
   * is a question.
   */
  note: string;
};

const HOUR_MS = 3_600_000;

export function reportingHealth(
  summary: Pick<TokenSummary, "last_event_at" | "last_event_source" | "stale_after_hours">,
  now: Date = new Date(),
): ReportingHealth {
  if (summary.last_event_at === null) {
    return {
      state: "unknown",
      lastWorked: null,
      affected: "Every token and cost number here. Nothing has ever been reported to this instance.",
      nextStep:
        "Install the client hooks on a machine that calls a model — usage is reported by the client, and this stack cannot measure what it never sees.",
      note: "No usage has ever been reported.",
    };
  }

  const lastWorked = new Date(summary.last_event_at);
  const age = Math.max(0, now.getTime() - lastWorked.getTime());
  const window = summary.stale_after_hours * HOUR_MS;
  const from = summary.last_event_source ? ` from ${summary.last_event_source}` : "";
  const note = `Last report ${relativeAge(lastWorked, now)}${from}.`;

  if (age <= window) {
    return { state: "healthy", lastWorked, affected: "", nextStep: "", note };
  }

  return {
    state: "stale",
    lastWorked,
    // Says look, not broken: a quiet weekend produces this too, and a banner that
    // cries failure over an idle Sunday is one people learn to scroll past.
    affected: `Every token and cost number here. Nothing has been reported for over ${summary.stale_after_hours}h — either nobody has run a prompt, or reporting is failing silently.`,
    nextStep:
      "On a machine that reports, check the Stop hook: it posts to /ext/exchange and swallows its own errors, so a rejected call leaves no trace there either.",
    note,
  };
}
