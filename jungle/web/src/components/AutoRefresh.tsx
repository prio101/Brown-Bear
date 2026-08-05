"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { relativeAge } from "@/lib/api/freshness";

import { RelativeTime } from "./RelativeTime";

/**
 * Keeps a server-rendered page current (BB-203, option A).
 *
 * `router.refresh()` re-runs the page's server components and streams fresh
 * markup in. That reuses the entire typed data layer unchanged, adds no endpoint,
 * needs no edge configuration, and keeps every API credential server-side — which
 * client-side polling of `/api/*` would not (sprint-1 decision D1).
 *
 * `renderedAt` comes from the server on each render, so after a refresh the
 * "updated" label moves on its own. There is deliberately no client-side "last
 * refreshed" state: the honest answer is when the *data* was fetched, not when a
 * timer last fired, and those differ whenever a refresh fails.
 */

export const STORAGE_KEY = "bb-autorefresh-paused";

/**
 * The server samples host and cache metrics every 30s
 * (`BB_SNAPSHOT_INTERVAL_SECONDS`, `BB_CACHE_SAMPLE_INTERVAL_SECONDS`).
 *
 * Exported so a test can assert the two stay aligned: refreshing faster than the
 * data can change surfaces nothing new and only adds load to a box that is also
 * running a model server.
 */
export const SERVER_SAMPLE_INTERVAL_MS = 30_000;
export const DEFAULT_REFRESH_MS = SERVER_SAMPLE_INTERVAL_MS;

export function AutoRefresh({
  renderedAt,
  intervalMs = DEFAULT_REFRESH_MS,
}: {
  renderedAt: string;
  intervalMs?: number;
}) {
  const router = useRouter();
  const [paused, setPaused] = useState(false);
  const [ready, setReady] = useState(false);

  // Read the stored preference after mount: touching localStorage during render
  // would make the server and client markup disagree.
  useEffect(() => {
    try {
      setPaused(localStorage.getItem(STORAGE_KEY) === "true");
    } catch {
      // Storage unavailable — refreshing stays on, which is the safe default for
      // an operations dashboard.
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready || paused) return;

    const timer = setInterval(() => {
      // A hidden tab cannot be read, so refreshing it is pure load on a box that
      // is also running a model server.
      if (document.visibilityState === "hidden") return;
      router.refresh();
    }, intervalMs);

    return () => clearInterval(timer);
  }, [ready, paused, intervalMs, router]);

  const toggle = () => {
    const next = !paused;
    setPaused(next);
    try {
      localStorage.setItem(STORAGE_KEY, String(next));
    } catch {
      // Preference is not persisted; the toggle still works for this page.
    }
    // Resuming should show current data immediately rather than waiting out a
    // full interval.
    if (!next) router.refresh();
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--bb-space-3)",
        flexWrap: "wrap",
      }}
    >
      <span className="bb-label-small" style={{ color: "var(--bb-on-surface-variant)" }}>
        {paused ? "Paused · data from " : "Updated "}
        <RelativeTime iso={renderedAt} initial={relativeAge(new Date(renderedAt))} />
      </span>

      <button
        type="button"
        onClick={toggle}
        aria-pressed={paused}
        className="bb-label-medium bb-interactive"
        style={{
          background: "transparent",
          border: "1px solid var(--bb-outline-variant)",
          borderRadius: "var(--bb-radius-full)",
          padding: "var(--bb-space-1) var(--bb-space-4)",
          color: "var(--bb-on-surface-variant)",
          cursor: "pointer",
          minHeight: "var(--bb-touch-target)",
        }}
      >
        {paused ? "Resume auto-refresh" : "Pause auto-refresh"}
      </button>

      <button
        type="button"
        onClick={() => router.refresh()}
        className="bb-label-medium bb-interactive"
        style={{
          background: "transparent",
          border: "1px solid var(--bb-outline-variant)",
          borderRadius: "var(--bb-radius-full)",
          padding: "var(--bb-space-1) var(--bb-space-4)",
          color: "var(--bb-on-surface-variant)",
          cursor: "pointer",
          minHeight: "var(--bb-touch-target)",
        }}
      >
        Refresh now
      </button>
    </div>
  );
}
