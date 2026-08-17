import { AutoRefresh } from "@/components/AutoRefresh";
import { BarChart } from "@/components/charts/BarChart";
import { ChartFrame, ChartTable } from "@/components/charts/ChartFrame";
import { LineChart } from "@/components/charts/LineChart";
import { compact, formatDay, type Series } from "@/components/charts/geometry";
import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { PeriodFilter, PERIODS, type Period } from "@/components/PeriodFilter";
import { StatTile } from "@/components/StatTile";
import { SavingsCard } from "@/components/SavingsCard";
import { Text } from "@/components/Text";
import {
  getAggregation,
  getTokenHistory,
  getSavings,
  getTokenSummary,
  getTokensByModel,
  getTokensBySource,
} from "@/lib/api/endpoints";
import { all, toPanelState } from "@/lib/api/panel";
import { provenanceOf, weakestProvenance, type Provenance } from "@/lib/api/provenance";
import { count, money } from "@/lib/format";

/**
 * Token analytics (BB-106).
 *
 * Tokens and cost are on SEPARATE charts. They have different scales, and one
 * chart with two y-axes is the single most misleading thing this page could do.
 */

type SeriesRow = { period: string; tokens: number; cost: number; requests: number };

/**
 * Group history rows into a time series.
 *
 * The endpoint returns one row per (period, model, source), so plotting rows
 * directly would put several points on the same instant.
 */
function toSeries(
  rows: readonly {
    period_start: string;
    total_tokens: number;
    cost: number;
    request_count: number;
  }[],
): SeriesRow[] {
  const byPeriod = new Map<string, SeriesRow>();
  for (const row of rows) {
    const existing = byPeriod.get(row.period_start) ?? {
      period: row.period_start,
      tokens: 0,
      cost: 0,
      requests: 0,
    };
    existing.tokens += row.total_tokens;
    existing.cost += row.cost;
    existing.requests += row.request_count;
    byPeriod.set(row.period_start, existing);
  }
  return [...byPeriod.values()].sort((a, b) => a.period.localeCompare(b.period));
}

