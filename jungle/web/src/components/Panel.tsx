import type { ReactNode } from "react";

import type { ApiError } from "@/lib/api/client";
import { relativeAge } from "@/lib/api/freshness";
import type { PanelState } from "@/lib/api/panel";

import { RelativeTime } from "./RelativeTime";
import { Text } from "./Text";

/**
 * The panel primitive (DESIGN-BOOK.md §8, §11).
 *
 * Two rules it exists to enforce:
 *
 *   1. **Panels fail independently.** One dead connector never blanks a page, so
 *      every panel owns its own error state.
 *   2. **Empty is not broken.** They get different copy, different iconography
 *      and different colour, always — because Brown Bear's default failure is
 *      silence, and an ambiguous empty panel is how a misconfiguration survives
 *      for days.
 *
 * The minimum height is fixed so a loading or error state does not reflow the
 * page underneath the reader.
 */

const shell = {
  background: "var(--bb-surface-container-low)",
  border: "1px solid var(--bb-outline-variant)",
  borderRadius: "var(--bb-radius-md)",
  boxShadow: "var(--bb-elevation-1)",
  padding: "var(--bb-space-6)",
  minHeight: "180px",
  display: "flex",
  flexDirection: "column",
  gap: "var(--bb-space-3)",
} as const;

export function Panel({
  title,
  action,
  children,
  minHeight,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  minHeight?: string;
}) {
  return (
    <section style={{ ...shell, ...(minHeight ? { minHeight } : {}) }}>
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: "var(--bb-space-3)",
        }}
      >
        <Text role="title-medium" as="h2">
          {title}
        </Text>
        {action}
      </header>
      {children}
    </section>
  );
}

/** The words a reader needs when a panel has nothing to show. */
export function PanelEmpty({ reason, fetchedAt }: { reason: string; fetchedAt: Date }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--bb-space-2)" }}>
      <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
        {reason}
      </Text>
      <Text role="label-small" style={{ color: "var(--bb-on-surface-variant)" }}>
        Nothing to show yet — checked{" "}
        <RelativeTime iso={fetchedAt.toISOString()} initial={relativeAge(fetchedAt)} />. This
        is not an error.
      </Text>
    </div>
  );
}

/**
 * A failed panel. Names the endpoint and one next action.
 *
 * Deliberately distinct from PanelEmpty in colour, glyph and wording: the whole
 * point is that a reader can tell at a glance which of the two they are looking
 * at.
 */
export function PanelError({ error }: { error: ApiError }) {
  const nextStep: Record<ApiError["kind"], string> = {
    timeout: "The service is up but slow. Check load, then retry.",
    status: "The endpoint answered with an error. Check the app logs.",
    shape: "The response did not match its schema — the backend changed. Update the client.",
    network: "The service is unreachable. Check whether its container is running.",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--bb-space-2)" }}>
      <span
        className="bb-label-large"
        style={{ color: "var(--bb-status-critical)", display: "inline-flex", gap: "var(--bb-space-2)" }}
      >
        <span aria-hidden="true">✕</span>
        Not working
      </span>
      <Text role="body-medium" style={{ color: "var(--bb-on-surface)" }}>
        {error.detail}
      </Text>
      <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
        {nextStep[error.kind]}
      </Text>
      <Text role="label-small" style={{ color: "var(--bb-on-surface-variant)" }}>
        Last checked{" "}
        <RelativeTime iso={error.at.toISOString()} initial={relativeAge(error.at)} />.
      </Text>
    </div>
  );
}

/** Fixed-height skeleton, so nothing reflows when data arrives. */
export function PanelLoading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      style={{
        flex: 1,
        borderRadius: "var(--bb-radius-sm)",
        background: "var(--bb-surface-container-high)",
        opacity: 0.6,
        minHeight: "88px",
      }}
    >
      <span className="bb-visually-hidden">Loading…</span>
    </div>
  );
}

/**
 * Render one of the four states. Exhaustive by construction — adding a fifth
 * state to PanelState makes this fail to compile rather than silently skip it.
 */
export function PanelBody<T>({
  state,
  children,
}: {
  state: PanelState<T>;
  children: (data: T, fetchedAt: Date) => ReactNode;
}) {
  switch (state.status) {
    case "loading":
      return <PanelLoading />;
    case "error":
      return <PanelError error={state.error} />;
    case "empty":
      return <PanelEmpty reason={state.reason} fetchedAt={state.fetchedAt} />;
    case "ready":
      return <>{children(state.data, state.fetchedAt)}</>;
  }
}
