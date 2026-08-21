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
 * see BB-204 and the comment in PdfFrame. `inline_renderable` comes from the server,
 * which decides it by sniffing the bytes; SVG is excluded there because it can
 * carry script, and inline from this origin that script would run with the
 * reader's session.
 *
 * Spec 011 adds looking closely. An image gets a magnifying lens under the pointer
 * and opens into a gallery of every image in the list; a PDF gets the browser
 * viewer's own zoom, because a lens cannot read pixels out of a framed PDF (see
 * PdfFrame). Both ask the preview route for `?original=1`: the detail pane is where
 * spec 007 §7.6 says the blob itself belongs, and magnifying a 240px thumbnail
 * magnifies nothing but the thumbnail.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { Lightbox } from "@/components/files/Lightbox";
import { Magnifier } from "@/components/files/Magnifier";
import { PdfFrame } from "@/components/files/PdfFrame";
import { isGalleryImage, previewUrl } from "@/components/files/previewSource";
import type { FileRecord } from "@/lib/api/schemas";
import { bytes as formatBytes } from "@/lib/format";

/** Lens powers, relative to the image as displayed. Above the file's own
 *  resolution the lens interpolates rather than reveals, which is why the top of
 *  the range is offered but labelled — see Magnifier. */
const LENS_STEPS = [1.5, 2, 3, 4, 6];
const DEFAULT_LENS = 2;

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

function PreviewPane({
  file,
  lens,
  onLensChange,
  onOpenGallery,
}: {
  file: FileRecord;
  lens: number;
  onLensChange: (next: number) => void;
  onOpenGallery?: () => void;
}) {
  const source = previewUrl(file.file_id, { original: true });

  if (file.media_type === "application/pdf") {
    return <PdfFrame src={source} title={`Preview of ${file.filename}`} />;
  }

  // A pruned blob and a stored thumbnail are independent: the thumbnail can still
  // render after the original is gone. Only when neither is there is the pane empty,
  // and it says which of the two reasons applies rather than showing a broken frame.
  const bytesGone = file.blob_present === false && !file.has_preview;

  if (!bytesGone && (file.has_preview || file.inline_renderable)) {
    const step = LENS_STEPS.indexOf(lens);
    return (
      <div className="bb-preview-stack">
        <div className="bb-preview-toolbar">
          <span className="bb-label-medium">Magnify</span>
          <button
            type="button"
            className="bb-interactive bb-preview-step"
            onClick={() => onLensChange(LENS_STEPS[Math.max(step - 1, 0)] ?? lens)}
            disabled={step <= 0}
            aria-label="Weaker lens"
          >
            −
          </button>
          <span className="bb-body-small bb-preview-value" aria-live="polite">
            {`${lens}×`}
          </span>
          <button
            type="button"
            className="bb-interactive bb-preview-step"
            onClick={() =>
              onLensChange(LENS_STEPS[Math.min(step + 1, LENS_STEPS.length - 1)] ?? lens)
            }
            disabled={step >= LENS_STEPS.length - 1}
            aria-label="Stronger lens"
          >
            +
          </button>
        </div>

        <Magnifier
          src={source}
          alt={`Preview of ${file.filename}`}
          zoom={lens}
          onOpen={onOpenGallery}
          openLabel={`Open ${file.filename} in the gallery`}
        />

        <p className="bb-body-small bb-graph-note">
          {onOpenGallery
            ? "Hover the preview to magnify. Click it to open the gallery."
            : // No gallery for this one: it is a thumbnail attached to a file that is
              // not itself an image, and a gallery of images should hold images.
              "Hover the preview to magnify. This is the thumbnail its client supplied, not an image file."}
        </p>
      </div>
    );
  }

  return (
    <div className="bb-file-preview-placard">
      <span className="bb-title-medium">{file.media_type}</span>
      <span className="bb-body-small">
        {bytesGone
          ? "The stored bytes are gone, so there is nothing to preview."
          : "No inline preview for this type."}
      </span>
    </div>
  );
}

export function FileBrowser({ initial }: { initial: FileRecord[] }) {
  const [files] = useState<FileRecord[]>(initial);
  const [selectedId, setSelectedId] = useState<string | null>(initial[0]?.file_id ?? null);
  const [detail, setDetail] = useState<FileRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lens, setLens] = useState(DEFAULT_LENS);
  //: Index into `gallery`, not into `files`. null is closed.
  const [galleryIndex, setGalleryIndex] = useState<number | null>(null);

  // Every image in the list, so the gallery is a gallery rather than one picture
  // with arrows that do nothing.
  const gallery = useMemo(() => files.filter(isGalleryImage), [files]);

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
  const galleryPosition =
    selected === null ? -1 : gallery.findIndex((f) => f.file_id === selected.file_id);

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

            <PreviewPane
              file={selected}
              lens={lens}
              onLensChange={setLens}
              onOpenGallery={
                galleryPosition >= 0 ? () => setGalleryIndex(galleryPosition) : undefined
              }
            />

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

      {galleryIndex === null ? null : (
        <Lightbox
          items={gallery.map((file) => ({ fileId: file.file_id, filename: file.filename }))}
          index={galleryIndex}
          // Selection follows the gallery, so closing it leaves the detail pane on
          // the image the reader was actually looking at — with its extraction.
          onIndexChange={(next) => {
            const file = gallery[next];
            if (file === undefined) return;
            setGalleryIndex(next);
            setSelectedId(file.file_id);
          }}
          onClose={() => setGalleryIndex(null)}
        />
      )}
    </div>
  );
}
