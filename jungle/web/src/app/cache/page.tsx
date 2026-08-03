import { ChartFrame, ChartTable } from "@/components/charts/ChartFrame";
import { formatClock, type Series } from "@/components/charts/geometry";
import { LineChart } from "@/components/charts/LineChart";
import { Nav } from "@/components/Nav";
import { Panel, PanelBody, PanelEmpty, PanelError } from "@/components/Panel";
import { StatTile } from "@/components/StatTile";
import { Text } from "@/components/Text";
import { WindowFilter, WINDOWS, type WindowMinutes } from "@/components/WindowFilter";
import { getCache } from "@/lib/api/endpoints";
import { bytes, count, rate } from "@/lib/format";

/**
 * Redis cache behaviour (BB-107).
 *
 * The whole ticket is honest null handling. `hit_rate: null` means "no samples",
 * and coercing it to 0% turns "we have no idea" into "the cache is failing",
 * which is a worse lie than showing nothing.
 */

export default async function CachePage({
  searchParams,
}: {
  searchParams: Promise<{ minutes?: string }>;
}) {
  const requested = Number((await searchParams).minutes);
  const minutes: WindowMinutes = WINDOWS.some((one) => one.value === requested)
    ? (requested as WindowMinutes)
    : 60;

  const cache = await getCache(minutes);

  const series = cache.ok ? cache.data.series : [];
  const labels = series.map((sample) => formatClock(sample.timestamp));

  // hit_rate is nullable and stays nullable all the way into the chart, where a
  // null breaks the line rather than being plotted as zero.
  const hitRateSeries: Series[] = [
    {
      name: "Hit rate",
      colorVar: "--bb-series-1",
      points: series.map((sample) => ({
        x: sample.timestamp,
        y: sample.hit_rate === null ? null : sample.hit_rate * 100,
      })),
    },
  ];

  const hitsMissesSeries: Series[] = [
    {
      name: "Hits",
      colorVar: "--bb-series-1",
      points: series.map((sample) => ({ x: sample.timestamp, y: sample.hits })),
    },
    {
      name: "Misses",
      colorVar: "--bb-series-2",
      points: series.map((sample) => ({ x: sample.timestamp, y: sample.misses })),
    },
  ];

  const cold = cache.ok && (cache.data.samples === 0 || cache.data.current === null);

  return (
    <div className="bb-shell">
      <Nav current="/cache" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-4)" }}>
          <Text role="headline-medium" as="h1">
            Cache
          </Text>
        </header>

        <WindowFilter current={minutes} basePath="/cache" />

        {!cache.ok ? (
          <div style={{ marginTop: "var(--bb-space-6)" }}>
            <Panel title="Cache">
              <PanelError error={cache.error} />
            </Panel>
          </div>
        ) : cold ? (
          <div style={{ marginTop: "var(--bb-space-6)" }}>
            <Panel title="Cache">
              {/* Cold start is EMPTY, not an error: samples 0 with current null is a
                  valid response, and the two states must not look alike. */}
              <PanelEmpty
                reason="No cache samples have been collected in this window yet. Redis counters are read every 30s."
                fetchedAt={cache.fetchedAt}
              />
            </Panel>
          </div>
        ) : (
          <>
            <div
              style={{
                display: "grid",
                gap: "var(--bb-space-4)",
                gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                margin: "var(--bb-space-6) 0 var(--bb-space-8)",
              }}
            >
              <StatTile
                label="Lifetime hit rate"
                value={rate(cache.data.current!.lifetime_hit_rate)}
                provenance="measured"
                // The sample's own timestamp: /api/cache serves stored samples, so
                // it answers while Redis is down and the request time would present
                // an old number as current.
                fetchedAt={new Date(cache.data.current!.timestamp)}
              />
              <StatTile
                label="Keys"
                value={count(cache.data.current!.total_keys)}
                provenance="measured"
                fetchedAt={new Date(cache.data.current!.timestamp)}
              />
              <StatTile
                label="Memory used"
                value={bytes(cache.data.current!.used_memory_bytes)}
                provenance="measured"
                fetchedAt={new Date(cache.data.current!.timestamp)}
              />
              <StatTile
                label="Connected clients"
                value={count(cache.data.current!.connected_clients)}
                provenance="measured"
                fetchedAt={new Date(cache.data.current!.timestamp)}
              />
            </div>

            <div style={{ display: "grid", gap: "var(--bb-space-6)" }}>
              <ChartFrame
                title="Hit rate over time"
                subtitle="The line breaks where a sample had no requests to rate — a gap, never a zero."
                table={
                  <ChartTable
                    caption="Hit rate per sample"
                    columns={[
                      {
                        label: "Time",
                        render: (row: (typeof series)[number]) => formatClock(row.timestamp),
                      },
                      { label: "Hit rate", numeric: true, render: (row) => rate(row.hit_rate) },
                      { label: "Hits", numeric: true, render: (row) => count(row.hits) },
                      { label: "Misses", numeric: true, render: (row) => count(row.misses) },
                    ]}
                    rows={series}
                  />
                }
              >
                <LineChart
                  series={hitRateSeries}
                  labels={labels}
                  ariaLabel="Cache hit rate over the selected window"
                  area
                />
              </ChartFrame>

              <ChartFrame
                title="Hits and misses"
                series={hitsMissesSeries}
                table={
                  <ChartTable
                    caption="Hits and misses per sample"
                    columns={[
                      {
                        label: "Time",
                        render: (row: (typeof series)[number]) => formatClock(row.timestamp),
                      },
                      { label: "Hits", numeric: true, render: (row) => count(row.hits) },
                      { label: "Misses", numeric: true, render: (row) => count(row.misses) },
                    ]}
                    rows={series}
                  />
                }
              >
                <LineChart
                  series={hitsMissesSeries}
                  labels={labels}
                  ariaLabel="Cache hits and misses over the selected window"
                />
              </ChartFrame>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
