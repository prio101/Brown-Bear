"use client";

/**
 * Gallery lightbox for stored images (spec 011 §11.4).
 *
 * Images only, and full-resolution: the stage asks for the file's own bytes, while
 * the filmstrip asks for thumbnails, because a strip of twelve originals would
 * download twelve originals to draw twelve 72px tiles.
 *
 * The keyboard is the interesting part. Arrows always move between images and never
 * pan — a mode where the same key does two things depending on zoom is exactly the
 * kind of hidden state that makes a viewer feel unpredictable. Panning is the mouse
 * drag, zoom is +/-/0 or a click, and Escape closes. Focus is trapped and restored,
 * because an overlay that leaves focus on the page behind it is a page a keyboard
 * reader cannot get out of.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { previewUrl } from "./previewSource";

export type GalleryItem = {
  fileId: string;
  filename: string;
};

/** Fit, then steps above it. 1 is "fit to the stage", which is not 100% of the
 *  file's own pixels — so the label says "fit", never a percentage it cannot
 *  substantiate. */
const SCALES = [1, 1.5, 2, 3, 4];

/** What a click, or the second click, toggles between. */
const FIT = 0;
const TOGGLED = 2;

/** `:not([disabled])` matters: calling focus() on a disabled button does nothing,
 *  so including one in the cycle makes Tab silently stop moving at that point. The
 *  zoom-out button is disabled whenever the image is fitted, which is every time
 *  the gallery opens. */
const FOCUSABLE = 'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

