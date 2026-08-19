import { AutoRefresh } from "@/components/AutoRefresh";
import { LivenessBanner, type LivenessState } from "@/components/LivenessBanner";
import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { ProvenanceBadge } from "@/components/ProvenanceBadge";
import { StatTile } from "@/components/StatTile";
import { StatusChip } from "@/components/StatusChip";
import { Text } from "@/components/Text";
import {
  getCache,
  getExtHealth,
  getHealth,
  getSystem,
  getTokenSummary,
  getTokensBySource,
} from "@/lib/api/endpoints";
import { staleness } from "@/lib/api/freshness";
import { reportingHealth } from "@/lib/api/reporting";
import { all, toPanelState } from "@/lib/api/panel";
import { provenanceOf, weakestProvenance } from "@/lib/api/provenance";
import { bytes, count, money, percent, rate } from "@/lib/format";

/**
 * Overview (BB-105).
 *
 * The page's job is not to show numbers — it is to make "everything is fine" and
 * "you have been silently disconnected for two days" impossible to confuse. The
 * banner does that work; the tiles are the easy part.
 */

/** Host snapshots are collected every 30s (BB_SNAPSHOT_INTERVAL_SECONDS). */
const SNAPSHOT_INTERVAL_MS = 30_000;

const listReset = { listStyle: "none", margin: 0, padding: 0 } as const;
const row = { display: "flex", justifyContent: "space-between", gap: "var(--bb-space-3)" } as const;

