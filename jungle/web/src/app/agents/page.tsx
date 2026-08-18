import { AgentConfigBrowser } from "@/components/AgentConfigBrowser";
import { LivenessBanner, type LivenessState } from "@/components/LivenessBanner";
import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { Text } from "@/components/Text";
import { getAgentConfigs, getAgentInventory } from "@/lib/api/endpoints";
import { all, toPanelState } from "@/lib/api/panel";
import { bytes, count } from "@/lib/format";

/**
 * Agent configuration (spec 008).
 *
 * What each connected machine is actually running, addressed the way the
 * requirement states it: machine → Global or project → tool → file.
 *
 * The page is read-only on purpose. A sync is something a machine does to itself;
 * a button here that pushed configuration *to* a machine would be a remote write
 * path, which is exactly what the edge is built not to publish.
 */

export const dynamic = "force-dynamic";

export default async function AgentsPage() {
  const [inventory] = await all([getAgentInventory()]);

  // The first branch, fetched server-side so the page is useful on first paint
  // rather than after a round trip the reader watches.
  const first = inventory.ok ? inventory.data.machines[0] : null;
  const firstScope = first?.scopes[0] ?? null;
  const firstTool = firstScope?.tools[0] ?? null;
  const selection =
    first && firstScope && firstTool
      ? {
          machine: first.machine,
          scope: firstScope.scope,
          project: firstScope.project,
          tool: firstTool.tool,
        }
      : null;

  const branch = selection
    ? await getAgentConfigs({
        machine: selection.machine,
        scope: selection.scope,
        project: selection.project || undefined,
        tool: selection.tool,
        limit: 500,
      })
    : null;

  const state = toPanelState(
    inventory,
    (data) => data.machines.length === 0,
    "No machine has synced its configuration yet. This is empty, not broken — a sync is always an explicit client action.",
  );

  // Staleness is judged against the backend's own threshold, so the page and the
  // app cannot disagree about what "stale" means. A machine that has never synced
  // does not appear at all, so `unknown` is not a state this page can be in.
  const staleHours = inventory.ok ? inventory.data.stale_after_hours : 24;
  const oldest =
    inventory.ok && inventory.data.machines.length > 0
      ? inventory.data.machines
          .map((machine) => machine.last_synced_at)
          .filter((value): value is string => value !== null)
          .sort()[0]
      : undefined;
  const staleSince = oldest ? new Date(oldest) : null;
  const liveness: LivenessState =
    staleSince && Date.now() - staleSince.getTime() > staleHours * 3_600_000
      ? "stale"
      : "healthy";

  return (
    <div className="bb-shell">
      <Nav current="/agents" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-6)" }}>
          <Text role="headline-medium" as="h1">
            Agent configuration
          </Text>
          <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
            What each machine is running, by machine, then its global or per-project
            scope, then the tool. A machine reports its own configuration and nothing
            here can verify it, so every file is marked as reported and carries the age
            of its sync.
          </Text>
          <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
            Values that look like credentials are masked before a row is written — by
            this stack, and by the client before it sends. The count beside each file is
            of the stored text, so it covers both. Files whose only content is a
            credential are refused outright and never stored.
          </Text>
          {inventory.ok ? (
            <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
              {`${count(inventory.data.totals.machines)} machines · ${count(
                inventory.data.totals.files,
              )} files · ${bytes(inventory.data.totals.bytes)} · ${count(
                inventory.data.totals.redactions,
              )} values masked`}
            </Text>
          ) : null}
        </header>

        <LivenessBanner
          state={liveness}
          affected="At least one machine has not synced its configuration recently, so what is shown for it may not be what it is running."
          lastWorked={staleSince}
          nextStep={`Run bb_sync.py on that machine. Anything older than ${staleHours}h counts as stale here.`}
        />

        <Panel title="Configuration files">
          <PanelBody state={state}>
            {(data) => (
              <AgentConfigBrowser
                inventory={data}
                initial={branch?.ok ? branch.data.files : []}
                initialSelection={selection}
              />
            )}
          </PanelBody>
        </Panel>
      </main>
    </div>
  );
}