export default async function Tokens({
  searchParams,
}: {
  searchParams: Promise<{ period?: string }>;
}) {
  const requested = (await searchParams).period;
  const period: Period = PERIODS.some((one) => one.value === requested)
    ? (requested as Period)
    : "daily";

  const [summary, history, byModel, bySource, aggregation, savings] = await all([
    getTokenSummary(period),
    getTokenHistory(period),
    getTokensByModel(period),
    getTokensBySource(period),
    getAggregation(),
    getSavings(30),
  ]);

  const rows = history.ok ? toSeries(history.data.results) : [];
  const labels = rows.map((row) => formatDay(row.period));

  const tokenSeries: Series[] = [
    {
      name: "Total tokens",
      colorVar: "--bb-series-1",
      points: rows.map((row) => ({ x: row.period, y: row.tokens })),
    },
  ];
  // Slot 2, not slot 1 again: colour follows the entity. Cost is a different
  // entity from tokens and gets its own chart precisely so no second axis appears.
  const costSeries: Series[] = [
    {
      name: "Cost",
      colorVar: "--bb-series-2",
      points: rows.map((row) => ({ x: row.period, y: row.cost })),
    },
  ];

  const presentSources = bySource.ok
    ? bySource.data.results.map((row) => provenanceOf(row.source))
    : [];
  const totalsProvenance: Provenance = weakestProvenance(presentSources);

  const aggregationState = toPanelState(
    aggregation,
    (data) => data.recent_runs.length === 0,
    "No aggregation runs recorded yet.",
  );

  // The server's render time is the honest answer to "how old is this":
  // after router.refresh() it moves on its own, and it does not move when a
  // refresh fails (BB-203).
  const renderedAt = new Date().toISOString();

  return (
    <div className="bb-shell">
      <Nav current="/tokens" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-4)" }}>
          <Text role="headline-medium" as="h1">
            Tokens
          </Text>
          <AutoRefresh renderedAt={renderedAt} />
        </header>

        {/* One filter row, above the charts, never interleaved. */}
        <PeriodFilter current={period} basePath="/tokens" />

        {summary.ok ? (
          <div
            style={{
              display: "grid",
              gap: "var(--bb-space-4)",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              margin: "var(--bb-space-6) 0 var(--bb-space-8)",
            }}
          >
            <StatTile
              label="Tokens in"
              value={count(summary.data.tokens_in)}
              provenance={totalsProvenance}
              fetchedAt={summary.fetchedAt}
            />
            <StatTile
              label="Tokens out"
              value={count(summary.data.tokens_out)}
              provenance={totalsProvenance}
              fetchedAt={summary.fetchedAt}
            />
            <StatTile
              label="Total"
              value={count(summary.data.total_tokens)}
              provenance={totalsProvenance}
              fetchedAt={summary.fetchedAt}
            />
            <StatTile
              label="Cost"
              value={money(summary.data.cost, summary.data.currency)}
              provenance="derived"
              fetchedAt={summary.fetchedAt}
              note="From a price table, not a bill."
            />
            <StatTile
              label="Requests"
              value={count(summary.data.request_count)}
              provenance={totalsProvenance}
              fetchedAt={summary.fetchedAt}
            />
          </div>
        ) : null}

        <div style={{ display: "grid", gap: "var(--bb-space-6)" }}>
          <ChartFrame
            title="Tokens over time"
            subtitle={`Grouped by ${period} period.`}
            truncated={history.ok ? history.data.truncated : false}
            table={
              <ChartTable
                caption="Tokens per period"
                columns={[
                  { label: "Period", render: (row: SeriesRow) => formatDay(row.period) },
                  { label: "Tokens", numeric: true, render: (row) => count(row.tokens) },
                  { label: "Requests", numeric: true, render: (row) => count(row.requests) },
                ]}
                rows={rows}
              />
            }
          >
            <LineChart
              series={tokenSeries}
              labels={labels}
              ariaLabel={`Total tokens per ${period} period`}
              area
            />
          </ChartFrame>

          {/* A SEPARATE chart, deliberately. Tokens and cost on one plot with two
              y-scales is the most misleading option available here. */}
          <ChartFrame
            title="Cost over time"
            subtitle="Separate chart on purpose — never a second axis on the token chart."
            truncated={history.ok ? history.data.truncated : false}
            table={
              <ChartTable
                caption="Cost per period"
                columns={[
                  { label: "Period", render: (row: SeriesRow) => formatDay(row.period) },
                  { label: "Cost", numeric: true, render: (row) => money(row.cost) },
                ]}
                rows={rows}
              />
            }
          >
            <LineChart
              series={costSeries}
              labels={labels}
              ariaLabel={`Cost per ${period} period`}
              valueFormat="money"
              area
            />
          </ChartFrame>

          <div
            style={{
              display: "grid",
              gap: "var(--bb-space-6)",
              gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
            }}
          >
            <ChartFrame
              title="By model"
              subtitle="Sorted by total tokens."
              table={
                <ChartTable
                  caption="Tokens by model"
                  columns={[
                    { label: "Model", render: (row: { label: string; value: number }) => row.label },
                    { label: "Tokens", numeric: true, render: (row) => count(row.value) },
                  ]}
                  rows={
                    byModel.ok
                      ? [...byModel.data.results]
                          .sort((a, b) => b.total_tokens - a.total_tokens)
                          .map((row) => ({ label: row.model, value: row.total_tokens }))
                      : []
                  }
                />
              }
            >
              <BarChart
                ariaLabel="Total tokens by model"
                seriesName="Tokens"
                bars={
                  byModel.ok
                    ? [...byModel.data.results]
                        .sort((a, b) => b.total_tokens - a.total_tokens)
                        .map((row) => ({ label: row.model, value: row.total_tokens }))
                    : []
                }
              />
            </ChartFrame>

            <ChartFrame
              title="By source"
              subtitle="local_ollama is measured here; remote_api is reported by a client."
              table={
                <ChartTable
                  caption="Tokens by source, with trust kind"
                  columns={[
                    {
                      label: "Source",
                      render: (row: { label: string; value: number }) => row.label,
                    },
                    {
                      label: "Trust",
                      render: (row) => provenanceOf(row.label),
                    },
                    { label: "Tokens", numeric: true, render: (row) => count(row.value) },
                  ]}
                  rows={
                    bySource.ok
                      ? [...bySource.data.results]
                          .sort((a, b) => b.total_tokens - a.total_tokens)
                          .map((row) => ({ label: row.source, value: row.total_tokens }))
                      : []
                  }
                />
              }
            >
              <BarChart
                ariaLabel="Total tokens by source"
                seriesName="Tokens"
                colorVar="--bb-series-3"
                bars={
                  bySource.ok
                    ? [...bySource.data.results]
                        .sort((a, b) => b.total_tokens - a.total_tokens)
                        .map((row) => ({ label: row.source, value: row.total_tokens }))
                    : []
                }
              />
            </ChartFrame>
          </div>

          {/* Placed above Aggregation and below the cost charts on purpose: it is
              the counterweight to them. The charts show what was spent; this shows
              what the shared memory contributed, and whether that actually
              displaced a provider call or merely grounded one. */}
          <Panel title="Served by the memory">
            <PanelBody state={toPanelState(savings, () => false, "")}>
              {(data) => <SavingsCard savings={data} />}
            </PanelBody>
          </Panel>

          <Panel title="Aggregation">
            <PanelBody state={aggregationState}>
              {(data) => (
                <div style={{ display: "grid", gap: "var(--bb-space-3)" }}>
                  <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                    Read-only: triggering a run is denied at the edge.
                  </Text>
                  <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--bb-space-1)" }}>
                    {Object.entries(data.latest_completed).map(([grain, when]) => (
                      <li
                        key={grain}
                        style={{ display: "flex", justifyContent: "space-between", gap: "var(--bb-space-3)" }}
                      >
                        <Text role="body-medium">{grain}</Text>
                        <Text role="body-small" tabular style={{ color: "var(--bb-on-surface-variant)" }}>
                          {when ? new Date(when).toLocaleString("en-US") : "never"}
                        </Text>
                      </li>
                    ))}
                  </ul>
                  <Text role="label-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                    {compact(data.recent_runs.length)} recent runs recorded.
                  </Text>
                </div>
              )}
            </PanelBody>
          </Panel>
        </div>
      </main>
    </div>
  );
}
