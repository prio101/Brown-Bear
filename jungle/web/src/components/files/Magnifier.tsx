"use client";

/**
 * Magnifying glass over a previewed image (spec 011 §11.2).
 *
 * A lens that follows the pointer, drawn as a second copy of the same image
 * scaled up behind a round window. The image is the browser's own decode, so this
 * ships no imaging code and downloads nothing twice — the lens references the same
 * URL the <img> already has.
 *
 * Two things this gets right that a naive lens does not:
 *
 * 1. The element box must be the drawn image, not a box the image is letterboxed
 *    inside. With `object-fit: contain` the pixels sit somewhere in the middle of a
 *    wider element, and a lens mapped onto the element shows a region offset from
 *    the cursor — subtly, and worse the further the aspect ratios diverge. The
 *    stylesheet sizes the image to its own pixels for exactly this reason.
 * 2. Past a file's own resolution the lens interpolates. It keeps magnifying and
 *    stops revealing, which on a scan is the difference between "the text is
 *    unreadable" and "the text is unreadable at this zoom". The badge says which
 *    side of 1:1 the reader is on rather than leaving them to guess.
 */

import { useCallback, useRef, useState } from "react";

/** Lens diameter. On the 4px grid, and large enough to hold a word of scanned text. */
const LENS = 176;

/** Rounding slack when comparing the lens against 1:1 — a hair over is not "past". */
const EPSILON = 0.05;

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max);

type Size = { w: number; h: number };

export function Magnifier({
  src,
  alt,
  zoom,
  onOpen,
  openLabel,
}: {
  src: string;
  alt: string;
  /** Lens power, relative to the image as displayed. */
  zoom: number;
  /** Click handler. Given one, the frame becomes a button and opens the gallery. */
  onOpen?: () => void;
  openLabel?: string;
}) {
  const frame = useRef<HTMLDivElement | HTMLButtonElement | null>(null);
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const [box, setBox] = useState<Size | null>(null);
  const [natural, setNatural] = useState<Size | null>(null);

  const track = useCallback((clientX: number, clientY: number) => {
    const element = frame.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    // An unmeasurable box cannot be mapped onto the image; showing a lens anyway
    // would put it in the corner and magnify the wrong thing.
    if (!rect.width || !rect.height) return;
    setBox({ w: rect.width, h: rect.height });
    setAt({
      x: clamp(clientX - rect.left, 0, rect.width),
      y: clamp(clientY - rect.top, 0, rect.height),
    });
  }, []);

  const handlers = {
    onMouseMove: (event: React.MouseEvent) => track(event.clientX, event.clientY),
    onMouseLeave: () => setAt(null),
  };

  // Relative to the image as displayed, so it is comparable with `zoom`.
  const oneToOne = natural && box && box.w > 0 ? natural.w / box.w : null;
  const interpolating = oneToOne !== null && zoom > oneToOne + EPSILON;

  let lens = null;
  if (at && box) {
    const spread: Size = { w: box.w * zoom, h: box.h * zoom };
    // Clamped so the lens never shows blank space past the edge of the image: the
    // window still tracks the cursor, the magnified content just stops sliding.
    const offsetX = clamp(at.x * zoom - LENS / 2, 0, Math.max(0, spread.w - LENS));
    const offsetY = clamp(at.y * zoom - LENS / 2, 0, Math.max(0, spread.h - LENS));
    lens = (
      <span
        className="bb-zoom-lens"
        data-testid="zoom-lens"
        // Decorative: it magnifies pixels a screen reader cannot use, and the
        // image beside it already carries the alt text.
        aria-hidden="true"
        style={{
          width: LENS,
          height: LENS,
          left: at.x - LENS / 2,
          top: at.y - LENS / 2,
          backgroundImage: `url("${src}")`,
          backgroundSize: `${spread.w}px ${spread.h}px`,
          backgroundPosition: `-${offsetX}px -${offsetY}px`,
        }}
      >
        <span className="bb-zoom-badge bb-label-medium">
          {`${zoom}×`}
          {interpolating ? " · past 1:1" : ""}
        </span>
      </span>
    );
  }

  const image = (
    // eslint-disable-next-line @next/next/no-img-element -- a blob route, not a static asset
    <img
      src={src}
      alt={alt}
      className="bb-zoom-img"
      draggable={false}
      onLoad={(event) => {
        const target = event.currentTarget;
        // 0 while the decode is pending, and in a DOM with no image loader at all.
        // Left null in that case, which reads as "1:1 unknown" rather than as
        // "already past it".
        if (target.naturalWidth > 0) {
          setNatural({ w: target.naturalWidth, h: target.naturalHeight });
        }
      }}
    />
  );

  if (onOpen) {
    return (
      <button
        type="button"
        ref={frame as React.Ref<HTMLButtonElement>}
        className="bb-zoom-frame"
        aria-label={openLabel ?? alt}
        onClick={onOpen}
        {...handlers}
      >
        {image}
        {lens}
      </button>
    );
  }

  return (
    <div ref={frame as React.Ref<HTMLDivElement>} className="bb-zoom-frame" {...handlers}>
      {image}
      {lens}
    </div>
  );
}
