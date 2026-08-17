import { LogStream } from "@/components/LogStream";
import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { Text } from "@/components/Text";
import { getRecentLogs } from "@/lib/api/endpoints";
import { toPanelState } from "@/lib/api/panel";

/**
 * Live logs (BB-301).
 *
 * The counterpart to the memory graph, split along the shape of the data. Memory
 * is a few dozen richly connected documents and belongs in a graph; logs are tens
 * of thousands of flat, ordered rows and belong in a stream.
 *
 * The first page of rows is fetched server-side so the page renders with content
 * rather than an empty box waiting on a connection. The client then opens the
 * stream with backlog=0 and appends — asking for the backlog twice would show
 * every recent row a second time.
 */

export default async function LogsPage() {
  const recent = await getRecentLogs(80);

  const state = toPanelState(
    recent,
    // Not an error and not an empty state to apologise for: a quiet stack has
    // nothing to log, and the stream will fill in the moment it does.
    () => false,
    "",
  );

  return (
    <div className="bb-shell">
      <Nav current="/logs" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-6)" }}>
          <Text role="headline-medium" as="h1">
            Logs
          </Text>
          <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
            Collection queries and token usage as they happen. Streamed rather than
            graphed: these outnumber stored memories by roughly a thousand to one,
            and as nodes they would bury the graph.
          </Text>
        </header>

        <Panel title="Live stream">
          <PanelBody state={state}>{(data) => <LogStream initial={data.rows} />}</PanelBody>
        </Panel>
      </main>
    </div>
  );
}
