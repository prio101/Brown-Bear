/**
 * d3-force simulation for the memory graph (BB-301).
 *
 * Replaces the hand-rolled spring-electrical layout. d3-force is npm-bundled, not
 * loaded from a CDN, so the offline requirement that rules out Swagger on
 * /api-doc/v1 is untouched — the whole graph still ships inside the app bundle.
 *
 * d3 gives three things the hand-rolled version did not: many-body repulsion via
 * Barnes-Hut (O(n log n) rather than O(n²), so this keeps working as the corpus
 * grows), collision resolution so nodes stop overlapping their own labels, and a
 * live alpha-decayed cooling schedule that settles visibly instead of appearing
 * fully-formed.
 *
 * **Determinism is preserved deliberately.** d3-force jiggles coincident nodes with
 * Math.random by default, which would make the graph lay out differently on every
 * render — reading as data having changed when it has not, the same lie BB-203
 * fixed on the dashboard. `simulation.randomSource()` takes a seeded PRNG instead,
 * so the same graph still lays out identically every time and the tests can assert
 * it.
 */

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
} from "d3-force";

export type GraphNode = {
  id: string;
  kind: string;
  label: string;
  degree: number;
  meta?: Record<string, unknown>;
};

export type GraphEdge = {
  source: string;
  target: string;
  kind: string;
  weight: number | null;
};

/** What d3 mutates: the node plus its simulated position and velocity. */
export type SimNode = GraphNode & {
  x: number;
  y: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
};

export type SimLink = {
  source: SimNode | string;
  target: SimNode | string;
  kind: string;
  weight: number | null;
};

export type Positioned = GraphNode & { x: number; y: number };

export type SimulationOptions = {
  width: number;
  height: number;
  linkDistance?: number;
  charge?: number;
};

const DEFAULTS = {
  linkDistance: 95,
  charge: -420,
};

/**
 * Deterministic unit float from a string. FNV-1a — cheap, dependency-free, and
 * well-spread for short ASCII ids, which is all a position seed needs.
 */
export function hashUnit(value: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return (hash >>> 0) / 0x100000000;
}

/**
 * Seeded PRNG handed to d3 in place of Math.random.
 *
 * mulberry32: 32 bits of state, uniform enough for jitter, and — the point —
 * reproducible. d3 calls this during initialisation and whenever two bodies
 * coincide.
 */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Rest length for one edge. */
function restLength(edge: GraphEdge, base: number): number {
  if (edge.kind !== "similar_to") return base;
  // The REST LENGTH carries the score, not the stiffness. A spring settles at its
  // rest length whatever its strength, so scaling strength by score changes only
  // how fast it gets there — every edge would still converge to the same distance
  // and a strong relation would look identical to a weak one.
  const weight = Math.min(1, Math.max(0, edge.weight ?? 0.5));
  return base * (1.5 - weight);
}

/** Node radius from structural degree. A hub should read as one before it is clicked. */
export function radiusFor(node: GraphNode): number {
  return Math.min(22, 7 + Math.sqrt(Math.max(0, node.degree)) * 2.5);
}

/**
 * Build a stopped simulation.
 *
 * Returned stopped so the caller decides whether to tick it live (the page, for
 * the settling animation) or run it to rest synchronously (`settle`, for tests).
 */
