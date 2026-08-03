import { Nav } from "@/components/Nav";
import { Panel, PanelBody } from "@/components/Panel";
import { StatusChip } from "@/components/StatusChip";
import { Text } from "@/components/Text";
import { getCollections, getExtHealth } from "@/lib/api/endpoints";
import { all, toPanelState } from "@/lib/api/panel";
import { count } from "@/lib/format";

/**
 * The corpus retrieval and the semantic cache depend on (BB-107).
 *
 * Retrieval quality is bounded by what is in these collections, so their state is
 * a fact the reader needs — not an empty state to decorate. Two things get
 * flagged loudly because both silently invalidate every score:
 *
 *   - a non-cosine distance space: Chroma defaults to l2, whose distances are
 *     unbounded and cannot be compared to the 0.95 threshold at all
 *   - an embedding model that no longer matches the live one: every vector in the
 *     collection was built with the old one
 */

/** What each collection is FOR. The two must never read as interchangeable. */
const ROLE_COPY: Record<string, string> = {
  cache: "Serves cache hits — these are prior answers.",
  retrieval: "Serves retrieval context — supporting material, never an answer.",
};

export default async function CollectionsPage() {
  const [collections, gateway] = await all([getCollections(), getExtHealth()]);

  const spaces = gateway.ok ? gateway.data.collections : {};
  const liveModel = gateway.ok ? gateway.data.embedding_model : null;

  const state = toPanelState(
    collections,
    (data) => data.collections.length === 0,
    "ChromaDB has no collections. Retrieval and the semantic cache both return nothing until one exists.",
  );

  return (
    <div className="bb-shell">
      <Nav current="/collections" />
      <main className="bb-page">
        <header style={{ marginBottom: "var(--bb-space-6)" }}>
          <Text role="headline-medium" as="h1">
            Collections
          </Text>
          {gateway.ok ? (
            <Text role="body-medium" style={{ color: "var(--bb-on-surface-variant)" }}>
              {`Live embedding model ${gateway.data.embedding_model} · cache threshold ${gateway.data.threshold} · top-k ${gateway.data.top_k} · TTL ${gateway.data.ttl_days}d`}
            </Text>
          ) : null}
        </header>

        <Panel title="ChromaDB">
          <PanelBody state={state}>
            {(data) => (
              <div style={{ display: "grid", gap: "var(--bb-space-4)" }}>
                <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                  {`${count(data.collection_count)} collections · ${count(data.document_count)} documents · API ${data.api_version}`}
                </Text>

                <div
                  style={{
                    display: "grid",
                    gap: "var(--bb-space-4)",
                    gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
                  }}
                >
                  {data.collections.map((collection) => {
                    const space = spaces[collection.name]?.space ?? null;
                    const role = collection.metadata?.role ?? null;
                    const model = collection.metadata?.embedding_model ?? null;

                    const unscoreable = space !== null && space !== "cosine";
                    const unknownSpace = space === null;
                    const modelMismatch =
                      model !== null && liveModel !== null && model !== liveModel;
                    const empty = collection.count === 0;

                    return (
                      <article
                        key={collection.id}
                        style={{
                          border: "1px solid var(--bb-outline-variant)",
                          borderRadius: "var(--bb-radius-md)",
                          padding: "var(--bb-space-4)",
                          display: "grid",
                          gap: "var(--bb-space-2)",
                        }}
                      >
                        <Text role="title-medium" as="h3">
                          {collection.name}
                        </Text>

                        {role && ROLE_COPY[role] ? (
                          <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                            {ROLE_COPY[role]}
                          </Text>
                        ) : (
                          <Text role="body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                            No role recorded — this collection was not created by the gateway.
                          </Text>
                        )}

                        <dl style={{ margin: 0, display: "grid", gap: "var(--bb-space-1)" }}>
                          {[
                            ["Documents", count(collection.count)],
                            ["Dimension", collection.dimension === null ? "unknown" : String(collection.dimension)],
                            ["Embedding model", model ?? "not recorded"],
                            ["Distance space", space ?? "not reported"],
                          ].map(([term, value]) => (
                            <div
                              key={term}
                              style={{ display: "flex", justifyContent: "space-between", gap: "var(--bb-space-3)" }}
                            >
                              <dt className="bb-body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
                                {term}
                              </dt>
                              <dd className="bb-body-small bb-tabular" style={{ margin: 0 }}>
                                {value}
                              </dd>
                            </div>
                          ))}
                        </dl>

                        {/* Trust flags. Each is colour PLUS glyph PLUS label. */}
                        <div style={{ display: "grid", gap: "var(--bb-space-2)" }}>
                          {unscoreable ? (
                            <StatusChip
                              role="critical"
                              label={`Space is ${space}`}
                              detail="cannot be scored — distances here are not comparable to the threshold"
                            />
                          ) : null}
                          {unknownSpace ? (
                            <StatusChip
                              role="warning"
                              label="Space unknown"
                              detail="the gateway does not report this collection"
                            />
                          ) : null}
                          {modelMismatch ? (
                            <StatusChip
                              role="serious"
                              label="Stale vectors"
                              detail={`built with ${model}, live model is ${liveModel} — re-embedding required`}
                            />
                          ) : null}
                          {empty ? (
                            <StatusChip
                              role="warning"
                              label="Empty"
                              detail="contributes nothing to retrieval"
                            />
                          ) : null}
                          {!unscoreable && !unknownSpace && !modelMismatch && !empty ? (
                            <StatusChip role="good" label="Usable" />
                          ) : null}
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>
            )}
          </PanelBody>
        </Panel>
      </main>
    </div>
  );
}
