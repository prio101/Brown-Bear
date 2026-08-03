/**
 * Where a number came from (BB-103 §103.1, DESIGN-BOOK.md §10.1).
 *
 * This stack has three kinds of number and they are not equally trustworthy:
 *
 *   measured  counted locally — the Ollama proxy counts its own tokens
 *   reported  claimed by a remote client via /ext/exchange. The client is the
 *             only party that sees the Anthropic response, so usage is reported,
 *             not captured; a client can under-report by setting BB_NO_STORE=1
 *             or simply not running its hook
 *   derived   computed — an aggregation, or a cost from a price table
 *
 * They must not share a visual treatment, which means the distinction has to
 * survive the data layer rather than being reconstructed in a component.
 */

export type Provenance = "measured" | "reported" | "derived";

/**
 * Trust ranking, used to pick what a mixed total should claim.
 *
 * `reported` sits lowest deliberately: a value derived from measured data is
 * better founded than a raw claim from a machine we do not control.
 */
const RANK: Record<Provenance, number> = {
  measured: 2,
  derived: 1,
  reported: 0,
};

/** Backend `source` values, as actually emitted by /api/tokens/*. */
const FROM_SOURCE: Record<string, Provenance> = {
  local_ollama: "measured",
  remote_api: "reported",
  // The raw event table mixes both origins, so a total over it is an aggregate.
  token_events: "derived",
  token_aggregates: "derived",
};

export function provenanceOf(source: string): Provenance {
  return FROM_SOURCE[source] ?? "derived";
}

/**
 * What a combined total may claim: the weakest kind present.
 *
 * A row that adds a remote client's claim to a locally measured count is only as
 * good as the claim, and saying otherwise is the specific dishonesty the Design
 * Book's provenance rule exists to prevent.
 */
export function weakestProvenance(kinds: readonly Provenance[]): Provenance {
  if (kinds.length === 0) return "derived";
  return kinds.reduce((weakest, kind) => (RANK[kind] < RANK[weakest] ? kind : weakest));
}

/** Marker glyphs from DESIGN-BOOK.md §10.1. Always paired with a text label. */
export const PROVENANCE_MARKER: Record<Provenance, string> = {
  measured: "●",
  reported: "◐",
  derived: "∿",
};

export const PROVENANCE_LABEL: Record<Provenance, string> = {
  measured: "measured",
  reported: "reported",
  derived: "derived",
};

export const PROVENANCE_EXPLANATION: Record<Provenance, string> = {
  measured: "Counted locally by this stack.",
  reported: "Claimed by a remote client. A client that stops reporting under-reports silently.",
  derived: "Computed — an aggregation or a cost estimate from a price table.",
};