export function createSimulation(
  nodes: GraphNode[],
  edges: GraphEdge[],
  options: SimulationOptions,
): { simulation: Simulation<SimNode, undefined>; nodes: SimNode[]; links: SimLink[] } {
  const { width, height } = options;
  const linkDistance = options.linkDistance ?? DEFAULTS.linkDistance;
  const charge = options.charge ?? DEFAULTS.charge;

  // Seeded on a phyllotactic spiral. A uniform-random start routinely drops two
  // nodes almost on top of each other, and the enormous repulsion between them
  // throws the first frames across the canvas.
  const golden = Math.PI * (3 - Math.sqrt(5));
  const radius = Math.min(width, height) * 0.36;
  const simNodes: SimNode[] = nodes.map((node, index) => {
    const t = (index + 0.5) / Math.max(1, nodes.length);
    const angle = index * golden + (hashUnit(node.id) * 0.5 - 0.25);
    return {
      ...node,
      x: width / 2 + radius * Math.sqrt(t) * Math.cos(angle),
      y: height / 2 + radius * Math.sqrt(t) * Math.sin(angle),
    };
  });

  const present = new Set(simNodes.map((n) => n.id));
  // Edges naming a node that is not present would make forceLink throw. Filtering
  // a kind out of the view leaves exactly those behind for a render.
  const links: SimLink[] = edges
    .filter((e) => present.has(e.source) && present.has(e.target) && e.source !== e.target)
    .map((e) => ({ source: e.source, target: e.target, kind: e.kind, weight: e.weight }));

  const simulation = forceSimulation<SimNode>(simNodes)
    .randomSource(seededRandom(0x5eed))
    .force(
      "link",
      forceLink<SimNode, SimLink>(links)
        .id((node) => node.id)
        .distance((link) =>
          restLength({ source: "", target: "", kind: link.kind, weight: link.weight }, linkDistance),
        )
        .strength((link) => (link.kind === "similar_to" ? 0.35 : 0.7)),
    )
    .force("charge", forceManyBody<SimNode>().strength(charge).distanceMax(520))
    .force("center", forceCenter(width / 2, height / 2).strength(0.06))
    // Collision uses the drawn radius plus label room, so nodes stop sitting on
    // top of each other's text.
    .force("collide", forceCollide<SimNode>((node) => radiusFor(node) + 14).iterations(2))
    // A weak pull on both axes keeps disconnected components on canvas; nothing
    // else acts on them.
    .force("x", forceX<SimNode>(width / 2).strength(0.045))
    .force("y", forceY<SimNode>(height / 2).strength(0.045))
    .stop();

  return { simulation, nodes: simNodes, links };
}

/**
 * Run a simulation to rest and return clamped positions.
 *
 * Synchronous and bounded, so it is testable and so a server render has something
 * to draw before any JS runs.
 */
export function settle(
  nodes: GraphNode[],
  edges: GraphEdge[],
  options: SimulationOptions & { iterations?: number },
): Positioned[] {
  if (nodes.length === 0) return [];
  const { width, height } = options;

  const only = nodes[0];
  if (nodes.length === 1 && only !== undefined) {
    return [{ ...only, x: width / 2, y: height / 2 }];
  }

  const { simulation, nodes: simNodes } = createSimulation(nodes, edges, options);
  simulation.tick(options.iterations ?? 320);
  simulation.stop();

  const margin = 30;
  return simNodes.map((node) => ({
    ...node,
    x: Math.min(width - margin, Math.max(margin, node.x)),
    y: Math.min(height - margin, Math.max(margin, node.y)),
  }));
}

/**
 * Which nodes a node touches. Used to dim everything else on selection — with a
 * few hundred edges, highlighting the neighbourhood is the only way to see it.
 */
export function neighboursOf(id: string, edges: GraphEdge[]): Set<string> {
  const found = new Set<string>();
  for (const edge of edges) {
    if (edge.source === id) found.add(edge.target);
    else if (edge.target === id) found.add(edge.source);
  }
  return found;
}

/** Stable key for an edge. Similarity is symmetric, so A–B and B–A are one edge. */
export function edgeKey(edge: GraphEdge): string {
  return edge.kind === "similar_to"
    ? `${edge.kind}:${[edge.source, edge.target].sort().join("|")}`
    : `${edge.kind}:${edge.source}|${edge.target}`;
}

/** Resolve a d3 link endpoint, which is a string before the simulation binds it. */
export function endpointId(value: SimNode | string): string {
  return typeof value === "string" ? value : value.id;
}
