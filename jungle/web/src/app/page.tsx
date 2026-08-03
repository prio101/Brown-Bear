import { Text, type TypeRole } from "@/components/Text";
import { ThemeToggle } from "@/components/ThemeToggle";
import { APP_NAME } from "@/lib/config";

/**
 * Token reference page (BB-102).
 *
 * Still a placeholder route as far as the sprint is concerned — no data, no
 * dashboard. It exists so the token layer is visually verifiable in both modes
 * before any page is built on it, which is cheaper than discovering a wrong
 * value in BB-106. BB-105 replaces this with the real overview.
 */

const TYPE_ROLES: readonly TypeRole[] = [
  "display-large", "display-medium", "display-small",
  "headline-large", "headline-medium", "headline-small",
  "title-large", "title-medium", "title-small",
  "body-large", "body-medium", "body-small",
  "label-large", "label-medium", "label-small",
];

const SERIES = [1, 2, 3, 4, 5, 6, 7, 8] as const;

const STATUS = [
  { role: "good", label: "Good" },
  { role: "warning", label: "Warning" },
  { role: "serious", label: "Serious" },
  { role: "critical", label: "Critical" },
] as const;

const card = {
  background: "var(--bb-surface-container-low)",
  border: "1px solid var(--bb-outline-variant)",
  borderRadius: "var(--bb-radius-md)",
  boxShadow: "var(--bb-elevation-1)",
  padding: "var(--bb-space-6)",
  marginBottom: "var(--bb-space-8)",
} as const;

export default function Home() {
  return (
    <main className="bb-page">
      <header
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "var(--bb-space-4)",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "var(--bb-space-8)",
        }}
      >
        <div>
          <Text role="headline-medium" as="h1">
            {APP_NAME} — design tokens
          </Text>
          <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
            Material Design 3 theme generated from one brown seed. Charts keep their own
            fixed, validated palette — a reseed cannot repaint a series.
          </Text>
        </div>
        <ThemeToggle />
      </header>

      <section style={card}>
        <Text role="title-medium" as="h2">Type scale</Text>
        <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)", marginBottom: "var(--bb-space-4)" }}>
          Fifteen roles. There is no sixteenth.
        </Text>
        {TYPE_ROLES.map((role) => (
          <div key={role} style={{ marginBottom: "var(--bb-space-2)" }}>
            <Text role={role}>{role}</Text>
          </div>
        ))}
      </section>

      <section style={card}>
        <Text role="title-medium" as="h2">Theme roles</Text>
        <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)", marginBottom: "var(--bb-space-4)" }}>
          Generated. A reseed changes these and nothing below.
        </Text>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--bb-space-2)" }}>
          {(["primary", "secondary", "tertiary", "error"] as const).map((role) => (
            <div
              key={role}
              className="bb-label-large"
              style={{
                background: `var(--bb-${role})`,
                color: `var(--bb-on-${role})`,
                padding: "var(--bb-space-3) var(--bb-space-4)",
                borderRadius: "var(--bb-radius-sm)",
                minWidth: "120px",
              }}
            >
              {role}
            </div>
          ))}
        </div>
      </section>

      <section style={card}>
        <Text role="title-medium" as="h2">Chart series — fixed slot order</Text>
        <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)", marginBottom: "var(--bb-space-4)" }}>
          Never cycled. Color follows the entity, not its rank. Validated 2026-08-03.
        </Text>
        <div style={{ display: "flex", gap: "2px", background: "var(--bb-chart-surface)", padding: "var(--bb-space-3)", borderRadius: "var(--bb-radius-sm)" }}>
          {SERIES.map((slot) => (
            <div key={slot} style={{ flex: 1, textAlign: "center" }}>
              <div
                style={{
                  height: "48px",
                  background: `var(--bb-series-${slot})`,
                  borderRadius: "var(--bb-radius-xs) var(--bb-radius-xs) 0 0",
                }}
              />
              {/* Text wears ink tokens, never the series color. */}
              <Text role="label-small" style={{ color: "var(--bb-ink-2)" }}>{slot}</Text>
            </div>
          ))}
        </div>
      </section>

      <section style={card}>
        <Text role="title-medium" as="h2">Status — reserved, never a series</Text>
        <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)", marginBottom: "var(--bb-space-4)" }}>
          Always icon plus label. Meaning never rests on hue.
        </Text>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--bb-space-4)" }}>
          {STATUS.map(({ role, label }) => (
            <span
              key={role}
              className="bb-label-large"
              style={{ display: "inline-flex", alignItems: "center", gap: "var(--bb-space-2)" }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: "12px",
                  height: "12px",
                  borderRadius: "var(--bb-radius-full)",
                  background: `var(--bb-status-${role})`,
                }}
              />
              {label}
            </span>
          ))}
        </div>
      </section>

      <section style={card}>
        <Text role="title-medium" as="h2">Focus and state</Text>
        <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)", marginBottom: "var(--bb-space-4)" }}>
          Tab to these. Every interactive element shows a 3px ring at 2px offset.
        </Text>
        <div style={{ display: "flex", gap: "var(--bb-space-4)", flexWrap: "wrap" }}>
          <button
            type="button"
            className="bb-interactive bb-label-large"
            style={{
              background: "var(--bb-primary)",
              color: "var(--bb-on-primary)",
              border: 0,
              borderRadius: "var(--bb-radius-full)",
              padding: "0 var(--bb-space-6)",
              cursor: "pointer",
            }}
          >
            Filled
          </button>
          <button
            type="button"
            className="bb-interactive bb-label-large"
            style={{
              background: "transparent",
              color: "var(--bb-primary)",
              border: "1px solid var(--bb-outline)",
              borderRadius: "var(--bb-radius-full)",
              padding: "0 var(--bb-space-6)",
              cursor: "pointer",
            }}
          >
            Outlined
          </button>
          <button type="button" disabled className="bb-label-large" style={{ borderRadius: "var(--bb-radius-full)", padding: "0 var(--bb-space-6)", minHeight: "var(--bb-touch-target)" }}>
            Disabled
          </button>
        </div>
      </section>
    </main>
  );
}
