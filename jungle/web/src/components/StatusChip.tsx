import type { ReactNode } from "react";

/**
 * Status, never conveyed by colour alone (DESIGN-BOOK.md §2.4, §11).
 *
 * On the light surface `warning` (1.79:1) and `serious` (2.57:1) sit below 3:1
 * deliberately. The icon-plus-label pairing is the mitigation, which is why this
 * component has no variant that renders the dot on its own.
 */

export type StatusRole = "good" | "warning" | "serious" | "critical";

/** Text glyphs rather than an icon font: no extra request, no CSP surface. */
const GLYPH: Record<StatusRole, string> = {
  good: "✓",
  warning: "!",
  serious: "▲",
  critical: "✕",
};

export function StatusChip({
  role,
  label,
  detail,
}: {
  role: StatusRole;
  label: string;
  detail?: ReactNode;
}) {
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: "var(--bb-space-2)" }}>
      <span
        aria-hidden="true"
        className="bb-label-medium"
        style={{
          color: `var(--bb-status-${role})`,
          fontWeight: 700,
        }}
      >
        {GLYPH[role]}
      </span>
      <span className="bb-label-large" style={{ color: `var(--bb-status-${role})` }}>
        {label}
      </span>
      {detail ? (
        <span className="bb-body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
          {detail}
        </span>
      ) : null}
    </span>
  );
}