export default async function Overview() {
  // Concurrent: six sequential server-side calls would make the page as slow as
  // their sum, and every result is independent.
  const [health, system, cache, summary, bySource, gateway] = await all([
    getHealth(),
    getSystem(60),
    getCache(60),
    getTokenSummary("daily"),
    getTokensBySource("daily"),
    getExtHealth(),
  ]);

  /* --- liveness ----------------------------------------------------------
   * Derived from the collector's own freshness, not from whether the page
   * rendered. A page full of zeroes renders perfectly well when the collector
   * has been dead since Tuesday, which is the failure this resolves. */
  let liveness: LivenessState = "healthy";
  let lastWorked: Date | null = null;
  let affected = "";
  let nextStep = "";

  if (!system.ok) {
    liveness = "unreachable";
    affected = "Host metrics, and every number derived from them.";
    nextStep = "Check that brownbear-app is running.";
  } else if (system.data.current === null || system.data.samples === 0) {
    liveness = "unknown";
    affected = "Host metrics have never been collected on this instance.";
    nextStep = "The collector runs every 30s — give it a minute, then reload.";
  } else {
    lastWorked = new Date(system.data.current.timestamp);
    const grade = staleness(lastWorked, SNAPSHOT_INTERVAL_MS);
    if (grade !== "fresh") {
      liveness = grade === "stale" ? "stale" : "unreachable";
      affected = "Every number on this page is as old as the last snapshot.";
      nextStep = "Check the scheduler inside brownbear-app.";
    }
  }

  /* --- is usage still being reported? (BB-205) ---------------------------
   * A second, independent signal. The collector above measures this host and was
   * fresh throughout the incident that produced this code; what had stopped was
   * arriving from another machine, and nothing on the page said so. */
  const reporting = summary.ok
    ? reportingHealth(summary.data)
    : null;

  /* --- provenance of the token totals ------------------------------------
   * A total that adds a remote client's claim to a locally measured count is only
   * as good as the claim, so compute the weakest kind from the sources actually
   * present rather than assuming one. */
  const presentSources = bySource.ok
    ? bySource.data.results.map((result) => provenanceOf(result.source))
    : [];
  const totalsProvenance = weakestProvenance(presentSources);
  const mixesTrust = new Set(presentSources).size > 1;

  const healthState = toPanelState(
    health,
    (data) => Object.keys(data.services).length === 0,
    "No services are configured.",
  );
  const gatewayState = toPanelState(gateway, () => false, "");
  const cacheState = toPanelState(
    cache,
    (data) => data.samples === 0 || data.current === null,
    "No cache samples have been collected yet.",
  );
  const systemState = toPanelState(system, (data) => data.current === null, "No host snapshots yet.");

  // The server's render time is the honest answer to "how old is this":
  // after router.refresh() it moves on its own, and it does not move when a
  // refresh fails (BB-203).
  const renderedAt = new Date().toISOString();

  return (
    <div className="bb-shell">
      <Nav current="/" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-6)" }}>
          <Text role="headline-medium" as="h1">
            Overview
          </Text>
          <AutoRefresh renderedAt={renderedAt} />
        </header>

        <LivenessBanner
          state={liveness}
          affected={affected}
          lastWorked={lastWorked}
          nextStep={nextStep}
        />

        {/* Separate banner, not a merged one: the collector and the reporting
            clients fail independently, and a reader has to know which. */}
        {reporting ? (
          <LivenessBanner
            state={reporting.state}
            affected={reporting.affected}
            lastWorked={reporting.lastWorked}
            nextStep={reporting.nextStep}
          />
        ) : null}

        <div
          style={{
            display: "grid",
            gap: "var(--bb-space-4)",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            marginBottom: "var(--bb-space-8)",
          }}
        >
          {summary.ok ? (
            <>
              <StatTile
                label="Tokens today"
                value={count(summary.data.total_tokens)}
                provenance={totalsProvenance}
                fetchedAt={summary.fetchedAt}
                // The age of the last report goes on the number itself, not only
                // in the banner: a zero has to be readable where it is read.
                note={[
                  reporting?.note,
                  mixesTrust ? "Mixes locally measured counts with remote client reports." : null,
                ]
                  .filter(Boolean)
                  .join(" ")}
              />
              <StatTile
                label="Cost today"
                value={money(summary.data.cost, summary.data.currency)}
                // Always derived: computed from a price table, never measured.
                provenance="derived"
                fetchedAt={summary.fetchedAt}
              />
              <StatTile
                label="Requests today"
                value={count(summary.data.request_count)}
                provenance={totalsProvenance}
                fetchedAt={summary.fetchedAt}
              />
            </>
          ) : null}
          {cache.ok && cache.data.current ? (
            <StatTile
              label="Cache hit rate"
              // null renders "no samples", never 0%: absence of evidence is not
              // evidence of failure.
              value={rate(cache.data.current.lifetime_hit_rate)}
              provenance="measured"
              // The SAMPLE's timestamp, not the request's. /api/cache serves
              // stored samples from Postgres, so it answers happily while Redis
              // is down — badging it "just now" because we asked just now would
              // present an hour-old number as current, which is the exact failure
              // this page exists to prevent.
              fetchedAt={new Date(cache.data.current.timestamp)}
              note="Lifetime, from Redis counters."
            />
          ) : null}
        </div>

        <div
          style={{
            display: "grid",
            gap: "var(--bb-space-6)",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          }}
        >
          <Panel title="Services">
            <PanelBody state={healthState}>
              {(data) => (
                <ul style={{ ...listReset, display: "grid", gap: "var(--bb-space-3)" }}>
                  {Object.entries(data.services).map(([name, service]) => (
                    <li key={name} style={row}>
                      <Text role="body-medium">{name}</Text>
                      <StatusChip
                        role={service.healthy ? "good" : "critical"}
                        label={service.healthy ? "Healthy" : "Down"}
                        detail={
                          service.healthy
                            ? service.latency_ms != null
                              ? `${service.latency_ms.toFixed(0)} ms`
                              : undefined
                            : (service.error ?? "no detail given")
                        }
                      />
                    </li>
                  ))}
                </ul>
              )}
            </PanelBody>
          </Panel>

          <Panel title="Context gateway">
            <PanelBody state={gatewayState}>
              {(data) => (
                <div style={{ display: "grid", gap: "var(--bb-space-3)" }}>
                  <StatusChip
                    role={data.ready ? "good" : "warning"}
                    label={data.ready ? "Ready" : "Not ready"}
                    detail={data.ready ? undefined : "Collections or embedding model missing."}
                  />
                  {/* Built as one string: a JSX line break before "d" renders as
                      "30 d", which reads as a typo. */}
                  <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                    {`${data.embedding_model} · threshold ${data.threshold} · top-k ${data.top_k} · TTL ${data.ttl_days}d`}
                  </Text>
                  <ul style={{ ...listReset, display: "grid", gap: "var(--bb-space-2)" }}>
                    {Object.entries(data.collections).map(([name, collection]) => (
                      <li key={name} style={row}>
                        <Text role="body-medium">{name}</Text>
                        {/* Only cosine distances are comparable to the threshold.
                            Any other space makes every score from it meaningless,
                            so it is flagged rather than rendered as fine. */}
                        {collection.space === "cosine" ? (
                          <Text role="label-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
                            cosine
                          </Text>
                        ) : (
                          <StatusChip
                            role="serious"
                            label={collection.space}
                            detail="scores cannot be compared to the threshold"
                          />
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </PanelBody>
          </Panel>

          <Panel title="Host">
            <PanelBody state={systemState}>
              {(data) =>
                data.current ? (
                  <ul style={{ ...listReset, display: "grid", gap: "var(--bb-space-2)" }}>
                    <li style={row}>
                      <Text role="body-medium">CPU</Text>
                      <Text role="body-medium" tabular>
                        {percent(data.current.cpu_percent)}
                      </Text>
                    </li>
                    <li style={row}>
                      <Text role="body-medium">Memory</Text>
                      <Text role="body-medium" tabular>
                        {percent(data.current.memory_percent)} of{" "}
                        {bytes(data.current.memory_total_bytes)}
                      </Text>
                    </li>
                    <li style={row}>
                      <Text role="body-medium">Disk</Text>
                      <Text role="body-medium" tabular>
                        {percent(data.current.disk_percent)} of {bytes(data.current.disk_total_bytes)}
                      </Text>
                    </li>
                    <li style={{ marginTop: "var(--bb-space-2)" }}>
                      <ProvenanceBadge kind="measured" fetchedAt={new Date(data.current.timestamp)} />
                    </li>
                  </ul>
                ) : null
              }
            </PanelBody>
          </Panel>

          <Panel title="Redis cache">
            <PanelBody state={cacheState}>
              {(data) =>
                data.current ? (
                  <ul style={{ ...listReset, display: "grid", gap: "var(--bb-space-2)" }}>
                    <li style={row}>
                      <Text role="body-medium">Keys</Text>
                      <Text role="body-medium" tabular>
                        {count(data.current.total_keys)}
                      </Text>
                    </li>
                    <li style={row}>
                      <Text role="body-medium">Memory</Text>
                      <Text role="body-medium" tabular>
                        {bytes(data.current.used_memory_bytes)}
                      </Text>
                    </li>
                    <li style={row}>
                      <Text role="body-medium">Clients</Text>
                      <Text role="body-medium" tabular>
                        {count(data.current.connected_clients)}
                      </Text>
                    </li>
                    {/* Sampled, not live. Without the sample's own age this panel
                        keeps showing figures from before Redis died. */}
                    <li style={{ marginTop: "var(--bb-space-2)" }}>
                      <ProvenanceBadge kind="measured" fetchedAt={new Date(data.current.timestamp)} />
                    </li>
                  </ul>
                ) : null
              }
            </PanelBody>
          </Panel>
        </div>
      </main>
    </div>
  );
}
