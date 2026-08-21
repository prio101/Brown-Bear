"use client";

/**
 * Prompt Palace (spec 012).
 *
 * Three panes: what was asked, what came back, and what it sits near. The last is
 * the reason the page exists — the other surfaces can tell you how many prompts
 * arrived and what they cost, but not whether the memory already held an answer.
 *
 * Everything here is a *claim*. Brown Bear never sees the model call: a client
 * posts the finished exchange to `/ext/exchange`, so the prompt, the answer and
 * the machine name are all reported rather than measured, and the machine name in
 * particular is uncheckable — the edge authenticates one shared secret for every
 * machine. So `machine: null` renders as "not recorded" and never as this host.
 *
 * Two rules from the design guide are load-bearing here rather than decorative:
 *
 *   A similarity that cannot be scored renders as "cannot be scored", never as 0
 *   and never hidden (Part 3, rule 2). Only cosine converts to the 0.95-style
 *   cutoff; a 0 in any other space would assert "unrelated", which nobody claimed.
 *
 *   A neighbour is never shown without its score and the cutoff it is being judged
 *   against (rule 1). A bare "related" tells a reader nothing they can falsify.
 */

import { useCallback, useEffect, useState } from "react";

import type { Prompt, PromptRelated } from "@/lib/api/schemas";

import { RelativeTime } from "./RelativeTime";

/** Neither list is ranked against the other: a prior prompt is an answer the cache
 *  might have served, a chunk is context that would have been injected. */
type Pane = "prompts" | "chunks";

function Score({ score, threshold }: { score: number | null | undefined; threshold: number }) {
  if (score === null || score === undefined) {
    return (
      <span className="bb-label-medium bb-score bb-score-unscored">
        {/* Never 0, never blank (DESIGN-GUIDE Part 3 rule 2). */}
        cannot be scored
      </span>
    );
  }
  const above = score >= threshold;
  return (
    <span
      className="bb-label-medium bb-score"
      data-above={above ? "true" : undefined}
      title={
        above
          ? `${score.toFixed(3)} is at or above the ${threshold} cutoff, so this could be served as a hit`
          : `${score.toFixed(3)} is below the ${threshold} cutoff, so this is related but not servable`
      }
    >
      {/* Glyph plus number, never colour alone (rule 5). */}
      <span aria-hidden="true">{above ? "●" : "○"}</span> {score.toFixed(3)}
    </span>
  );
}

function Attribution({ machine }: { machine: string | null }) {
  if (machine) {
    return (
      <span className="bb-body-small bb-prompt-machine" title="Reported by the client. The edge authenticates one shared secret for every machine, so this cannot be verified.">
        {machine}
      </span>
    );
  }
  return (
    <span
      className="bb-body-small bb-prompt-machine bb-prompt-unattributed"
      title="No machine was reported: stored before the field existed, or by a client that does not send it. It does not mean the prompt ran on this host."
    >
      not recorded
    </span>
  );
}

