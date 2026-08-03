import { describe, expect, it } from "vitest";

import {
  axisFormatter,
  compact,
  labelIndices,
  niceTicks,
  segments,
  type Point,
} from "../geometry";

describe("segments", () => {
  it("breaks the line at a null instead of joining across it", () => {
    // Joining across a gap draws a line through data that does not exist;
    // replacing the gap with zero asserts a measurement of zero. A break is the
    // only honest option, and this is the mechanism.
    const points: Point[] = [
      { x: "a", y: 1 },
      { x: "b", y: 2 },
      { x: "c", y: null },
      { x: "d", y: 4 },
      { x: "e", y: 5 },
    ];

    const runs = segments(points);

    expect(runs).toHaveLength(2);
    expect(runs[0]?.map((p) => p.y)).toEqual([1, 2]);
    expect(runs[1]?.map((p) => p.y)).toEqual([4, 5]);
    // Indices are preserved so the gap keeps its horizontal position.
    expect(runs[1]?.[0]?.index).toBe(3);
  });

  it("never emits zero for a null", () => {
    const runs = segments([{ x: "a", y: null }, { x: "b", y: 7 }]);

    expect(runs.flat().map((p) => p.y)).toEqual([7]);
    expect(runs.flat().map((p) => p.y)).not.toContain(0);
  });

  it("handles an all-null series as no runs at all", () => {
    expect(segments([{ x: "a", y: null }, { x: "b", y: null }])).toEqual([]);
  });

  it("keeps an isolated point between two gaps", () => {
    // A one-point run draws no path, which is why the chart renders a dot for it.
    const runs = segments([
      { x: "a", y: null },
      { x: "b", y: 3 },
      { x: "c", y: null },
    ]);

    expect(runs).toHaveLength(1);
    expect(runs[0]).toHaveLength(1);
  });
});

describe("niceTicks", () => {
  it("rounds to clean 1/2/5 steps", () => {
    expect(niceTicks(0, 100)).toEqual([0, 20, 40, 60, 80, 100]);
  });

  it("does not collapse when min equals max", () => {
    expect(niceTicks(5, 5)).toEqual([5, 6]);
  });

  it("always reaches the maximum, so no value plots outside the frame", () => {
    // charts.js stopped at max + step/2, which for 54823 topped out at 50000 —
    // and the plot scales to the top tick, so the real maximum drew above the
    // frame. Regression guard for that.
    for (const max of [54823, 100, 1, 1_146_120, 7, 999]) {
      expect(Math.max(...niceTicks(0, max))).toBeGreaterThanOrEqual(max);
    }
  });
});

describe("axisFormatter", () => {
  it("picks one style for the whole axis from its largest tick", () => {
    // Formatting each tick on its own magnitude mixes styles down one axis —
    // "14K" above "8,000" reads as two different scales.
    const format = axisFormatter(1_200_000);
    expect(format(1_200_000)).toBe("1.2M");
    expect(format(400_000)).toBe("0.4M");
    expect(format(0)).toBe("0");
  });

  it("uses thousands for a mid-range axis", () => {
    const format = axisFormatter(54_823);
    expect(format(50_000)).toBe("50K");
  });

  it("leaves small numbers alone", () => {
    expect(axisFormatter(42)(12)).toBe("12");
  });
});

describe("compact", () => {
  it("renders an absent value as an em dash, not zero", () => {
    expect(compact(null)).toBe("—");
    expect(compact(0)).toBe("0");
  });

  it("scales large magnitudes", () => {
    expect(compact(2_270_601)).toBe("2.3M");
    expect(compact(54_823)).toBe("54.8K");
  });
});

describe("labelIndices", () => {
  it("labels first, middle and last only — never every point", () => {
    expect(labelIndices(11)).toEqual([0, 5, 10]);
  });

  it("degrades for tiny series without duplicating", () => {
    expect(labelIndices(1)).toEqual([0]);
    expect(labelIndices(2)).toEqual([0, 1]);
  });
});
