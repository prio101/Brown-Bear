import type { ReactNode } from "react";

import type { Provenance } from "@/lib/api/provenance";

import { ProvenanceBadge } from "./ProvenanceBadge";
import { Text } from "./Text";

/**
 * The dashboard's most-used primitive (DESIGN-BOOK.md §8.1).
 *
 * A single number with its identity and its trust context. Required: label,
 * value, provenance, freshness. A bare number with no provenance is not a
 * shortcut, it is a missing fact.
 *
 * The delta is optional but its comparison window is not — a delta without a
 * window is meaningless, so they are one parameter rather than two.
 */

export type Delta = {
  /** Signed change. Sign decides the arrow; `good` decides the colour. */
  ratio: number;
  /** "vs last 7d" — required, and rendered verbatim. */
  window: string;
  /** Whether an increase is good. Tokens rising is not obviously either. */
  higherIsBetter?: boolean;
};

function DeltaLine({ delta }: { delta: Delta }) {
  const rising = delta.ratio >= 0;
  const arrow = rising ? "↑" : "↓";
  const neutral = delta.higherIsBetter === undefined;
  const good = delta.higherIsBetter === undefined ? false : rising === delta.higherIsBetter;

  return (
    <Text
      role="body-small"
      style={{
        color: neutral
          ? "var(--bb-on-surface-variant)"
          : good
            ? "var(--bb-delta-good)"
            : "var(--bb-status-serious)",
      }}
    >
      <span aria-hidden="true">{arrow} </span>
      {Math.abs(delta.ratio * 100).toFixed(0)}% {delta.window}
    </Text>
  );
}

export function StatTile({
  label,
  value,
  delta,
  provenance,
  fetchedAt,
  note,
}: {
  label: string;
  value: string;
  delta?: Delta;
  provenance: Provenance;
  fetchedAt: Date;
  /** For the caveat a number needs, e.g. that a total mixes trust kinds. */
  note?: ReactNode;
}) {
  return (
    <div
      style={{
        background: "var(--bb-surface-container-low)",
        border: "1px solid var(--bb-outline-variant)",
        borderRadius: "var(--bb-radius-md)",
        boxShadow: "var(--bb-elevation-1)",
        padding: "var(--bb-space-4)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--bb-space-1)",
        minHeight: "132px",
      }}
    >
      <Text
        role="label-medium"
        style={{ color: "var(--bb-on-surface-variant)", textTransform: "uppercase" }}
      >
        {label}
      </Text>
      {/* Proportional figures: tabular-nums is for columns that must align. */}
      <Text role="display-small" style={{ color: "var(--bb-on-surface)" }}>
        {value}
      </Text>
      {delta ? <DeltaLine delta={delta} /> : null}
      {note ? (
        <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
          {note}
        </Text>
      ) : null}
      <div style={{ marginTop: "auto" }}>
        <ProvenanceBadge kind={provenance} fetchedAt={fetchedAt} />
      </div>
    </div>
  );
}
