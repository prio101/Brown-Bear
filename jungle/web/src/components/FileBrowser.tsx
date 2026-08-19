"use client";

/**
 * File browser (spec 007 §7.6).
 *
 * Three panes: what the file is, what it looks like, and — the point of the page —
 * what the memory actually read out of it. Nothing else in the stack can answer
 * that last question, and without it a bad extraction is invisible: you would see
 * poor retrieval and have no way to tell whether the scan was unreadable or the
 * embedding was at fault.
 *
 * Preview is the browser's job. Images go in an <img>, PDFs in an <iframe> the
 * browser's own viewer fills — both rendered natively, so this ships no PDF library
 * and the runtime image needs no rendering dependency. That frame is not sandboxed;
 * see BB-204 and the comment on it below. `inline_renderable` comes from the server,
 * which decides it by sniffing the bytes; SVG is excluded there because it can
 * carry script, and inline from this origin that script would run with the
 * reader's session.
 */

import { useCallback, useEffect, useState } from "react";

import type { FileRecord } from "@/lib/api/schemas";
import { bytes as formatBytes } from "@/lib/format";

const STATUS_COPY: Record<string, { label: string; glyph: string; detail: string }> = {
  indexed: { label: "Indexed", glyph: "●", detail: "extracted text is in the corpus" },
  stored: { label: "Stored only", glyph: "○", detail: "no extraction — downloadable, not searchable" },
  failed: { label: "Failed", glyph: "✕", detail: "extraction arrived but indexing failed" },
  missing: { label: "Bytes missing", glyph: "⚠", detail: "the row is here and the blob is not" },
};

function StatusChip({ status }: { status: string }) {
  const copy = STATUS_COPY[status] ?? { label: status, glyph: "?", detail: "" };
  return (
    <span className="bb-label-medium" title={copy.detail}>
      {/* Glyph plus word, never colour alone. */}
      <span aria-hidden="true">{copy.glyph}</span> {copy.label}
    </span>
  );
}

function Preview({ file }: { file: FileRecord }) {
  const source = `/ext/files/${encodeURIComponent(file.file_id)}/preview`;

  if (file.media_type === "application/pdf") {
    return (
      <iframe
        // Deliberately NOT sandboxed (BB-204). This frame carried `sandbox=""`, and
        // Chrome answers a sandboxed PDF frame with its subframe error page rather
        // than the document — measured across every token combination, including
        // `allow-scripts allow-same-origin`, so there is no set that both sandboxes
        // and renders. The isolation that mattered is still there and is the
        // browser's own: a PDF's JavaScript runs in the viewer's engine, which has
        // no DOM, no cookies and no reach into this page. The response carries
        // `default-src 'none'; object-src 'none'`, `nosniff` and a byte-sniffed
        // allowlist, so this route can never hand back HTML.
        src={source}
        title={`Preview of ${file.filename}`}
        className="bb-file-preview-frame"
      />
    );
  }
  if (file.has_preview || file.inline_renderable) {
    // eslint-disable-next-line @next/next/no-img-element -- a blob route, not a static asset
    return <img src={source} alt={`Preview of ${file.filename}`} className="bb-file-preview-img" />;
  }
  return (
    <div className="bb-file-preview-placard">
      <span className="bb-title-medium">{file.media_type}</span>
      <span className="bb-body-small">No inline preview for this type.</span>
    </div>
  );
}

