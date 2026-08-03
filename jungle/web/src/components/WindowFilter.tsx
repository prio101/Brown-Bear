import Link from "next/link";

/** Sampling window selector. URL state, so a view is shareable and needs no JS. */

export const WINDOWS = [
  { value: 60, label: "1 hour" },
  { value: 360, label: "6 hours" },
  { value: 1440, label: "24 hours" },
  { value: 10080, label: "7 days" },
] as const;

export type WindowMinutes = (typeof WINDOWS)[number]["value"];

export function WindowFilter({
  current,
  basePath,
}: {
  current: WindowMinutes;
  basePath: string;
}) {
  return (
    <div
      role="group"
      aria-label="Window"
      style={{ display: "flex", flexWrap: "wrap", gap: "var(--bb-space-2)", alignItems: "center" }}
    >
      {WINDOWS.map((window) => {
        const active = window.value === current;
        return (
          <Link
            key={window.value}
            href={`${basePath}?minutes=${window.value}`}
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
            {window.label}
          </Link>
        );
      })}
    </div>
  );
}