export function Lightbox({
  items,
  index,
  onIndexChange,
  onClose,
}: {
  items: GalleryItem[];
  index: number;
  onIndexChange: (next: number) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDivElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);
  const [scaleIndex, setScaleIndex] = useState(FIT);
  const [pan, setPan] = useState({ x: 0, y: 0 });

  const drag = useRef<{ x: number; y: number; from: { x: number; y: number }; moved: boolean } | null>(
    null,
  );
  // A drag that ends over the image also fires a click. Without this the pan
  // finishes by toggling the zoom it was panning.
  const dragged = useRef(false);

  const count = items.length;
  const item = items[index];

  const go = useCallback(
    (next: number) => {
      if (count === 0) return;
      // Wraps rather than disabling at the ends: a gallery that stops has to
      // explain why, and there is nothing to explain here.
      onIndexChange(((next % count) + count) % count);
    },
    [count, onIndexChange],
  );

  // A new image starts fitted. Carrying zoom and pan across would open the next
  // photo scrolled to a corner of a frame it does not share.
  useEffect(() => {
    setScaleIndex(FIT);
    setPan({ x: 0, y: 0 });
  }, [index]);

  // Keys are taken on the document, not the dialog: the reader may well be
  // clicking the stage rather than tabbing, and an overlay that only answers the
  // keyboard while a button holds focus answers it unpredictably.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Tab") {
        const nodes = dialog.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
        if (!nodes || nodes.length === 0) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (first === undefined || last === undefined) return;
        const active = document.activeElement;
        if (event.shiftKey && (active === first || !dialog.current?.contains(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
        return;
      }

      switch (event.key) {
        case "Escape":
          event.preventDefault();
          onClose();
          break;
        case "ArrowRight":
          event.preventDefault();
          go(index + 1);
          break;
        case "ArrowLeft":
          event.preventDefault();
          go(index - 1);
          break;
        case "Home":
          event.preventDefault();
          go(0);
          break;
        case "End":
          event.preventDefault();
          go(count - 1);
          break;
        case "+":
        case "=":
          event.preventDefault();
          setScaleIndex((current) => Math.min(current + 1, SCALES.length - 1));
          break;
        case "-":
          event.preventDefault();
          setScaleIndex((current) => Math.max(current - 1, FIT));
          setPan({ x: 0, y: 0 });
          break;
        case "0":
          event.preventDefault();
          setScaleIndex(FIT);
          setPan({ x: 0, y: 0 });
          break;
        default:
          break;
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [count, go, index, onClose]);

  // Focus in, focus back out. The element that opened the gallery is where a
  // keyboard reader expects to land when it closes.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    const { body } = document;
    const restore = body.style.overflow;
    // The page behind must not scroll under the overlay.
    body.style.overflow = "hidden";
    return () => {
      body.style.overflow = restore;
      opener?.focus?.();
    };
  }, []);

  // Registered once rather than per drag: mouseup outside the image still has to
  // end the drag, and a listener that only exists while dragging cannot see it.
  useEffect(() => {
    const move = (event: MouseEvent) => {
      const held = drag.current;
      if (!held) return;
      const dx = event.clientX - held.x;
      const dy = event.clientY - held.y;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) held.moved = true;
      setPan({ x: held.from.x + dx, y: held.from.y + dy });
    };
    const up = () => {
      if (drag.current?.moved) dragged.current = true;
      drag.current = null;
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, []);

  if (count === 0 || item === undefined) return null;

  const scale = SCALES[scaleIndex] ?? 1;
  const zoomed = scaleIndex !== FIT;

  return (
    <div
      className="bb-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`Image gallery: ${item.filename}`}
      ref={dialog}
      // Clicking the backdrop closes; clicking anything inside it does not.
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <header className="bb-lightbox-bar">
        <div className="bb-lightbox-title">
          <span className="bb-title-medium">{item.filename}</span>
          <span className="bb-body-small bb-lightbox-count">{`${index + 1} of ${count}`}</span>
        </div>

        <div className="bb-preview-toolbar">
          <button
            type="button"
            className="bb-interactive bb-preview-step"
            onClick={() => {
              setScaleIndex((current) => Math.max(current - 1, FIT));
              setPan({ x: 0, y: 0 });
            }}
            disabled={scaleIndex === FIT}
            aria-label="Zoom out"
          >
            −
          </button>
          <span className="bb-body-small bb-preview-value" aria-live="polite">
            {scale === 1 ? "fit" : `${scale}×`}
          </span>
          <button
            type="button"
            className="bb-interactive bb-preview-step"
            onClick={() => setScaleIndex((current) => Math.min(current + 1, SCALES.length - 1))}
            disabled={scaleIndex === SCALES.length - 1}
            aria-label="Zoom in"
          >
            +
          </button>
          <a
            className="bb-interactive bb-preview-step bb-preview-step-wide"
            href={`/ext/files/${encodeURIComponent(item.fileId)}?download=1`}
          >
            Download
          </a>
          <button
            type="button"
            className="bb-interactive bb-preview-step bb-preview-step-wide"
            onClick={onClose}
            ref={closeButton}
          >
            Close
          </button>
        </div>
      </header>

      <div className="bb-lightbox-stage">
        {count > 1 ? (
          <button
            type="button"
            className="bb-interactive bb-lightbox-arrow"
            onClick={() => go(index - 1)}
            aria-label="Previous image"
          >
            ‹
          </button>
        ) : null}

        {/* eslint-disable-next-line @next/next/no-img-element -- a blob route, not a static asset */}
        <img
          key={item.fileId}
          src={previewUrl(item.fileId, { original: true })}
          alt={item.filename}
          className="bb-lightbox-img"
          data-testid="lightbox-image"
          draggable={false}
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
            cursor: zoomed ? "grab" : "zoom-in",
          }}
          onMouseDown={(event) => {
            if (!zoomed) return;
            event.preventDefault();
            drag.current = { x: event.clientX, y: event.clientY, from: pan, moved: false };
          }}
          onClick={() => {
            if (dragged.current) {
              dragged.current = false;
              return;
            }
            setScaleIndex((current) => (current === FIT ? TOGGLED : FIT));
            setPan({ x: 0, y: 0 });
          }}
        />

        {count > 1 ? (
          <button
            type="button"
            className="bb-interactive bb-lightbox-arrow"
            onClick={() => go(index + 1)}
            aria-label="Next image"
          >
            ›
          </button>
        ) : null}
      </div>

      {count > 1 ? (
        <div className="bb-lightbox-strip" aria-label="Gallery filmstrip">
          {items.map((entry, position) => (
            <button
              key={entry.fileId}
              type="button"
              className="bb-interactive bb-lightbox-thumb"
              aria-current={position === index ? "true" : undefined}
              data-active={position === index ? "true" : undefined}
              onClick={() => go(position)}
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- a blob route, not a static asset */}
              <img src={previewUrl(entry.fileId)} alt={entry.filename} draggable={false} />
            </button>
          ))}
        </div>
      ) : null}

      <p className="bb-body-small bb-lightbox-hint">
        Click the image to zoom, drag to pan. Arrow keys move between images, + and −
        zoom, 0 fits, Escape closes.
      </p>
    </div>
  );
}
