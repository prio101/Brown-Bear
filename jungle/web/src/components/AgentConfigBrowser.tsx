"use client";

/**
 * Agent configuration browser (spec 008 §8.5).
 *
 * The four levels of the address are the navigation — machine, then Global or a
 * project, then the tool — and then the files under it. Three rows of chips rather
 * than an expanding tree: the depth is fixed at three, and a tree widget for a
 * fixed three levels is machinery for nothing.
 *
 * Two things this component must not do, both of which would be easy:
 *
 *   1. **Present a stale configuration as current.** A sync is a deliberate client
 *      action, so silence is the normal state, and every row carries the age of
 *      the sync it came from. `reported` provenance, not `measured`: this is a
 *      machine's claim about itself, and nothing here can verify it.
 *   2. **Render an empty content pane as an empty file.** A `binary` or oversized
 *      file has no stored content *by design*; saying so is the whole difference
 *      between "nothing was in it" and "we did not keep it".
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { relativeAge } from "@/lib/api/freshness";
import type { AgentConfig, AgentInventory, AgentRevision } from "@/lib/api/schemas";
import { bytes as formatBytes, count } from "@/lib/format";

import { ProvenanceBadge } from "./ProvenanceBadge";
import { RelativeTime } from "./RelativeTime";
import { StatusChip, type StatusRole } from "./StatusChip";

type Selection = { machine: string; scope: string; project: string; tool: string };

const STATUS_COPY: Record<string, { role: StatusRole; label: string; detail: string }> = {
  synced: { role: "good", label: "Synced", detail: "present in the machine's last sync" },
  removed: {
    role: "serious",
    label: "Removed",
    detail: "gone from the machine; the last synced content is kept",
  },
};

const KIND_COPY: Record<string, string> = {
  text: "",
  binary: "Not UTF-8, so no content was kept. Its address, size and digest are recorded.",
  too_large:
    "Over the 256 KB per-file cap, so no content was kept. It was not truncated — half a configuration file is a configuration that exists on no machine.",
};

function Chip({
  label,
  detail,
  active,
  onSelect,
}: {
  label: string;
  detail?: string;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className="bb-graph-chip bb-interactive"
      data-off={active ? undefined : "true"}
      aria-pressed={active}
      onClick={onSelect}
    >
      <span className="bb-label-large">{label}</span>
      {detail ? <span className="bb-body-small">{detail}</span> : null}
    </button>
  );
}

export function AgentConfigBrowser({
  inventory,
  initial,
  initialSelection,
}: {
  inventory: AgentInventory;
  /** The first branch's files, fetched server-side so the page is useful on
   * first paint rather than after a round trip. */
  initial: AgentConfig[];
  initialSelection: Selection | null;
}) {
  const [selection, setSelection] = useState<Selection | null>(initialSelection);
  const [files, setFiles] = useState<AgentConfig[]>(initial);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initial[0]?.config_id ?? null);
  const [detail, setDetail] = useState<AgentConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [history, setHistory] = useState<AgentRevision[]>([]);
  const [kept, setKept] = useState(0);
  /** A past revision the reader has opened. Null means the current content —
   * which must be the default, or the page shows history as though it were now. */
  const [viewing, setViewing] = useState<AgentRevision | null>(null);

  const machine = useMemo(
    () => inventory.machines.find((m) => m.machine === selection?.machine) ?? null,
    [inventory.machines, selection?.machine],
  );
  const scope = useMemo(
    () =>
      machine?.scopes.find(
        (s) => s.scope === selection?.scope && s.project === selection?.project,
      ) ?? null,
    [machine, selection?.scope, selection?.project],
  );

  const loadBranch = useCallback(async (next: Selection) => {
    setListError(null);
    const params = new URLSearchParams({
      machine: next.machine,
      scope: next.scope,
      tool: next.tool,
      limit: "500",
    });
    if (next.project) params.set("project", next.project);
    try {
      // Straight to the gateway from the browser: same origin, so the edge's
      // authentication already applies and no credential lives in client JS.
      const response = await fetch(`/ext/agents/files?${params}`, {
        headers: { accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`the gateway returned ${response.status}`);
      const body = (await response.json()) as { files: AgentConfig[] };
      setFiles(body.files);
      setSelectedId(body.files[0]?.config_id ?? null);
      setDetail(null);
    } catch (cause) {
      setListError(cause instanceof Error ? cause.message : String(cause));
      setFiles([]);
      setSelectedId(null);
    }
  }, []);

  const select = useCallback(
    (next: Selection) => {
      setSelection(next);
      void loadBranch(next);
    },
    [loadBranch],
  );

  useEffect(() => {
    setViewing(null);
    setHistory([]);
    if (!selectedId) return;
    let cancelled = false;
    fetch(`/ext/agents/files/${encodeURIComponent(selectedId)}/revisions`, {
      headers: { accept: "application/json" },
      cache: "no-store",
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((body: { revisions?: AgentRevision[]; kept?: number } | null) => {
        if (cancelled || !body) return;
        setHistory(body.revisions ?? []);
        setKept(body.kept ?? 0);
      })
      // History is an extra, not the point of the page: a failure here must not
      // take the content pane with it.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const openRevision = useCallback(
    async (row: AgentRevision) => {
      if (row.current) {
        setViewing(null);
        return;
      }
      try {
        const response = await fetch(
          `/ext/agents/files/${encodeURIComponent(row.config_id)}/revisions/${row.revision}`,
          { headers: { accept: "application/json" }, cache: "no-store" },
        );
        if (!response.ok) throw new Error(`the gateway returned ${response.status}`);
        setViewing((await response.json()) as AgentRevision);
      } catch {
        setViewing(null);
      }
    },
    [],
  );

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setDetailError(null);
    // Fetched on selection: the list omits content, and a whole machine's
    // configuration would be megabytes of payload nobody scrolls through.
    fetch(`/ext/agents/files/${encodeURIComponent(selectedId)}`, {
      headers: { accept: "application/json" },
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`the gateway returned ${response.status}`);
        return (await response.json()) as AgentConfig;
      })
      .then((body) => {
        if (!cancelled) setDetail(body);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setDetailError(cause instanceof Error ? cause.message : String(cause));
          setDetail(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  if (inventory.machines.length === 0) {
    return (
      <p className="bb-body-medium bb-graph-note">
        No machine has synced its configuration yet. On a machine, run{" "}
        <code>python3 bb_sync.py</code> in a checkout, or{" "}
        <code>python3 bb_sync.py --global</code> for <code>~/.claude</code>. Nothing is
        collected automatically — a sync is always something someone asks for.
      </p>
    );
  }

  const selected = detail ?? files.find((f) => f.config_id === selectedId) ?? null;

  return (
    <div className="bb-agents">
      <div className="bb-agents-levels">
        <div className="bb-agents-level">
          <span className="bb-graph-detail-kind">Machine</span>
          <div className="bb-agents-chips">
            {inventory.machines.map((entry) => (
              <Chip
                key={entry.machine}
                label={entry.machine}
                detail={`${count(entry.files)} files`}
                active={entry.machine === selection?.machine}
                onSelect={() => {
                  const firstScope = entry.scopes[0];
                  const firstTool = firstScope?.tools[0];
                  if (!firstScope || !firstTool) return;
                  select({
                    machine: entry.machine,
                    scope: firstScope.scope,
                    project: firstScope.project,
                    tool: firstTool.tool,
                  });
                }}
              />
            ))}
          </div>
        </div>

        <div className="bb-agents-level">
          {/* The requirement's second level: one machine-wide configuration, and
              one per project. */}
          <span className="bb-graph-detail-kind">Global / project</span>
          <div className="bb-agents-chips">
            {(machine?.scopes ?? []).map((entry) => (
              <Chip
                key={`${entry.scope}:${entry.project}`}
                label={entry.label}
                detail={`${count(entry.files)} files`}
                active={entry.scope === selection?.scope && entry.project === selection?.project}
                onSelect={() => {
                  const firstTool = entry.tools[0];
                  if (!firstTool || !selection) return;
                  select({
                    machine: selection.machine,
                    scope: entry.scope,
                    project: entry.project,
                    tool: firstTool.tool,
                  });
                }}
              />
            ))}
          </div>
        </div>

        <div className="bb-agents-level">
          <span className="bb-graph-detail-kind">Tool</span>
          <div className="bb-agents-chips">
            {(scope?.tools ?? []).map((entry) => (
              <Chip
                key={entry.tool}
                label={entry.tool}
                detail={`${count(entry.files)} files · ${formatBytes(entry.bytes)}`}
                active={entry.tool === selection?.tool}
                onSelect={() => selection && select({ ...selection, tool: entry.tool })}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="bb-file-layout">
        {listError ? (
          <p className="bb-body-medium" style={{ color: "var(--bb-status-critical)" }}>
            <span aria-hidden="true">✕</span> Could not list this branch: {listError}. The app
            answered, so check its logs rather than the machine that synced.
          </p>
        ) : files.length === 0 ? (
          <p className="bb-body-medium bb-graph-note">
            Nothing under this tool for this scope. That is an empty branch, not a
            failure — the machine has synced other branches.
          </p>
        ) : (
          <ul className="bb-file-list" aria-label="Configuration files">
            {files.map((file) => {
              const active = file.config_id === selectedId;
              const status = STATUS_COPY[file.status];
              return (
                <li key={file.config_id}>
                  <button
                    type="button"
                    className="bb-interactive bb-file-row"
                    aria-current={active ? "true" : undefined}
                    data-active={active ? "true" : undefined}
                    onClick={() => setSelectedId(file.config_id)}
                  >
                    <span className="bb-body-medium bb-file-name">{file.path}</span>
                    <span className="bb-body-small bb-file-meta">
                      {formatBytes(file.size_bytes)} · rev {file.revision}
                      {file.redactions > 0 ? ` · ${file.redactions} masked` : ""}
                    </span>
                    {status ? (
                      <StatusChip role={status.role} label={status.label} />
                    ) : (
                      <span className="bb-label-medium">{file.status}</span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <section className="bb-file-detail" aria-label="Configuration file detail">
          {selected === null ? (
            <p className="bb-body-medium bb-graph-note">Select a file.</p>
          ) : (
            <>
              <header>
                <h3 className="bb-title-medium" style={{ margin: 0, overflowWrap: "anywhere" }}>
                  {selected.path}
                </h3>
                <p className="bb-body-small bb-graph-note" style={{ margin: "4px 0 0" }}>
                  {selected.machine} · {selected.label} · {selected.tool}
                </p>
                {selected.last_synced_at ? (
                  <div style={{ marginTop: "var(--bb-space-2)" }}>
                    {/* A machine's claim about its own configuration. Nothing here
                        can check it, so it is never labelled `measured`. */}
                    <ProvenanceBadge
                      kind="reported"
                      fetchedAt={new Date(selected.last_synced_at)}
                    />
                  </div>
                ) : null}
              </header>

              <dl className="bb-graph-dl">
                {[
                  ["status", STATUS_COPY[selected.status]?.detail ?? selected.status],
                  ["revision", `${selected.revision} (counts distinct contents, not syncs)`],
                  ["size", formatBytes(selected.size_bytes)],
                  [
                    "masked values",
                    selected.redactions > 0
                      ? `${selected.redactions} in the stored text`
                      : "none recognised",
                  ],
                  ["digest of what arrived", `${selected.sha256.slice(0, 24)}…`],
                ].map(([term, value]) => (
                  <div className="bb-graph-field" key={term}>
                    <dt className="bb-body-small">{term}</dt>
                    <dd className="bb-body-small">{value}</dd>
                  </div>
                ))}
                <div className="bb-graph-field">
                  <dt className="bb-body-small">last synced</dt>
                  <dd className="bb-body-small">
                    {selected.last_synced_at ? (
                      <RelativeTime
                        iso={selected.last_synced_at}
                        initial={relativeAge(new Date(selected.last_synced_at))}
                      />
                    ) : (
                      "never"
                    )}
                  </dd>
                </div>
                <div className="bb-graph-field">
                  <dt className="bb-body-small">content last changed</dt>
                  <dd className="bb-body-small">
                    {selected.changed_at ? (
                      <RelativeTime
                        iso={selected.changed_at}
                        initial={relativeAge(new Date(selected.changed_at))}
                      />
                    ) : (
                      "unknown"
                    )}
                  </dd>
                </div>
              </dl>

              {selected.status === "removed" ? (
                <p className="bb-body-small bb-graph-note">
                  This file is no longer on the machine. Its last synced content is kept
                  below, because a file that disappeared is information.
                </p>
              ) : null}

              {history.length > 0 ? (
                <div>
                  <span className="bb-graph-detail-kind">
                    History — {history.length} of the last {kept} kept
                  </span>
                  <ul className="bb-revisions" aria-label="Revision history">
                    {history.map((row) => {
                      const open = viewing?.revision === row.revision;
                      const isCurrent = row.current && viewing === null;
                      return (
                        <li key={row.revision}>
                          <button
                            type="button"
                            className="bb-interactive bb-revision"
                            data-active={open || isCurrent ? "true" : undefined}
                            onClick={() => void openRevision(row)}
                          >
                            <span className="bb-body-small">
                              rev {row.revision}
                              {row.current ? " · current" : ""}
                            </span>
                            <span className="bb-body-small bb-file-meta">
                              {formatBytes(row.size_bytes)}
                              {row.redactions > 0 ? ` · ${row.redactions} masked` : ""} ·{" "}
                              {row.created_at ? (
                                <RelativeTime
                                  iso={row.created_at}
                                  initial={relativeAge(new Date(row.created_at))}
                                />
                              ) : (
                                "unknown age"
                              )}
                            </span>
                            {/* The restore verdict comes from the server, which owns
                                the masking rules. Shown here so a reader knows before
                                trying, not after. */}
                            <span className="bb-body-small bb-file-meta">
                              {row.restorable ? "can be restored" : "cannot be restored"}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ) : null}

              <div>
                <span className="bb-graph-detail-kind">
                  {viewing ? `Revision ${viewing.revision} (not current)` : "Stored content"}
                </span>
                {viewing ? (
                  <p className="bb-body-small bb-graph-note" style={{ margin: "4px 0" }}>
                    This is what the file held at revision {viewing.revision}, superseded{" "}
                    {viewing.replaced_at ? (
                      <RelativeTime
                        iso={viewing.replaced_at}
                        initial={relativeAge(new Date(viewing.replaced_at))}
                      />
                    ) : (
                      "later"
                    )}
                    . It is not what the machine is running.{" "}
                    <button
                      type="button"
                      className="bb-graph-link"
                      onClick={() => setViewing(null)}
                    >
                      Show the current content
                    </button>
                  </p>
                ) : null}
                {selected.redactions > 0 ? (
                  <p className="bb-body-small bb-graph-note" style={{ margin: "4px 0" }}>
                    {selected.redactions} value{selected.redactions === 1 ? "" : "s"} replaced
                    with <code>«redacted»</code> before this was written — by this server, or
                    by the client before it sent. Either way the original was never stored, so
                    it cannot be shown here or anywhere else.
                  </p>
                ) : null}
                {loading ? (
                  <p className="bb-body-small bb-graph-note">Loading…</p>
                ) : detailError ? (
                  <p className="bb-body-small" style={{ color: "var(--bb-status-critical)" }}>
                    Could not load the content: {detailError}
                  </p>
                ) : KIND_COPY[selected.content_kind] ? (
                  <div className="bb-file-preview-placard">
                    <span className="bb-title-medium">{selected.content_kind}</span>
                    <span className="bb-body-small">{KIND_COPY[selected.content_kind]}</span>
                  </div>
                ) : viewing ? (
                  <pre className="bb-file-extraction">{viewing.content}</pre>
                ) : selected.content ? (
                  <pre className="bb-file-extraction">{selected.content}</pre>
                ) : (
                  <p className="bb-body-small bb-graph-note">Loading the content…</p>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
