/**
 * Value formatting.
 *
 * One rule runs through all of it: a value we do not have is never formatted as
 * a value we do have. `null` becomes explanatory text, never `0`.
 */

const NUMBER = new Intl.NumberFormat("en-US");

export function count(value: number): string {
  return NUMBER.format(value);
}

/**
 * A rate that may be absent.
 *
 * `null` means "no samples". Rendering it as 0% would turn the absence of
 * evidence into evidence of failure (DESIGN-BOOK.md §10, BB-107).
 */
export function rate(value: number | null): string {
  if (value === null) return "no samples";
  return `${(value * 100).toFixed(1)}%`;
}

export function percent(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function money(value: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    // Costs here are frequently sub-cent; two decimals would render most of a
    // day's spend as $0.00.
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(value);
}

const UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export function bytes(value: number): string {
  if (value === 0) return "0 B";
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), UNITS.length - 1);
  const scaled = value / 1024 ** exponent;
  return `${scaled.toFixed(exponent === 0 ? 0 : 1)} ${UNITS[exponent]}`;
}

/**
 * A similarity score, or the refusal to score one.
 *
 * The backend returns null for any non-cosine collection because those distances
 * cannot be compared to the threshold. That refusal is information and must be
 * rendered as such — never 0, never an em dash, never a hidden row.
 */
export function similarity(value: number | null): string {
  return value === null ? "cannot be scored" : value.toFixed(3);
}
