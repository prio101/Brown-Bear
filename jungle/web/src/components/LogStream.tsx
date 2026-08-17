"use client";

/**
 * Live log view (BB-301).
 *
 * EventSource rather than polling: the server already streams, and a poll would
 * either lag behind or hammer the endpoint. Same-origin to /api/logs/stream, so
 * the browser resends the credentials it signed in with — EventSource cannot set
 * an Authorization header, which is exactly why the edge accepts a browser session
 * as well as a bearer token.
 *
 * **Newest first.** Rows arrive at the top and older ones move down, so the reader
 * watches one fixed place instead of chasing a growing list downward. It also
 * means a stream that has been open for an hour still opens on what just
 * happened rather than on scrollback.
 *
 * Two behaviours that look like bugs and are not:
 *
 *   - The list is capped. A stream left open overnight would otherwise grow until
 *     the tab dies; the oldest rows are dropped, and the cap is stated on screen.
 *   - Auto-scroll stops the moment you scroll away from the top. A view that yanks
 *     itself back while you are reading scrollback is unusable, so following is
 *     abandoned until you return to the top yourself.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { LogRow } from "@/lib/api/schemas";

/** Rows kept in the DOM. Beyond this the browser, not the server, is the limit. */
const MAX_ROWS = 500;

type Status = "connecting" | "live" | "reconnecting" | "failed";

function detailOf(row: LogRow): string {
  if (row.kind === "query") {
    const latency = row.latency_ms === null || row.latency_ms === undefined ? "?" : row.latency_ms.toFixed(1);
    return `${row.collection ?? "?"} · ${latency}ms · ${row.result_count ?? 0} results · ${row.query_text ?? ""}`;
  }
  const cost = row.cost_usd === null || row.cost_usd === undefined ? null : `$${row.cost_usd.toFixed(4)}`;
  return [
    row.model ?? "?",
    row.endpoint ?? "—",
    `${row.tokens_in ?? 0} in / ${row.tokens_out ?? 0} out`,
    row.source,
    cost,
  ]
    .filter(Boolean)
    .join(" · ");
}

function clockOf(row: LogRow): string {
  if (!row.timestamp) return "--:--:--";
  const parsed = new Date(row.timestamp);
  return Number.isNaN(parsed.getTime()) ? "--:--:--" : parsed.toLocaleTimeString();
}

const rowKey = (row: LogRow) => `${row.kind}:${row.id}`;

export function LogStream({ initial }: { initial: LogRow[] }) {
  // The endpoint returns oldest-first; this view reads newest-first.
  const [rows, setRows] = useState<LogRow[]>(() => [...initial].reverse());
  const [status, setStatus] = useState<Status>("connecting");
  const [paused, setPaused] = useState(false);
  const [beat, setBeat] = useState<string | null>(null);
  const [freshest, setFreshest] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const following = useRef(true);

  useEffect(() => {
    // backlog=0: the server component already rendered the recent rows, and
    // asking for them again would duplicate every one of them on connect.
    const source = new EventSource("/api/logs/stream?backlog=0");

    const append = (event: MessageEvent) => {
      try {
        const row = JSON.parse(event.data) as LogRow;
        setRows((current) => {
          // Ids are per-table, so a query and a token event can share one.
          if (current.some((r) => rowKey(r) === rowKey(row))) return current;
          // Prepend: newest first. The cap drops from the tail, which is the
          // oldest end.
          const next = [row, ...current];
          return next.length > MAX_ROWS ? next.slice(0, MAX_ROWS) : next;
        });
        setFreshest(rowKey(row));
      } catch {
        // A malformed frame is not worth tearing the stream down for.
      }
    };

    source.addEventListener("query", append as EventListener);
    source.addEventListener("token", append as EventListener);
    source.addEventListener("ready", () => setStatus("live"));
    source.addEventListener("heartbeat", (event) => {
      setStatus("live");
      try {
        setBeat(new Date((JSON.parse((event as MessageEvent).data) as { at: string }).at).toLocaleTimeString());
      } catch {
        setBeat(null);
      }
    });
    source.onopen = () => setStatus("live");
    source.onerror = () => {
      // EventSource reconnects on its own; CLOSED means it has given up.
      setStatus(source.readyState === EventSource.CLOSED ? "failed" : "reconnecting");
    };

    return () => source.close();
  }, []);

  useEffect(() => {
    if (paused || !following.current) return;
    const list = listRef.current;
    // Newest is at the top, so following means holding position at the top.
    if (list) list.scrollTop = 0;
  }, [rows, paused]);

  const onScroll = useCallback(() => {
    const list = listRef.current;
    if (!list) return;
    following.current = list.scrollTop < 40;
  }, []);

  const label: Record<Status, string> = {
    connecting: "Connecting…",
    live: "Live",
    reconnecting: "Reconnecting…",
    failed: "Disconnected — reload to reconnect",
  };

  return (
    <div style={{ display: "grid", gap: "var(--bb-space-3)" }}>
      <div style={{ display: "flex", gap: "var(--bb-space-3)", alignItems: "center", flexWrap: "wrap" }}>
        {/* Glyph plus text, never colour alone. */}
        <span className="bb-label-medium" role="status">
          <span aria-hidden="true">{status === "live" ? "●" : status === "failed" ? "✕" : "○"}</span>{" "}
          {label[status]}
        </span>
        <button
          type="button"
          className="bb-interactive"
          onClick={() => setPaused((p) => !p)}
          style={{ font: "inherit", color: "var(--bb-primary)", background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          {paused ? "Resume auto-scroll" : "Pause auto-scroll"}
        </button>
        <span className="bb-body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
          {rows.length} rows shown (newest first, capped at {MAX_ROWS})
          {beat ? ` · last heartbeat ${beat}` : ""}
        </span>
      </div>

      <div className="bb-log-stream" ref={listRef} onScroll={onScroll} tabIndex={0} aria-label="Log stream">
        {rows.length === 0 ? (
          <p className="bb-body-small" style={{ color: "var(--bb-on-surface-variant)", margin: 0 }}>
            Nothing logged yet. Rows appear as soon as anything queries a collection
            or reports token usage.
          </p>
        ) : (
          rows.map((row) => (
            <div
              className="bb-log-row"
              key={rowKey(row)}
              data-fresh={rowKey(row) === freshest ? "true" : undefined}
            >
              <span className="bb-tabular" style={{ color: "var(--bb-on-surface-variant)" }}>
                {clockOf(row)}
              </span>
              <span className="bb-log-kind" style={{ color: row.kind === "query" ? "var(--bb-primary)" : "var(--bb-on-surface)" }}>
                {row.kind}
              </span>
              <span className="bb-log-detail">{detailOf(row)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
