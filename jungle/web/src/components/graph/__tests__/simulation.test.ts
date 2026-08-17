import { describe, expect, it } from "vitest";

import {
  type GraphEdge,
  type GraphNode,
  edgeKey,
  endpointId,
  hashUnit,
  neighboursOf,
  radiusFor,
  seededRandom,
  settle,
} from "../simulation";

/**
 * The layout has no visual feedback loop — a wrong force constant looks like a
 * slightly odd picture rather than a failure. These pin the properties that
 * matter: that it is reproducible despite d3 reaching for Math.random by default,
 * that everything stays clickable inside the viewport, and that a stronger
 * similarity really does draw two memories closer.
 */

const VIEW = { width: 800, height: 600 };

function nodes(count: number): GraphNode[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `exchange:x_${i}`,
    kind: "exchange",
    label: `memory ${i}`,
    degree: 1,
  }));
}

function edge(a: string, b: string, kind = "contains", weight: number | null = null): GraphEdge {
  return { source: a, target: b, kind, weight };
}

describe("hashUnit", () => {
  it("is stable for the same string", () => {
    expect(hashUnit("exchange:x_1")).toBe(hashUnit("exchange:x_1"));
  });

  it("separates similar ids", () => {
    expect(hashUnit("exchange:x_1")).not.toBe(hashUnit("exchange:x_2"));
  });

  it("stays in the unit interval", () => {
    for (const id of ["", "a", "collection:conversations", "x".repeat(400)]) {
      const value = hashUnit(id);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
    }
  });
});

describe("seededRandom", () => {
  it("repeats exactly for the same seed", () => {
    const a = seededRandom(1234);
    const b = seededRandom(1234);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });

  it("differs across seeds", () => {
    expect(seededRandom(1)()).not.toBe(seededRandom(2)());
  });

  it("stays in the unit interval", () => {
    const next = seededRandom(99);
    for (let i = 0; i < 200; i += 1) {
      const value = next();
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
    }
  });
});

