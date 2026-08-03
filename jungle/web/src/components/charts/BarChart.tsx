"use client";

import { useEffect, useRef, useState } from "react";

import { money } from "@/lib/format";

import { compact } from "./geometry";

/** Named formatters: a function cannot cross the server/client boundary. */
export type BarFormat = "compact" | "money";

const FORMATTERS: Record<BarFormat, (value: number) => string> = {
  compact,
  money: (value) => money(value),
};

/**
 * Horizontal bar chart (BB-106 §106.1), ported from charts.js.
 *
 * One series, one colour. A value ramp across nominal categories would
 * double-encode length as hue, and length is already the encoding.
 *
 * Sorted by value at the call site, not here: sorting is a statement about the
 * data and belongs where the data is chosen.
 */

const ROW_HEIGHT = 30;
const BAR_MAX = 24;
const PAD = { top: 6, right: 64, bottom: 6 } as const;

export type Bar = { label: string; value: number };

export function BarChart({
  bars,
  ariaLabel,
  colorVar = "--bb-series-1",
  seriesName = "Value",
  valueFormat = "compact",
}: {
  bars: readonly Bar[];
  ariaLabel: string;
  colorVar?: string;
  seriesName?: string;
  valueFormat?: BarFormat;
}) {
  const format = FORMATTERS[valueFormat];
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(260, entry.contentRect.width));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const height = PAD.top + PAD.bottom + Math.max(bars.length, 1) * ROW_HEIGHT;

  if (!bars.length) {
    return (
      <div className="bb-chart-plot" style={{ height }}>
        <svg width="100%" height={height} role="img" aria-label={`${ariaLabel} — no data`}>
          <text
            x="50%"
            y="50%"
            textAnchor="middle"
            fill="var(--bb-ink-muted)"
            className="bb-body-medium"
          >
            No data yet
          </text>
        </svg>
      </div>
    );
  }

  const max = Math.max(...bars.map((bar) => bar.value), 1);
  const labelW = Math.min(160, Math.max(80, Math.round(width * 0.28)));
  const trackX = labelW + 12;
  const trackW = Math.max(20, width - trackX - PAD.right);
  const barH = Math.min(BAR_MAX, ROW_HEIGHT - 10);

  return (
    <div ref={wrapRef} className="bb-chart-plot" style={{ position: "relative" }}>
      <svg width={width} height={height} role="img" aria-label={ariaLabel}>
        {bars.map((bar, index) => {
          const y = PAD.top + index * ROW_HEIGHT;
          const barY = y + (ROW_HEIGHT - barH) / 2;
          const barW = Math.max(2, (bar.value / max) * trackW);
          // 4px rounded data-end, square at the baseline — the rounded end marks
          // where the value stops, so rounding both ends would make it ambiguous.
          const r = Math.min(4, barW);

          return (
            <g key={bar.label}>
              <text
                x={labelW}
                y={y + ROW_HEIGHT / 2 + 4}
                textAnchor="end"
                fill="var(--bb-ink-2)"
                className="bb-body-small"
              >
                {bar.label}
              </text>

              <path
                d={
                  `M${trackX},${barY} H${trackX + barW - r} ` +
                  `A${r},${r} 0 0 1 ${trackX + barW},${barY + r} ` +
                  `V${barY + barH - r} A${r},${r} 0 0 1 ${trackX + barW - r},${barY + barH} ` +
                  `H${trackX} Z`
                }
                fill={`var(${colorVar})`}
              />

              {/* The value sits at the tip in an ink token, never the series colour. */}
              <text
                x={trackX + barW + 8}
                y={barY + barH / 2 + 4}
                fill="var(--bb-ink-2)"
                className="bb-body-small bb-tabular"
              >
                {format(bar.value)}
              </text>

              {/* Hit target spans the whole row, well past the mark. */}
              <rect
                x={0}
                y={y}
                width={width}
                height={ROW_HEIGHT}
                fill="transparent"
                onMouseEnter={() => setActive(index)}
                onMouseLeave={() => setActive(-1)}
              />
            </g>
          );
        })}
      </svg>

      {active >= 0 && bars[active] ? (
        <div
          className="bb-tooltip"
          style={{ left: `${trackX}px`, top: `${PAD.top + active * ROW_HEIGHT}px` }}
        >
          <p className="bb-label-medium bb-tooltip-title">{bars[active]!.label}</p>
          <div className="bb-tooltip-row">
            <span
              className="bb-body-small"
              style={{ display: "inline-flex", gap: "var(--bb-space-2)", alignItems: "center" }}
            >
              <span
                aria-hidden="true"
                className="bb-tooltip-key"
                style={{ background: `var(${colorVar})` }}
              />
              {seriesName}
            </span>
            <span className="bb-body-small bb-tabular">{format(bars[active]!.value)}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
