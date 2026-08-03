/**
 * Chart geometry and number formatting (BB-106).
 *
 * Ported from `jungle/app/brownbear/static/charts.js`, whose conventions this
 * sprint preserves rather than re-picks. Pure functions, kept out of the
 * components so they can be tested without a DOM.
 */

/** A point whose value may be absent. `null` breaks the line; it is never zero. */
export type Point = { x: string; y: number | null };

export type Series = {
  name: string;
  /** A `--bb-series-N` custom property name. Slots are assigned in fixed order. */
  colorVar: string;
  points: readonly Point[];
};

/**
 * Axis ticks rounded to clean numbers, so the axis carries unlabelled values
 * between the labelled ones.
 */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) return [min, min + 1];
  const span = max - min;
  const rawStep = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalised = rawStep / magnitude;
  const step = (normalised >= 5 ? 5 : normalised >= 2 ? 2 : 1) * magnitude;

  // Diverges from charts.js deliberately. Its loop stopped at `max + step/2`,
  // which can leave the top tick BELOW the data maximum — niceTicks(0, 54823)
  // returned a top of 50000. Since the plot scales to the top tick, any value
  // above it renders outside the plot area. Guaranteeing the last tick reaches
  // the maximum is the fix; the clean 1/2/5 steps are unchanged.
  const ticks: number[] = [];
  for (let value = Math.floor(min / step) * step; ; value += step) {
    ticks.push(Number(value.toFixed(10)));
    if (value >= max - 1e-9) break;
  }
  return ticks;
}

/**
 * One formatter for the whole axis, chosen from its largest tick.
 *
 * Formatting each tick on its own magnitude mixes styles down a single axis —
 * "14K" sitting above "8,000" — which reads as two different scales.
 */
export function axisFormatter(maxTick: number): (value: number) => string {
  const max = Math.abs(maxTick);
  const scaled = (divisor: number, suffix: string) => (value: number) =>
    value === 0 ? "0" : `${(value / divisor).toFixed(value % divisor === 0 ? 0 : 1)}${suffix}`;

  if (max >= 1e6) return scaled(1e6, "M");
  if (max >= 1e4) return scaled(1e3, "K");
  return (value) => value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** Compact form for tooltips and bar tips. */
export function compact(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1).replace(/\.0$/, "")}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 1e4) return `${(value / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/**
 * Split a series into runs of consecutive present values.
 *
 * This is the whole reason nulls are modelled rather than filtered: joining
 * across a gap draws a line through data that does not exist, and replacing the
 * gap with zero asserts a measurement of zero. Both are lies; a break is the
 * truth.
 */
export function segments(points: readonly Point[]): { index: number; y: number }[][] {
  const runs: { index: number; y: number }[][] = [];
  let run: { index: number; y: number }[] = [];

  points.forEach((point, index) => {
    if (point.y === null) {
      if (run.length) runs.push(run);
      run = [];
      return;
    }
    run.push({ index, y: point.y });
  });
  if (run.length) runs.push(run);

  return runs;
}

/** Which x positions get a label: first, middle, last. Never every point. */
export function labelIndices(count: number): number[] {
  if (count <= 1) return [0];
  return [...new Set([0, Math.floor((count - 1) / 2), count - 1])];
}

export function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