describe("settle", () => {
  it("is deterministic", () => {
    // d3-force jiggles coincident bodies with Math.random unless given a seeded
    // source. Without that, the graph would lay out differently on every render,
    // reading as data having changed when it has not.
    const graph = nodes(12);
    const links = [edge("exchange:x_0", "exchange:x_1"), edge("exchange:x_2", "exchange:x_3")];

    const first = settle(graph, links, VIEW);
    const second = settle(graph, links, VIEW);

    expect(first.map((n) => [n.id, n.x, n.y])).toEqual(second.map((n) => [n.id, n.x, n.y]));
  });

  it("keeps every node inside the viewport", () => {
    // Anything outside cannot be clicked, so this is a functional requirement.
    const result = settle(nodes(40), [], VIEW);

    for (const node of result) {
      expect(node.x).toBeGreaterThanOrEqual(0);
      expect(node.x).toBeLessThanOrEqual(VIEW.width);
      expect(node.y).toBeGreaterThanOrEqual(0);
      expect(node.y).toBeLessThanOrEqual(VIEW.height);
    }
  });

  it("produces finite positions for isolated nodes", () => {
    const result = settle(nodes(6), [], VIEW);
    expect(result.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
  });

  it("places connected nodes nearer than the farthest unconnected one", () => {
    const graph = nodes(8);
    const result = settle(graph, [edge("exchange:x_0", "exchange:x_1")], VIEW);
    const at = (id: string) => result.find((n) => n.id === id)!;
    const distance = (a: string, b: string) => Math.hypot(at(a).x - at(b).x, at(a).y - at(b).y);

    const linked = distance("exchange:x_0", "exchange:x_1");
    const others = graph
      .slice(2)
      .map((n) => distance("exchange:x_0", n.id))
      .sort((a, b) => a - b);
    const farthest = others.at(-1) ?? Number.POSITIVE_INFINITY;

    expect(linked).toBeLessThan(farthest);
  });

  it("separates nodes rather than fusing them", () => {
    // forceCollide exists for this; overlapping nodes cannot be clicked apart.
    const [first, second] = settle(nodes(2), [], VIEW);
    expect(first).toBeDefined();
    expect(second).toBeDefined();
    expect(Math.hypot(first!.x - second!.x, first!.y - second!.y)).toBeGreaterThan(1);
  });

  it("handles the degenerate sizes", () => {
    expect(settle([], [], VIEW)).toEqual([]);
    const one = settle(nodes(1), [], VIEW);
    expect(one).toHaveLength(1);
    expect([one[0]!.x, one[0]!.y]).toEqual([VIEW.width / 2, VIEW.height / 2]);
  });

  it("ignores edges naming nodes that are not present", () => {
    // Filtering a kind out of the view leaves its edges behind for a render, and
    // forceLink throws on an unresolvable endpoint rather than skipping it.
    const result = settle(nodes(3), [edge("exchange:x_0", "exchange:missing")], VIEW);
    expect(result).toHaveLength(3);
    expect(result.every((n) => Number.isFinite(n.x))).toBe(true);
  });

  it("ignores self-edges", () => {
    const result = settle(nodes(2), [edge("exchange:x_0", "exchange:x_0")], VIEW);
    expect(result.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
  });

  it("pulls a strong similarity closer than a weak one", () => {
    // The rest length carries the score, not the stiffness: a spring settles at
    // its rest length whatever its strength, so scaling strength by score would
    // leave both edges at the same distance.
    const graph: GraphNode[] = [
      { id: "a", kind: "exchange", label: "a", degree: 2 },
      { id: "b", kind: "exchange", label: "b", degree: 1 },
      { id: "c", kind: "exchange", label: "c", degree: 1 },
    ];
    const result = settle(
      graph,
      [edge("a", "b", "similar_to", 0.95), edge("a", "c", "similar_to", 0.62)],
      { ...VIEW, iterations: 500 },
    );
    const at = (id: string) => result.find((n) => n.id === id)!;

    const strong = Math.hypot(at("a").x - at("b").x, at("a").y - at("b").y);
    const weak = Math.hypot(at("a").x - at("c").x, at("a").y - at("c").y);
    expect(strong).toBeLessThan(weak);
  });
});

describe("radiusFor", () => {
  it("grows with degree so a hub reads as one before it is clicked", () => {
    const small = radiusFor({ id: "a", kind: "exchange", label: "", degree: 1 });
    const hub = radiusFor({ id: "b", kind: "collection", label: "", degree: 40 });
    expect(hub).toBeGreaterThan(small);
  });

  it("is bounded, so one hub cannot swallow the canvas", () => {
    expect(radiusFor({ id: "a", kind: "collection", label: "", degree: 100_000 })).toBeLessThanOrEqual(22);
  });

  it("survives a degree of zero", () => {
    expect(radiusFor({ id: "a", kind: "exchange", label: "", degree: 0 })).toBeGreaterThan(0);
  });
});

describe("neighboursOf", () => {
  it("finds both directions", () => {
    expect(neighboursOf("a", [edge("a", "b"), edge("c", "a")])).toEqual(new Set(["b", "c"]));
  });

  it("returns empty for an isolated node", () => {
    expect(neighboursOf("z", [edge("a", "b")]).size).toBe(0);
  });
});

describe("edgeKey", () => {
  it("treats similarity as undirected", () => {
    // A–B and B–A are one relation; two keys would draw two overlapping lines and
    // double the node's apparent connection count.
    expect(edgeKey(edge("a", "b", "similar_to", 0.8))).toBe(edgeKey(edge("b", "a", "similar_to", 0.8)));
  });

  it("keeps structural edges directed", () => {
    expect(edgeKey(edge("a", "b", "contains"))).not.toBe(edgeKey(edge("b", "a", "contains")));
  });

  it("separates kinds between the same pair", () => {
    expect(edgeKey(edge("a", "b", "contains"))).not.toBe(edgeKey(edge("a", "b", "belongs_to")));
  });
});

describe("endpointId", () => {
  it("reads a string endpoint before d3 binds it", () => {
    expect(endpointId("exchange:x_1")).toBe("exchange:x_1");
  });

  it("reads a bound node endpoint", () => {
    expect(endpointId({ id: "exchange:x_1", kind: "exchange", label: "", degree: 0, x: 0, y: 0 })).toBe(
      "exchange:x_1",
    );
  });
});
