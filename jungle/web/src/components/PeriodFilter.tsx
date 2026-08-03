import Link from "next/link";

/**
 * Period filter (BB-106 §106.4).
 *
 * One row of controls above the charts, never interleaved. State lives in the URL
 * so a view is shareable and survives a reload — and so this stays a server
 * component with no client JS.
 *
 * Links rather than a select: each option is a real, linkable URL, which is also
 * what makes the current selection expressible as aria-current.
 */

export const PERIODS = [
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
] as const;

export type Period = (typeof PERIODS)[number]["value"];

export function PeriodFilter({ current, basePath }: { current: Period; basePath: string }) {
  return (
    <div
      role="group"
      aria-label="Period"
      style={{ display: "flex", flexWrap: "wrap", gap: "var(--bb-space-2)", alignItems: "center" }}
    >
      {PERIODS.map((period) => {
        const active = period.value === current;
        return (
          <Link
            key={period.value}
            href={`${basePath}?period=${period.value}`}
            aria-current={active ? "true" : undefined}
            className="bb-label-large bb-interactive"
            style={{
              textDecoration: "none",
              padding: "var(--bb-space-2) var(--bb-space-4)",
              borderRadius: "var(--bb-radius-full)",
              border: `1px solid ${active ? "transparent" : "var(--bb-outline)"}`,
              background: active ? "var(--bb-secondary-container)" : "transparent",
              color: active ? "var(--bb-on-secondary-container)" : "var(--bb-on-surface-variant)",
              display: "inline-flex",
              alignItems: "center",
            }}
          >
            {period.label}
          </Link>
        );
      })}
    </div>
  );
}
