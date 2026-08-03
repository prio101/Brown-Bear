import type { ReactNode } from "react";

import { Text } from "../Text";

import type { Series } from "./geometry";

/**
 * Chart chrome: title, legend, truncation note, and the table twin (BB-106).
 *
 * Two rules are enforced structurally rather than by review:
 *
 *   - **The legend is present for two or more series and absent for one** (the
 *     title already names a single series), so identity is never colour-alone.
 *   - **The table twin always exists**, in a real `<details>` with a visible
 *     summary — not visually hidden with no affordance. No value in this
 *     dashboard is reachable only by hover.
 */

export function Legend({ series }: { series: readonly Series[] }) {
  // One series needs no legend box: the chart title names it.
  if (series.length < 2) return null;

  return (
    <ul
      style={{
        listStyle: "none",
        margin: 0,
        padding: 0,
        display: "flex",
        flexWrap: "wrap",
        gap: "var(--bb-space-4)",
      }}
    >
      {series.map((one) => (
        <li
          key={one.name}
          className="bb-label-medium"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "var(--bb-space-2)",
            // Text wears ink, never the series colour. The swatch carries identity.
            color: "var(--bb-ink-2)",
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: "12px",
              height: "12px",
              borderRadius: "var(--bb-radius-xs)",
              background: `var(${one.colorVar})`,
            }}
          />
          {one.name}
        </li>
      ))}
    </ul>
  );
}

export type TableColumn<Row> = {
  label: string;
  numeric?: boolean;
  render: (row: Row) => ReactNode;
};

export function ChartTable<Row>({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: readonly TableColumn<Row>[];
  rows: readonly Row[];
}) {
  return (
    <details>
      <summary className="bb-label-large bb-chart-summary">Table view</summary>
      <div className="bb-scroll-x">
        <table className="bb-table">
          <caption className="bb-visually-hidden">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.label}
                  scope="col"
                  className={column.numeric ? "bb-tabular bb-num" : undefined}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map((column) => (
                  <td
                    key={column.label}
                    className={column.numeric ? "bb-tabular bb-num" : undefined}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function ChartFrame({
  title,
  subtitle,
  series,
  truncated,
  children,
  table,
}: {
  title: string;
  subtitle?: string;
  series?: readonly Series[];
  /** When the backend capped the series. Saying nothing here makes the chart lie. */
  truncated?: boolean;
  children: ReactNode;
  table: ReactNode;
}) {
  return (
    <figure className="bb-chart-figure">
      <figcaption style={{ display: "grid", gap: "var(--bb-space-1)" }}>
        <Text role="title-medium" as="h3">
          {title}
        </Text>
        {subtitle ? (
          <Text role="body-small" style={{ color: "var(--bb-ink-2)" }}>
            {subtitle}
          </Text>
        ) : null}
      </figcaption>

      {series ? <Legend series={series} /> : null}

      {truncated ? (
        <p
          className="bb-label-medium"
          style={{ color: "var(--bb-status-warning)", margin: 0 }}
        >
          <span aria-hidden="true">! </span>
          Series capped by the backend — this is not the whole range.
        </p>
      ) : null}

      {children}
      {table}
    </figure>
  );
}
