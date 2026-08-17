import { MemoryGraph } from "@/components/graph/MemoryGraph";
import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { Text } from "@/components/Text";
import { getGraph } from "@/lib/api/endpoints";
import { toPanelState } from "@/lib/api/panel";

/**
 * Stored memory as a graph (BB-301).
 *
 * The other pages answer "how much" — counts, rates, cost over time. This answers
 * "what is in there, and what is it connected to", which is the question a shared
 * memory has to be able to answer about itself.
 *
 * The overview is fetched server-side like every other page, so no credential
 * reaches client JS. Expansion is different: clicking a node fetches
 * /api/graph/node from the browser, same-origin through the edge, which resends
 * the credentials the reader already signed in with. That keeps the interactive
 * path inside the same authentication boundary as everything else.
 *
 * Logs are deliberately not here. They outnumber stored memories by roughly a
 * thousand to one, so as nodes they would bury the thing being looked at — they
 * stream on /logs instead.
 */

export default async function GraphPage() {
  const graph = await getGraph();

  const state = toPanelState(
    graph,
    (data) => data.nodes.length === 0,
    "Nothing is stored yet. The graph fills in as exchanges are reported to /ext/exchange and documents are ingested through /ext/documents.",
  );

  return (
    <div className="bb-shell">
      <Nav current="/graph" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-6)" }}>
          <Text role="headline-medium" as="h1">
            Memory graph
          </Text>
          <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
            Every stored memory and what it connects to. Solid lines are recorded
            facts — this exchange belongs to that project. Dashed lines are computed
            similarity, and appear when you expand a node.
          </Text>
        </header>

        <Panel title="Stored memory">
          <PanelBody state={state}>
            {(data) => (
              <MemoryGraph
                initial={{ nodes: data.nodes, edges: data.edges, truncated: data.truncated }}
              />
            )}
          </PanelBody>
        </Panel>
      </main>
    </div>
  );
}
