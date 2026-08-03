/**
 * Freshness formatting (BB-103 §103.4).
 *
 * Every provenance badge carries the age of its number, because "2 min ago" is
 * what makes a zero interpretable: without it, a zero could equally mean a quiet
 * day or a collector that died on Tuesday.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * Coarse by design. Second-level precision on an operations dashboard invites
 * reading noise as signal, and the number it labels is sampled every 30s anyway.
 */
export function relativeAge(then: Date, now: Date = new Date()): string {
  const elapsed = now.getTime() - then.getTime();

  // Clock skew between the app container and the browser is real; a future
  // timestamp is not worth a special display.
  if (elapsed < 0) return "just now";
  if (elapsed < MINUTE) return "just now";

  if (elapsed < HOUR) {
    const minutes = Math.floor(elapsed / MINUTE);
    return `${minutes} min ago`;
  }
  if (elapsed < DAY) {
    const hours = Math.floor(elapsed / HOUR);
    return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  }
  const days = Math.floor(elapsed / DAY);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

/** How stale is too stale, per the liveness banner's states (§10.4). */
export type Staleness = "fresh" | "stale" | "very-stale";

export function staleness(then: Date, expectedIntervalMs: number, now: Date = new Date()): Staleness {
  const elapsed = Math.max(0, now.getTime() - then.getTime());
  if (elapsed <= expectedIntervalMs * 2) return "fresh";
  if (elapsed <= expectedIntervalMs * 10) return "stale";
  return "very-stale";
}
