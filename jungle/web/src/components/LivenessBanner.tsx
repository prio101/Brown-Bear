import { relativeAge } from "@/lib/api/freshness";

import { Text } from "./Text";
import type { StatusRole } from "./StatusChip";

/**
 * The banner that resolves empty-versus-broken (DESIGN-BOOK.md §10.4).
 *
 * This is the most important element on the overview page, and the reason is
 * uncomfortable: Brown Bear's client hooks fail open. An unreachable gateway, a
 * wrong token, a timeout and a genuine no-match all produce *silence*. So an
 * empty dashboard is ambiguous, absence of data is never evidence of health, and
 * something has to say so out loud.
 *
 * Persistent, never a snackbar. A dismissible transient is exactly how a silent
 * failure stays silent for a fortnight.
 */

export type LivenessState = "healthy" | "stale" | "unreachable" | "unknown";

const ROLE: Record<Exclude<LivenessState, "healthy">, StatusRole> = {
  stale: "serious",
  unreachable: "critical",
  unknown: "warning",
};

const GLYPH: Record<Exclude<LivenessState, "healthy">, string> = {
  stale: "▲",
  unreachable: "✕",
  unknown: "!",
};

export function LivenessBanner({
  state,
  affected,
  lastWorked,
  nextStep,
}: {
  state: LivenessState;
  /** What is affected, in the reader's terms. */
  affected: string;
  /** When it last worked. Null means it never has. */
  lastWorked: Date | null;
  /** Exactly one next step. */
  nextStep: string;
}) {
  // Healthy renders nothing: a green "all good" bar trains people to ignore the
  // strip of the page where the real warning will appear.
  if (state === "healthy") return null;

  const role = ROLE[state];

  return (
    <div
      role="status"
      style={{
        display: "flex",
        gap: "var(--bb-space-3)",
        alignItems: "flex-start",
        background: "var(--bb-surface-container-high)",
        borderInlineStart: `4px solid var(--bb-status-${role})`,
        borderRadius: "var(--bb-radius-sm)",
        padding: "var(--bb-space-4)",
        marginBottom: "var(--bb-space-6)",
      }}
    >
      <span
        aria-hidden="true"
        className="bb-title-medium"
        style={{ color: `var(--bb-status-${role})` }}
      >
        {GLYPH[state]}
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--bb-space-1)" }}>
        <Text role="title-small" style={{ color: `var(--bb-status-${role})` }}>
          {state === "stale"
            ? "Data may be out of date"
            : state === "unreachable"
              ? "Not reachable"
              : "Never contacted"}
        </Text>
        <Text role="body-medium">{affected}</Text>
        <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
          {lastWorked
            ? `Last worked ${relativeAge(lastWorked)}.`
            : "No successful contact has ever been recorded."}{" "}
          {nextStep}
        </Text>
      </div>
    </div>
  );
}
