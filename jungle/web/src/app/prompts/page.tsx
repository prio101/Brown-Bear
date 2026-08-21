import { AutoRefresh } from "@/components/AutoRefresh";
import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { PromptPalace } from "@/components/PromptPalace";
import { ProvenanceBadge } from "@/components/ProvenanceBadge";
import { StatTile } from "@/components/StatTile";
import { Text } from "@/components/Text";
import { getPrompts } from "@/lib/api/endpoints";
import { toPanelState } from "@/lib/api/panel";
import { count } from "@/lib/format";

/**
 * Prompt Palace (spec 012).
 *
 * What has been asked of this memory, from whichever machine, with the answer and
 * what each prompt sits near. The list is fetched server-side like every other
 * page; the answers and the similarity lookups are not — they are fetched per
 * prompt on selection, because a page of forty model responses plus eighty vector
 * queries is not a page load.
 *
 * Auto-refreshing because the interesting case is a prompt arriving from somewhere
 * else. The refresh badge is what keeps a quiet page from reading as a dead one —
 * without it, "no new prompts" and "the gateway stopped answering" look identical.
 */

export const dynamic = "force-dynamic";

export default async function PromptsPage() {
  const fetchedAt = new Date();
  const prompts = await getPrompts({ limit: 100 });

  const state = toPanelState(
    prompts,
    (data) => data.prompts.length === 0,
    "No prompts stored yet. A machine reports one with POST /ext/exchange when a turn finishes.",
  );

  return (
    <div className="bb-shell">
      <Nav current="/prompts" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-6)" }}>
          <Text role="headline-medium" as="h1">
            Prompt Palace
          </Text>
          <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
            Every prompt this memory has been told about, with the answer and what it
            sits near — prior prompts that could have answered it, and stored passages
            a retrieval lookup would have injected. Brown Bear never sees the model
            call: a client reports the finished exchange, so the prompt, the answer and
            the machine name are all claims it made and none of them can be verified
            here.
          </Text>
          <ProvenanceBadge kind="reported" fetchedAt={fetchedAt} />
        </header>

        {prompts.ok ? (
          <div className="bb-tile-row" style={{ marginBottom: "var(--bb-space-4)" }}>
            <StatTile
              label="Stored"
              value={count(prompts.data.total)}
              provenance="reported"
              fetchedAt={fetchedAt}
              note="exchanges in the collection"
            />
            <StatTile
              label="Scanned"
              value={count(prompts.data.scanned)}
              provenance="reported"
              fetchedAt={fetchedAt}
              // Chroma returns documents in no order, so this is not a detail: a
              // capped scan means the newest prompt may not be on the page.
              note={
                prompts.data.truncated
                  ? "read for this page — capped, so the newest may be missing"
                  : "read for this page — the whole collection"
              }
            />
            <StatTile
              label="Machines"
              value={count(prompts.data.machines.length)}
              provenance="reported"
              fetchedAt={fetchedAt}
              note={
                prompts.data.machines.length > 0
                  ? prompts.data.machines.join(", ")
                  : "no client has reported one yet"
              }
            />
            <StatTile
              label="Cache cutoff"
              value={String(prompts.data.threshold)}
              // The one local fact on the page: the cutoff is this stack's own
              // setting, not something a client reported.
              provenance="measured"
              fetchedAt={fetchedAt}
              note={prompts.data.scorable ? "cosine, so scores are comparable" : "not cosine — scores unavailable"}
            />
          </div>
        ) : null}

        {prompts.ok && prompts.data.truncated ? (
          <p className="bb-body-small bb-graph-note" style={{ marginBottom: "var(--bb-space-4)" }}>
            {`This page read ${prompts.data.scanned} of ${prompts.data.total} stored exchanges. Chroma
            returns documents in no particular order, so "newest first" is newest within
            what was read — the most recent prompt may not be listed.`}
          </p>
        ) : null}

        <Panel title="Prompts">
          <PanelBody state={state}>
            {(data) => (
              <PromptPalace
                initial={data.prompts}
                threshold={data.threshold}
                scorable={data.scorable}
              />
            )}
          </PanelBody>
        </Panel>

        <AutoRefresh renderedAt={fetchedAt.toISOString()} />
      </main>
    </div>
  );
}