export function PromptPalace({
  initial,
  threshold,
  scorable,
}: {
  initial: Prompt[];
  threshold: number;
  scorable: boolean;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(initial[0]?.id ?? null);
  const [detail, setDetail] = useState<Prompt | null>(null);
  const [related, setRelated] = useState<PromptRelated | null>(null);
  const [pane, setPane] = useState<Pane>("prompts");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedError, setRelatedError] = useState<string | null>(null);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    setRelatedError(null);
    setDetail(null);
    setRelated(null);

    // Two requests rather than one: the answer is a row lookup and arrives
    // immediately, while the neighbours are two vector searches. Waiting for the
    // second to show the first would make reading an answer feel like a query.
    try {
      const response = await fetch(`/api/prompts/${encodeURIComponent(id)}`, {
        headers: { accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`the gateway returned ${response.status}`);
      setDetail((await response.json()) as Prompt);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }

    // Panels fail independently (Part 3, rule 8): a failed similarity lookup must
    // not take the answer down with it.
    try {
      const response = await fetch(`/api/prompts/${encodeURIComponent(id)}/related`, {
        headers: { accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`the gateway returned ${response.status}`);
      setRelated((await response.json()) as PromptRelated);
    } catch (cause) {
      setRelatedError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    if (selectedId) void load(selectedId);
  }, [selectedId, load]);

  const selected = detail ?? initial.find((p) => p.id === selectedId) ?? null;

  if (initial.length === 0) {
    return (
      <p className="bb-body-medium bb-graph-note">
        No prompts stored yet. A machine reports one with{" "}
        <code>POST /ext/exchange</code> when a turn finishes — the client is the only
        party that saw the response, so nothing arrives here until one does.
      </p>
    );
  }

  return (
    <div className="bb-file-layout">
      <ul className="bb-file-list" aria-label="Stored prompts">
        {initial.map((prompt) => {
          const active = prompt.id === selectedId;
          return (
            <li key={prompt.id}>
              <button
                type="button"
                className="bb-interactive bb-file-row"
                aria-current={active ? "true" : undefined}
                data-active={active ? "true" : undefined}
                onClick={() => setSelectedId(prompt.id)}
              >
                <span className="bb-body-medium bb-file-name">
                  {prompt.prompt || "(no prompt recorded)"}
                </span>
                <span className="bb-body-small bb-file-meta">
                  <Attribution machine={prompt.machine} />
                  {" · "}
                  {prompt.model ?? "model not recorded"}
                  {prompt.created_at ? (
                    <>
                      {" · "}
                      <RelativeTime iso={prompt.created_at} initial={prompt.created_at} />
                    </>
                  ) : null}
                </span>
                {prompt.cacheable === false ? (
                  <span className="bb-label-medium" title="Volatile: this answer will not be served from the cache however closely a later prompt matches.">
                    <span aria-hidden="true">⚠</span> not cacheable
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>

      <section className="bb-file-detail" aria-label="Prompt detail">
        {selected === null ? (
          <p className="bb-body-medium bb-graph-note">Select a prompt.</p>
        ) : (
          <>
            <header>
              <h2 className="bb-title-medium" style={{ margin: 0, overflowWrap: "anywhere" }}>
                {selected.prompt || "(no prompt recorded)"}
              </h2>
              <p className="bb-body-small bb-graph-note" style={{ margin: "4px 0 0" }}>
                <Attribution machine={selected.machine} /> · {selected.project ?? "no project"} ·{" "}
                {selected.model ?? "model not recorded"}
              </p>
            </header>

            <div>
              <span className="bb-graph-detail-kind">Response</span>
              {loading ? (
                <p className="bb-body-small bb-graph-note">Loading…</p>
              ) : error ? (
                <p className="bb-body-small bb-prompt-error">Could not load the response: {error}</p>
              ) : selected.response ? (
                <pre className="bb-file-extraction">{selected.response}</pre>
              ) : (
                // The listing carries no answer, so "empty" is not knowable yet.
                <p className="bb-body-small bb-graph-note">Loading the response…</p>
              )}
            </div>

            <dl className="bb-graph-dl">
              {[
                ["reported by", selected.machine ?? "not recorded"],
                ["stored", selected.created_at ?? "not recorded"],
                ["cacheable", selected.cacheable === false ? "no — volatile prompt" : "yes"],
                ["stale after", selected.stale_after ?? "no expiry set"],
                ["embedded with", selected.embedding_model ?? "not recorded"],
                ["answer length", selected.response_chars ? `${selected.response_chars} chars` : "—"],
              ].map(([term, value]) => (
                <div className="bb-graph-field" key={term}>
                  <dt className="bb-body-small">{term}</dt>
                  <dd className="bb-body-small">{value}</dd>
                </div>
              ))}
            </dl>

            <div>
              <div className="bb-prompt-tabs" role="tablist" aria-label="Related memory">
                <button
                  type="button"
                  role="tab"
                  aria-selected={pane === "prompts"}
                  className="bb-interactive bb-preview-step bb-preview-step-wide"
                  data-active={pane === "prompts" ? "true" : undefined}
                  onClick={() => setPane("prompts")}
                >
                  {`Similar prompts${related ? ` (${related.prompts.length})` : ""}`}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={pane === "chunks"}
                  className="bb-interactive bb-preview-step bb-preview-step-wide"
                  data-active={pane === "chunks" ? "true" : undefined}
                  onClick={() => setPane("chunks")}
                >
                  {`Knowledge chunks${related ? ` (${related.chunks.length})` : ""}`}
                </button>
              </div>

              {relatedError ? (
                <p className="bb-body-small bb-prompt-error">
                  Could not look up what this is near: {relatedError}. The response above is
                  unaffected.
                </p>
              ) : related === null ? (
                <p className="bb-body-small bb-graph-note">Searching the collections…</p>
              ) : related.unavailable ? (
                <p className="bb-body-small bb-graph-note">{related.unavailable}</p>
              ) : (
                <>
                  <p className="bb-body-small bb-graph-note">
                    {scorable && related.scorable
                      ? `Cosine similarity, floor ${related.min_similarity}. A score at or above ${related.threshold} could be served as a cache hit; below it, related but not servable.`
                      : `This collection is not in cosine space, so nothing here can be scored against the ${related.threshold} cutoff — the neighbours are listed without scores rather than with zeros.`}
                  </p>

                  {pane === "prompts" ? (
                    related.prompts.length === 0 ? (
                      <p className="bb-body-small bb-graph-note">
                        Nothing else in the corpus resembles this prompt above the floor. That is a
                        real state, and an interesting one: it means the memory had nothing to offer
                        here.
                      </p>
                    ) : (
                      <ul className="bb-prompt-related" aria-label="Similar prompts">
                        {related.prompts.map((neighbour) => (
                          <li key={neighbour.id}>
                            <button
                              type="button"
                              className="bb-interactive bb-prompt-related-row"
                              onClick={() => setSelectedId(neighbour.id)}
                            >
                              <span className="bb-prompt-related-head">
                                <Score score={neighbour.score} threshold={related.threshold} />
                                {neighbour.would_hit ? (
                                  <span className="bb-label-medium" title="Above the cutoff and cacheable: a later identical prompt could be answered from this instead of calling the model.">
                                    <span aria-hidden="true">✓</span> would hit
                                  </span>
                                ) : null}
                              </span>
                              <span className="bb-body-medium bb-file-name">
                                {neighbour.prompt || "(no prompt recorded)"}
                              </span>
                              <span className="bb-body-small bb-file-meta">
                                <Attribution machine={neighbour.machine} />
                                {" · "}
                                {neighbour.model ?? "model not recorded"}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )
                  ) : related.chunks.length === 0 ? (
                    <p className="bb-body-small bb-graph-note">
                      No stored document resembles this prompt above the floor, so a retrieval
                      lookup would have injected nothing.
                    </p>
                  ) : (
                    <ul className="bb-prompt-related" aria-label="Knowledge chunks">
                      {related.chunks.map((chunk) => (
                        <li key={chunk.id}>
                          <div className="bb-prompt-related-row bb-prompt-chunk">
                            <span className="bb-prompt-related-head">
                              <Score score={chunk.score} threshold={related.threshold} />
                              <span className="bb-body-small bb-file-meta">
                                {chunk.source ?? "source not recorded"}
                                {chunk.chunk_index !== null && chunk.chunk_index !== undefined
                                  ? ` · chunk ${chunk.chunk_index + 1}${chunk.chunk_count ? ` of ${chunk.chunk_count}` : ""}`
                                  : ""}
                              </span>
                            </span>
                            {/* Formatted as a passage, never as an answer: this is
                                supporting context, and the guardrail is visual. */}
                            <blockquote className="bb-prompt-passage bb-body-small">
                              {chunk.text ?? "(no text stored)"}
                            </blockquote>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