export function FileBrowser({ initial }: { initial: FileRecord[] }) {
  const [files] = useState<FileRecord[]>(initial);
  const [selectedId, setSelectedId] = useState<string | null>(initial[0]?.file_id ?? null);
  const [detail, setDetail] = useState<FileRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (fileId: string) => {
    setLoading(true);
    setError(null);
    try {
      // Fetched on selection rather than shipped with the list: the extracted text
      // of a whole corpus would be megabytes of payload nobody scrolls through.
      const response = await fetch(`/ext/files/${encodeURIComponent(fileId)}`, {
        headers: { accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`the gateway returned ${response.status}`);
      setDetail((await response.json()) as FileRecord);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) void load(selectedId);
  }, [selectedId, load]);

  const selected = detail ?? files.find((f) => f.file_id === selectedId) ?? null;

  if (files.length === 0) {
    return (
      <p className="bb-body-medium bb-graph-note">
        No files yet. A machine sends one with <code>POST /ext/files</code>, carrying the
        bytes and the text it extracted from them — extraction happens where the file
        is, not here.
      </p>
    );
  }

  return (
    <div className="bb-file-layout">
      <ul className="bb-file-list" aria-label="Stored files">
        {files.map((file) => {
          const active = file.file_id === selectedId;
          return (
            <li key={file.file_id}>
              <button
                type="button"
                className="bb-interactive bb-file-row"
                aria-current={active ? "true" : undefined}
                data-active={active ? "true" : undefined}
                onClick={() => setSelectedId(file.file_id)}
              >
                <span className="bb-body-medium bb-file-name">{file.filename}</span>
                <span className="bb-body-small bb-file-meta">
                  {file.media_type} · {formatBytes(file.size_bytes)} · {file.chunk_count} chunks
                </span>
                <StatusChip status={file.blob_present === false ? "missing" : file.status} />
              </button>
            </li>
          );
        })}
      </ul>

      <section className="bb-file-detail" aria-label="File detail">
        {selected === null ? (
          <p className="bb-body-medium bb-graph-note">Select a file.</p>
        ) : (
          <>
            <header>
              <h2 className="bb-title-medium" style={{ margin: 0, overflowWrap: "anywhere" }}>
                {selected.filename}
              </h2>
              <p className="bb-body-small bb-graph-note" style={{ margin: "4px 0 0" }}>
                {selected.project} · {selected.media_type} · {formatBytes(selected.size_bytes)}
              </p>
            </header>

            <Preview file={selected} />

            <dl className="bb-graph-dl">
              {[
                ["status", STATUS_COPY[selected.status]?.label ?? selected.status],
                // Recorded, never verified — the reader has to be able to see what
                // produced the text they are judging.
                ["extracted by", selected.extractor ?? "not recorded"],
                ["reported from", selected.extracted_by ?? "not recorded"],
                ["chunks", String(selected.chunk_count)],
                ["extracted characters", String(selected.extracted_chars)],
                ["tags", selected.tags.length ? selected.tags.join(", ") : "none"],
                ["sha256", selected.sha256.slice(0, 24) + "…"],
              ].map(([term, value]) => (
                <div className="bb-graph-field" key={term}>
                  <dt className="bb-body-small">{term}</dt>
                  <dd className="bb-body-small">{value}</dd>
                </div>
              ))}
            </dl>

            {selected.error ? (
              <p className="bb-body-small" style={{ color: "#ff6b8a" }}>
                {selected.error}
              </p>
            ) : null}

            <div>
              <a
                className="bb-graph-link"
                href={`/ext/files/${encodeURIComponent(selected.file_id)}?download=1`}
              >
                Download original
              </a>
            </div>

            <div>
              <span className="bb-graph-detail-kind">Extracted text</span>
              {loading ? (
                <p className="bb-body-small bb-graph-note">Loading…</p>
              ) : error ? (
                <p className="bb-body-small" style={{ color: "#ff6b8a" }}>
                  Could not load the extraction: {error}
                </p>
              ) : selected.extracted_text ? (
                <pre className="bb-file-extraction">{selected.extracted_text}</pre>
              ) : selected.extracted_chars > 0 ? (
                // Not yet fetched, rather than absent. The list omits extracted
                // text, so saying "nothing was extracted" here would call an
                // indexed file empty until the detail request lands.
                <p className="bb-body-small bb-graph-note">Loading the extraction…</p>
              ) : (
                <p className="bb-body-small bb-graph-note">
                  Nothing was extracted from this file, so nothing about it is
                  searchable. The bytes are still stored and downloadable.
                </p>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
