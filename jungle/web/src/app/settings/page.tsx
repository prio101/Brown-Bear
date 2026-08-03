import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { Text } from "@/components/Text";
import { getSettings } from "@/lib/api/endpoints";
import type { Setting } from "@/lib/api/schemas";
import { toPanelState } from "@/lib/api/panel";

/**
 * Effective configuration, read-only (BB-108).
 *
 * The edge publishes GET /api/settings and denies PUT, so configuration changes
 * happen on the host. The design work is making that boundary read as intentional
 * rather than broken: a control that looks live and returns 403 teaches the reader
 * the product is faulty, where a disabled control with one line of explanation
 * teaches them where the boundary is.
 */

/** Keys whose value must never be rendered, only their presence. */
const SECRET_PATTERN = /token|secret|password|key|credential/i;

function isSecret(setting: Setting): boolean {
  return SECRET_PATTERN.test(setting.key) || SECRET_PATTERN.test(setting.label);
}

/**
 * Presence, not a masked prefix.
 *
 * A mask still leaks length and leading characters, and a page sitting behind one
 * shared token is not the place to spend that.
 */
function renderValue(setting: Setting): string {
  if (isSecret(setting)) {
    return setting.value === null || setting.value === "" ? "not set" : "set";
  }
  if (setting.value === null) return "not set";
  if (typeof setting.value === "boolean") return setting.value ? "on" : "off";
  return `${setting.value}${setting.unit ? ` ${setting.unit}` : ""}`;
}

/** Group by the concern a reader is looking for, not by the backend's ordering. */
const GROUPS: { title: string; match: RegExp }[] = [
  { title: "Context gateway", match: /cache|threshold|top_k|ttl|embedding|chunk|conversation|knowledge/i },
  { title: "Collection & sampling", match: /snapshot|sample|interval|retention/i },
  { title: "Tokens & cost", match: /token|currency|price|cost/i },
  { title: "Scheduling", match: /schedul|aggregat|cron/i },
];

function groupOf(setting: Setting): string {
  return GROUPS.find((group) => group.match.test(setting.key))?.title ?? "Other";
}

export default async function SettingsPage() {
  const settings = await getSettings();

  const state = toPanelState(
    settings,
    (data) => data.settings.length === 0,
    "No settings are exposed by this instance.",
  );

  return (
    <div className="bb-shell">
      <Nav current="/settings" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-4)" }}>
          <Text role="headline-medium" as="h1">
            Settings
          </Text>
        </header>

        {/* The boundary, stated once and plainly. */}
        <div
          style={{
            display: "grid",
            gap: "var(--bb-space-2)",
            background: "var(--bb-surface-container-high)",
            borderInlineStart: "4px solid var(--bb-outline)",
            borderRadius: "var(--bb-radius-sm)",
            padding: "var(--bb-space-4)",
            marginBottom: "var(--bb-space-6)",
          }}
        >
          <Text role="title-small">Read-only through the tunnel</Text>
          <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
            The edge publishes reads and denies writes, so an authenticated remote caller
            can inspect this stack but not reconfigure it. Change these on the host.
          </Text>
          <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
            Most service credentials are hardcoded in <code>compose.yaml</code> rather than
            read from <code>.env</code> — editing <code>.env</code> does not change Postgres,
            Redis or VectorAdmin.
          </Text>
        </div>

        <Panel title="Effective configuration">
          <PanelBody state={state}>
            {(data) => {
              const grouped = new Map<string, Setting[]>();
              for (const setting of data.settings) {
                const key = groupOf(setting);
                grouped.set(key, [...(grouped.get(key) ?? []), setting]);
              }

              return (
                <div style={{ display: "grid", gap: "var(--bb-space-6)" }}>
                  {[...grouped.entries()].map(([group, items]) => (
                    <section key={group} style={{ display: "grid", gap: "var(--bb-space-2)" }}>
                      <Text role="title-small" as="h3">
                        {group}
                      </Text>
                      <div className="bb-scroll-x">
                        <table className="bb-table">
                          <thead>
                            <tr>
                              <th scope="col">Setting</th>
                              <th scope="col" className="bb-num">Value</th>
                              <th scope="col">Source</th>
                              <th scope="col">Editable here</th>
                            </tr>
                          </thead>
                          <tbody>
                            {items.map((setting) => (
                              <tr key={setting.key}>
                                <td>
                                  <span className="bb-body-medium">{setting.label}</span>
                                  <br />
                                  <code className="bb-label-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                                    {setting.key}
                                  </code>
                                </td>
                                <td className="bb-num bb-tabular bb-body-medium">
                                  {renderValue(setting)}
                                </td>
                                <td className="bb-body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                                  {setting.source}
                                </td>
                                <td>
                                  {/* Disabled with the reason inline — never a live-looking
                                      control that returns 403 when pressed. */}
                                  <button
                                    type="button"
                                    disabled
                                    aria-disabled="true"
                                    className="bb-label-medium bb-disabled"
                                    title="Writes are denied at the edge. Change this on the host."
                                    style={{
                                      background: "transparent",
                                      border: "1px solid var(--bb-outline-variant)",
                                      borderRadius: "var(--bb-radius-full)",
                                      padding: "var(--bb-space-1) var(--bb-space-3)",
                                      color: "var(--bb-on-surface-variant)",
                                    }}
                                  >
                                    No — host only
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  ))}
                </div>
              );
            }}
          </PanelBody>
        </Panel>
      </main>
    </div>
  );
}
