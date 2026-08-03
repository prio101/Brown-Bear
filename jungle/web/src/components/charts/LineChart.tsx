"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { money } from "@/lib/format";

import {
  axisFormatter,
  compact,
  labelIndices,
  niceTicks,
  segments,
  type Series,
} from "./geometry";

/**
 * Formatters are named, not passed.
 *
 * A function cannot cross the server/client boundary — React refuses to
 * serialise it — so the server names the format it wants and this component
 * resolves it. Adding a format means adding a case here, which is the point:
 * the set stays small and reviewable.
 */
export type ValueFormat = "compact" | "money";

const FORMATTERS: Record<ValueFormat, (value: number | null) => string> = {
  compact,
  money: (value) => (value === null ? "no data" : money(value)),
};

/**
 * Line / area chart (BB-106 §106.1).
 *
 * Hand-rolled inline SVG, ported from charts.js. No charting library: every
 * mainstream option defaults to behaviour this project prohibits — cycled
 * palettes, dual axes, tweened values, no table twin — and fighting those
 * defaults costs more than the SVG.
 *
 * Mark specs are fixed here rather than per call site: 2px stroke with round
 * joins, end marker r=4.5 with a 2px surface ring so it stays legible where
 * series cross, area fill a 10% wash and only for a single series, hairline
 * horizontal gridlines, recessive axis.
 */

const PAD = { top: 14, right: 18, bottom: 30, left: 54 } as const;

export type LineChartProps = {
  series: readonly Series[];
  /** One label per x position. First, middle and last are drawn. */
  labels: readonly string[];
  ariaLabel: string;
  height?: number;
  /** Area wash under the line. Ignored unless there is exactly one series. */
  area?: boolean;
  valueFormat?: ValueFormat;
};

