import {
  PROVENANCE_EXPLANATION,
  PROVENANCE_LABEL,
  PROVENANCE_MARKER,
  type Provenance,
} from "@/lib/api/provenance";
import { relativeAge } from "@/lib/api/freshness";

/**
 * Where a number came from and how old it is (DESIGN-BOOK.md §10.1).
 *
 * Every number that is not a local fact carries one. The freshness half is not
 * decoration: "2 min ago" is what makes a zero interpretable, because without it
 * a zero could equally be a quiet day or a collector that died on Tuesday.
 */
export function ProvenanceBadge({
  kind,
  fetchedAt,
  now,
}: {
  kind: Provenance;
  fetchedAt: Date;
  /** Injectable so a server render and a test agree on "now". */
  now?: Date;
}) {
  return (
    <span
      className="bb-label-small"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "var(--bb-space-1)",
        color: "var(--bb-on-surface-variant)",
      }}
      title={PROVENANCE_EXPLANATION[kind]}
    >
      <span aria-hidden="true">{PROVENANCE_MARKER[kind]}</span>
      <span>{PROVENANCE_LABEL[kind]}</span>
      <span aria-hidden="true">·</span>
      <span>{relativeAge(fetchedAt, now)}</span>
    </span>
  );
}
