"use client";

/**
 * PDF preview with zoom (spec 011 §11.3).
 *
 * The PDF renders in the browser's own viewer, and that viewer does the zooming —
 * driven by the `#zoom=` fragment, which Chrome's viewer and Firefox's pdf.js both
 * honour. Text stays crisp because the viewer re-lays-out at the new scale instead
 * of a scaled-up bitmap of the old one.
 *
 * There is deliberately no hover lens here, and it is not an omission. A lens needs
 * two things this page cannot get from a framed PDF: its pixels, and its scroll
 * position. The viewer is a separate document rendered by the browser, and script
 * on this page can read neither — so a lens would keep showing the top of page 1
 * while the reader scrolled, magnifying the wrong region and saying nothing about
 * it. Rendering the pages ourselves (pdf.js to a canvas) would make a real lens
 * possible; spec 011 records that as an open question with its cost, rather than
 * quietly adding a megabyte of PDF rendering to the bundle.
 */

import { useState } from "react";

/** Percentages the viewers agree on. */
const STEPS = [50, 75, 100, 125, 150, 200, 300, 400];

/** Where "fit" steps to on the first press. */
const FROM_FIT = STEPS.indexOf(100);

export function PdfFrame({ src, title }: { src: string; title: string }) {
  // null is the viewer's own default — fit to width in every viewer that matters.
  // Not the same as 100%, so it is a state rather than a step.
  const [step, setStep] = useState<number | null>(null);

  const percent = step === null ? null : STEPS[step] ?? null;
  // The fragment must follow the query string, not precede it.
  const url = percent === null ? src : `${src}#zoom=${percent}`;

  return (
    <div className="bb-preview-stack">
      <div className="bb-preview-toolbar">
        <span className="bb-label-medium">Zoom</span>
        <button
          type="button"
          className="bb-interactive bb-preview-step"
          onClick={() => setStep((current) => Math.max((current ?? FROM_FIT) - 1, 0))}
          disabled={step === 0}
          aria-label="Zoom out"
        >
          −
        </button>
        <span className="bb-body-small bb-preview-value" aria-live="polite">
          {percent === null ? "fit" : `${percent}%`}
        </span>
        <button
          type="button"
          className="bb-interactive bb-preview-step"
          onClick={() =>
            setStep((current) => Math.min((current ?? FROM_FIT) + 1, STEPS.length - 1))
          }
          disabled={step === STEPS.length - 1}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className="bb-interactive bb-preview-step bb-preview-step-wide"
          onClick={() => setStep(null)}
          disabled={step === null}
        >
          Fit
        </button>
      </div>

      <iframe
        // Remounted per zoom on purpose: changing only the fragment of an iframe's
        // src does not re-run the viewer, so the key forces a fresh load. The cost
        // is that the viewer starts again at the top, which the note below states.
        key={url}
        // Deliberately NOT sandboxed (BB-204). This frame carried `sandbox=""`, and
        // Chrome answers a sandboxed PDF frame with its subframe error page rather
        // than the document — measured across every token combination, including
        // `allow-scripts allow-same-origin`, so there is no set that both sandboxes
        // and renders. The isolation that mattered is still there and is the
        // browser's own: a PDF's JavaScript runs in the viewer's engine, which has
        // no DOM, no cookies and no reach into this page. The response carries
        // `default-src 'none'; object-src 'none'`, `nosniff` and a byte-sniffed
        // allowlist, so this route can never hand back HTML.
        src={url}
        title={title}
        className="bb-file-preview-frame"
      />

      <p className="bb-body-small bb-graph-note">
        The browser&apos;s own viewer does this zoom, so the text stays sharp and the
        page reloads at the new scale — returning to the top. There is no hover lens
        for a PDF: this page cannot read pixels, or a scroll position, out of the
        viewer, so a lens would magnify a region the reader had already scrolled past.
      </p>
    </div>
  );
}