export function LineChart({
  series,
  labels,
  ariaLabel,
  height = 240,
  area = false,
  valueFormat = "compact",
}: LineChartProps) {
  const format = FORMATTERS[valueFormat];
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [active, setActive] = useState(-1);

  // Measured rather than a viewBox scale, so label text stays at its token size
  // instead of scaling with the plot.
  useEffect(() => {
    const node = wrapRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(260, entry.contentRect.width));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const drawn = series.filter((one) => one.points.length > 0);
  const count = Math.max(0, ...drawn.map((one) => one.points.length));

  const values = drawn.flatMap((one) =>
    one.points.map((point) => point.y).filter((y): y is number => y !== null),
  );
  const rawMax = values.length ? Math.max(...values, 0) : 0;
  const ticks = niceTicks(0, rawMax === 0 ? 1 : rawMax);
  const top = Math.max(...ticks);
  const tickFormat = axisFormatter(top);

  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const xAt = (index: number) =>
    PAD.left + (count === 1 ? plotW / 2 : (plotW * index) / (count - 1));
  const yAt = (value: number) => PAD.top + plotH - (value / (top || 1)) * plotH;

  const onMove = useCallback(
    (event: React.MouseEvent<SVGRectElement>) => {
      const box = event.currentTarget.getBoundingClientRect();
      const ratio = (event.clientX - box.left) / (box.width || 1);
      setActive(Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1)))));
    },
    [count],
  );

  const onKey = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        setActive((current) => {
          const next = current < 0 ? 0 : current + (event.key === "ArrowRight" ? 1 : -1);
          return Math.max(0, Math.min(count - 1, next));
        });
      } else if (event.key === "Escape") {
        setActive(-1);
      }
    },
    [count],
  );

  if (!drawn.length || count === 0) {
    // Inside the plot frame, not a blank box: an empty chart still has to say so.
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

  return (
    <div
      ref={wrapRef}
      className="bb-chart-plot"
      tabIndex={0}
      onKeyDown={onKey}
      onBlur={() => setActive(-1)}
      style={{ position: "relative" }}
    >
      <svg width={width} height={height} role="img" aria-label={ariaLabel}>
        {/* Gridlines: hairline, solid, recessive. Horizontal only. */}
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={yAt(tick)}
              y2={yAt(tick)}
              stroke="var(--bb-gridline)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={yAt(tick) + 4}
              textAnchor="end"
              fill="var(--bb-ink-muted)"
              className="bb-label-small bb-tabular"
            >
              {tickFormat(tick)}
            </text>
          </g>
        ))}

        <line
          x1={PAD.left}
          x2={width - PAD.right}
          y1={PAD.top + plotH}
          y2={PAD.top + plotH}
          stroke="var(--bb-axis)"
          strokeWidth={1}
        />

        {labelIndices(count).map((index) =>
          labels[index] ? (
            <text
              key={index}
              x={xAt(index)}
              y={height - 10}
              textAnchor={index === 0 ? "start" : index === count - 1 ? "end" : "middle"}
              fill="var(--bb-ink-muted)"
              className="bb-label-small"
            >
              {labels[index]}
            </text>
          ) : null,
        )}

        {drawn.map((one) => {
          const runs = segments(one.points);
          const single = drawn.length === 1;
          return (
            <g key={one.name}>
              {runs.map((run, runIndex) => {
                const path = run
                  .map((p, i) => `${i ? "L" : "M"}${xAt(p.index)},${yAt(p.y)}`)
                  .join(" ");
                return (
                  <g key={runIndex}>
                    {area && single && run.length > 1 ? (
                      // A 10% wash, never a saturated block.
                      <path
                        d={`${path} L${xAt(run[run.length - 1]!.index)},${yAt(0)} L${xAt(run[0]!.index)},${yAt(0)} Z`}
                        fill={`var(${one.colorVar})`}
                        fillOpacity={0.1}
                        stroke="none"
                      />
                    ) : null}
                    <path
                      d={path}
                      fill="none"
                      stroke={`var(${one.colorVar})`}
                      strokeWidth={2}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                    />
                    {/* A lone surviving point between two gaps would otherwise be
                        invisible: a path of one point draws nothing. */}
                    {run.length === 1 ? (
                      <circle
                        cx={xAt(run[0]!.index)}
                        cy={yAt(run[0]!.y)}
                        r={3}
                        fill={`var(${one.colorVar})`}
                      />
                    ) : null}
                  </g>
                );
              })}
              {(() => {
                const last = [...one.points].reverse().find((point) => point.y !== null);
                const lastIndex = one.points.findLastIndex((point) => point.y !== null);
                if (!last || last.y === null || lastIndex < 0) return null;
                return (
                  <circle
                    cx={xAt(lastIndex)}
                    cy={yAt(last.y)}
                    r={4.5}
                    fill={`var(${one.colorVar})`}
                    stroke="var(--bb-chart-surface)"
                    strokeWidth={2}
                  />
                );
              })()}
            </g>
          );
        })}

        {/* Crosshair and focus dots for the active column. */}
        {active >= 0 ? (
          <g>
            <line
              x1={xAt(active)}
              x2={xAt(active)}
              y1={PAD.top}
              y2={PAD.top + plotH}
              stroke="var(--bb-axis)"
              strokeWidth={1}
            />
            {drawn.map((one) => {
              const point = one.points[active];
              if (!point || point.y === null) return null;
              return (
                <circle
                  key={one.name}
                  cx={xAt(active)}
                  cy={yAt(point.y)}
                  r={4.5}
                  fill={`var(${one.colorVar})`}
                  stroke="var(--bb-chart-surface)"
                  strokeWidth={2}
                />
              );
            })}
          </g>
        ) : null}

        {/* The hit target is the whole plot, never the mark. */}
        <rect
          x={PAD.left}
          y={PAD.top}
          width={Math.max(0, plotW)}
          height={Math.max(0, plotH)}
          fill="transparent"
          style={{ cursor: "crosshair" }}
          onMouseMove={onMove}
          onMouseLeave={() => setActive(-1)}
        />
      </svg>

      {active >= 0 ? (
        <div className="bb-tooltip" style={{ left: `${xAt(active) + 14}px`, top: `${PAD.top}px` }}>
          <p className="bb-label-medium bb-tooltip-title">{labels[active] ?? ""}</p>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {drawn.map((one) => {
              const point = one.points[active];
              return (
                <li key={one.name} className="bb-tooltip-row">
                  <span className="bb-body-small" style={{ display: "inline-flex", gap: "var(--bb-space-2)", alignItems: "center" }}>
                    <span
                      aria-hidden="true"
                      className="bb-tooltip-key"
                      style={{ background: `var(${one.colorVar})` }}
                    />
                    {one.name}
                  </span>
                  <span className="bb-body-small bb-tabular">
                    {/* A gap says so, rather than reading as zero. */}
                    {point && point.y !== null ? format(point.y) : "no data"}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      <span className="bb-visually-hidden">
        Use arrow keys to step through data points, Escape to dismiss. A table view follows.
      </span>
    </div>
  );
}
