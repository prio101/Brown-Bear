"use client";

/**
 * The memory graph canvas (BB-301).
 *
 * d3-force drives the layout and d3-zoom drives pan/zoom. The zoom behaviour
 * matters for correctness, not just ergonomics: the previous version called
 * setPointerCapture on the <svg> to implement dragging, which makes the browser
 * dispatch `click` to the capture target rather than to the node under the
 * pointer — so selecting a node silently did nothing. d3-zoom distinguishes a
 * drag from a click itself, so both work.
 *
 * Nodes AND edges are selectable. An edge is the more interesting object here:
 * `similar_to` carries a score, and being able to ask "how related is this,
 * exactly" is most of what a memory graph is for.
 *
 * Node kinds differ by SHAPE as well as colour, and edge kinds by DASH as well as
 * colour, per DESIGN-BOOK.md §2.4 — nothing is distinguishable by hue alone. The
 * canvas is a fixed deep surface rather than a themed one, matching §2.2, where
 * chart surfaces are deliberately not themed.
 */

import { zoom, zoomIdentity, type ZoomTransform } from "d3-zoom";
import { select } from "d3-selection";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  type GraphEdge,
  type GraphNode,
  type SimNode,
  createSimulation,
  edgeKey,
  endpointId,
  neighboursOf,
  radiusFor,
  settle,
} from "./simulation";

export type GraphPayload = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
};

const WIDTH = 1100;
const HEIGHT = 720;

/** Colour AND shape AND a legend label. Never colour alone. */
const KIND_STYLE: Record<string, { colour: string; shape: string; label: string }> = {
  collection: { colour: "#b48cff", shape: "square", label: "Collection" },
  project: { colour: "#3ce68b", shape: "diamond", label: "Project" },
  model: { colour: "#ffb84d", shape: "triangle", label: "Model" },
  source: { colour: "#4db8ff", shape: "rounded", label: "Source document" },
  exchange: { colour: "#ff6b8a", shape: "circle", label: "Exchange (a memory)" },
  chunk: { colour: "#2fe0d0", shape: "ring", label: "Chunk (retrievable)" },
};

const EDGE_LABEL: Record<string, string> = {
  contains: "contains",
  belongs_to: "belongs to",
  answered_by: "answered by",
  derived_from: "derived from",
  similar_to: "resembles",
};

/** Fields worth a full block rather than a one-line definition. */
const PREVIEW_FIELDS = new Set(["answer_preview", "text_preview"]);

function Shape({ node, r, colour }: { node: SimNode; r: number; colour: string }) {
  const shape = KIND_STYLE[node.kind]?.shape ?? "circle";
  const common = { fill: colour, stroke: "#0b0f1a", strokeWidth: 1.5 };

  if (shape === "square") {
    return <rect x={node.x - r} y={node.y - r} width={r * 2} height={r * 2} rx={3} {...common} />;
  }
  if (shape === "rounded") {
    return (
      <rect
        x={node.x - r * 1.25}
        y={node.y - r * 0.82}
        width={r * 2.5}
        height={r * 1.64}
        rx={r * 0.6}
        {...common}
      />
    );
  }
  if (shape === "diamond") {
    return (
      <rect
        x={node.x - r}
        y={node.y - r}
        width={r * 2}
        height={r * 2}
        transform={`rotate(45 ${node.x} ${node.y})`}
        {...common}
      />
    );
  }
  if (shape === "triangle") {
    const h = r * 1.3;
    return (
      <polygon
        points={`${node.x},${node.y - h} ${node.x + h},${node.y + h * 0.78} ${node.x - h},${node.y + h * 0.78}`}
        {...common}
      />
    );
  }
  if (shape === "ring") {
    return <circle cx={node.x} cy={node.y} r={r} fill="#0b0f1a" stroke={colour} strokeWidth={3.5} />;
  }
  return <circle cx={node.x} cy={node.y} r={r} {...common} />;
}

export function MemoryGraph({ initial }: { initial: GraphPayload }) {
  const [nodes, setNodes] = useState<GraphNode[]>(initial.nodes);
  const [edges, setEdges] = useState<GraphEdge[]>(initial.edges);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [expanding, setExpanding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);

  const svgRef = useRef<SVGSVGElement | null>(null);
  // State, not a ref: the array must change identity when the graph changes so a
  // render is guaranteed. Held in a ref, the canvas kept drawing the previous set
  // of nodes until the simulation happened to tick — so hiding a kind appeared to
  // do nothing whenever the layout was already at rest.
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  // Bumped on every tick to repaint. d3 mutates the node objects in place, so
  // nothing is copied per frame.
  const [, setFrame] = useState(0);

  const visibleNodes = useMemo(() => nodes.filter((n) => !hidden.has(n.kind)), [nodes, hidden]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)),
    [edges, visibleIds],
  );

  // The simulation is rebuilt only when the graph itself changes — never on
  // selection, hover or zoom, which would restart the animation on every click.
  useEffect(() => {
    const { simulation, nodes: simNodes } = createSimulation(visibleNodes, visibleEdges, {
      width: WIDTH,
      height: HEIGHT,
    });
    setSimNodes(simNodes);
    simulation.on("tick", () => setFrame((f) => f + 1));
    simulation.alpha(0.9).restart();
    return () => {
      simulation.on("tick", null);
      simulation.stop();
    };
  }, [visibleNodes, visibleEdges]);

  useEffect(() => {
    const element = svgRef.current;
    if (!element) return;
    const behaviour = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 5])
      .on("zoom", (event) => setTransform(event.transform));
    select(element).call(behaviour);
    return () => {
      select(element).on(".zoom", null);
    };
  }, []);

  // A settled layout for the very first paint. The live simulation runs in an
  // effect, which never runs on the server — without this the page would render an
  // empty canvas and only fill in after hydration, losing the server-rendered
  // graph the rest of the dashboard is built to deliver.
  const firstPaint = useMemo(
    () => settle(visibleNodes, visibleEdges, { width: WIDTH, height: HEIGHT, iterations: 140 }),
    [visibleNodes, visibleEdges],
  );

  const positioned: SimNode[] = simNodes.length > 0 ? simNodes : firstPaint;
  const byId = useMemo(() => new Map(positioned.map((n) => [n.id, n])), [positioned]);
  const highlighted = useMemo(
    () => (selectedNode ? neighboursOf(selectedNode, visibleEdges) : null),
    [selectedNode, visibleEdges],
  );

  const expand = useCallback(async (id: string) => {
    setExpanding(id);
    setError(null);
    try {
      const response = await fetch(`/api/graph/node?id=${encodeURIComponent(id)}`, {
        headers: { accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`the gateway returned ${response.status}`);
      const payload = (await response.json()) as GraphPayload;

      // Merge rather than replace: exploring is additive, and replacing would
      // discard the context the reader navigated through to get here.
      setNodes((current) => {
        const seen = new Map(current.map((n) => [n.id, n]));
        for (const node of payload.nodes) {
          const existing = seen.get(node.id);
          // Later payloads carry richer meta for the same node; keep the fuller one.
          if (!existing || Object.keys(node.meta ?? {}).length > Object.keys(existing.meta ?? {}).length) {
            seen.set(node.id, node);
          }
        }
        return [...seen.values()];
      });
      setEdges((current) => {
        const seen = new Map(current.map((e) => [edgeKey(e), e]));
        for (const edge of payload.edges) if (!seen.has(edgeKey(edge))) seen.set(edgeKey(edge), edge);
        return [...seen.values()];
      });
      setExpanded((current) => new Set(current).add(id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setExpanding(null);
    }
  }, []);

  const activateNode = useCallback(
    (id: string) => {
      setSelectedEdge(null);
      setSelectedNode(id);
      if (!expanded.has(id)) void expand(id);
    },
    [expand, expanded],
  );

  const detailNode = selectedNode ? (nodes.find((n) => n.id === selectedNode) ?? null) : null;
  const detailEdge = selectedEdge
    ? (visibleEdges.find((e) => edgeKey(e) === selectedEdge) ?? null)
    : null;
  const kinds = useMemo(() => [...new Set(nodes.map((n) => n.kind))].sort(), [nodes]);

  return (
    <div className="bb-graph-layout">
      <div style={{ display: "grid", gap: "var(--bb-space-3)" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--bb-space-2)" }}>
          {kinds.map((kind) => {
            const style = KIND_STYLE[kind];
            const off = hidden.has(kind);
            const total = nodes.filter((n) => n.kind === kind).length;
            return (
              <button
                key={kind}
                type="button"
                className="bb-interactive bb-graph-chip"
                aria-pressed={!off}
                data-off={off ? "true" : undefined}
                onClick={() =>
                  setHidden((current) => {
                    const next = new Set(current);
                    if (next.has(kind)) next.delete(kind);
                    else next.add(kind);
                    return next;
                  })
                }
              >
                <span
                  aria-hidden="true"
                  className="bb-graph-swatch"
                  style={{
                    background: style?.colour ?? "#8891a5",
                    borderRadius: style?.shape === "circle" || style?.shape === "ring" ? "50%" : 2,
                  }}
                />
                <span className="bb-label-medium">
                  {style?.label ?? kind} ({total}){off ? " — hidden" : ""}
                </span>
              </button>
            );
          })}
        </div>

        <svg
          ref={svgRef}
          className="bb-graph-canvas"
          role="application"
          aria-label="Memory graph. Nodes are collections, projects, models, sources, exchanges and chunks. Click a node or a connection for detail."
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          onClick={() => {
            setSelectedNode(null);
            setSelectedEdge(null);
          }}
        >
          <defs>
            <pattern id="bb-grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1b2338" strokeWidth="1" />
            </pattern>
            <filter id="bb-glow" x="-70%" y="-70%" width="240%" height="240%">
              <feGaussianBlur stdDeviation="3.4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <rect width={WIDTH} height={HEIGHT} fill="#080b14" />
          <rect width={WIDTH} height={HEIGHT} fill="url(#bb-grid)" opacity={0.5} />

          <g transform={transform.toString()}>
            <g>
              {visibleEdges.map((edge) => {
                const a = byId.get(edge.source);
                const b = byId.get(edge.target);
                if (!a || !b) return null;
                const key = edgeKey(edge);
                const semantic = edge.kind === "similar_to";
                const isSelected = key === selectedEdge;
                const touchesSelection =
                  selectedNode !== null &&
                  (edge.source === selectedNode || edge.target === selectedNode);
                const dimmed = (selectedNode !== null && !touchesSelection) || (selectedEdge !== null && !isSelected);

                return (
                  <g key={key}>
                    {/* A wide transparent line under each edge: a 1px stroke is
                        almost impossible to hit with a pointer. */}
                    <line
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      stroke="transparent"
                      strokeWidth={12}
                      style={{ cursor: "pointer" }}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelectedNode(null);
                        setSelectedEdge(key);
                      }}
                    >
                      <title>{`${a.label} — ${EDGE_LABEL[edge.kind] ?? edge.kind} → ${b.label}`}</title>
                    </line>
                    <line
                      x1={a.x}
                      y1={a.y}
                      x2={b.x}
                      y2={b.y}
                      stroke={semantic ? "#2fe0d0" : "#3d4a68"}
                      // Dashed for computed, solid for recorded — legible in greyscale.
                      strokeDasharray={semantic ? "5 4" : undefined}
                      className={semantic ? "bb-edge-semantic" : undefined}
                      strokeWidth={isSelected ? 3.5 : semantic ? 1 + (edge.weight ?? 0.5) * 2 : 1.2}
                      opacity={dimmed ? 0.1 : isSelected || touchesSelection ? 1 : 0.45}
                      filter={isSelected ? "url(#bb-glow)" : undefined}
                      pointerEvents="none"
                    />
                  </g>
                );
              })}
            </g>

            <g>
              {positioned.map((node) => {
                const style = KIND_STYLE[node.kind];
                const r = radiusFor(node);
                const isSelected = node.id === selectedNode;
                const related = highlighted?.has(node.id) ?? false;
                const dimmed =
                  (selectedNode !== null && !isSelected && !related) || selectedEdge !== null;
                const busy = expanding === node.id;

                return (
                  <g
                    key={node.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${style?.label ?? node.kind}: ${node.label}`}
                    aria-pressed={isSelected}
                    onClick={(event) => {
                      event.stopPropagation();
                      activateNode(node.id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        activateNode(node.id);
                      }
                    }}
                    opacity={dimmed ? 0.18 : 1}
                    style={{ cursor: "pointer" }}
                    filter={isSelected || related ? "url(#bb-glow)" : undefined}
                  >
                    {isSelected ? (
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={r + 7}
                        fill="none"
                        stroke={style?.colour ?? "#8891a5"}
                        strokeWidth={2}
                        className="bb-node-pulse"
                      />
                    ) : null}
                    {busy ? (
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={r + 12}
                        fill="none"
                        stroke="#2fe0d0"
                        strokeWidth={1.2}
                        strokeDasharray="4 4"
                        className="bb-node-spin"
                        style={{ transformOrigin: `${node.x}px ${node.y}px` }}
                      />
                    ) : null}
                    <Shape node={node} r={r} colour={style?.colour ?? "#8891a5"} />
                    <title>{`${style?.label ?? node.kind} — ${node.label}`}</title>
                    {/* Labels only where they can be read: every node labelled at
                        this density is an unreadable wall of text. */}
                    {r >= 12 || isSelected ? (
                      <text
                        x={node.x}
                        y={node.y + r + 13}
                        textAnchor="middle"
                        className="bb-node-label"
                        pointerEvents="none"
                      >
                        {node.label.length > 28 ? `${node.label.slice(0, 27)}…` : node.label}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </g>
          </g>
        </svg>

        <div style={{ display: "flex", gap: "var(--bb-space-3)", flexWrap: "wrap", alignItems: "center" }}>
          <span className="bb-body-small" style={{ color: "var(--bb-on-surface-variant)" }}>
            {visibleNodes.length} nodes · {visibleEdges.length} connections · scroll to zoom, drag to
            pan, click a node or a connection
          </span>
          <button
            type="button"
            className="bb-interactive bb-graph-link"
            onClick={() => {
              const element = svgRef.current;
              if (element) select(element).call(zoom<SVGSVGElement, unknown>().transform, zoomIdentity);
              setTransform(zoomIdentity);
            }}
          >
            Reset view
          </button>
          {initial.truncated ? (
            <span className="bb-body-small" style={{ color: "#ffb84d" }}>
              ⚠ Truncated — not every memory is shown.
            </span>
          ) : null}
        </div>
        {error ? (
          <p className="bb-body-small" role="status" style={{ color: "#ff6b8a" }}>
            Could not expand that node: {error}. The graph you can see is still accurate.
          </p>
        ) : null}
      </div>

      <aside aria-label="Detail" className="bb-graph-detail">
        {detailEdge !== null ? (
          <>
            <span className="bb-label-medium bb-graph-detail-kind">Connection</span>
            <p className="bb-body-medium" style={{ margin: "4px 0 0" }}>
              {EDGE_LABEL[detailEdge.kind] ?? detailEdge.kind}
            </p>
            <dl className="bb-graph-dl">
              <Field term="from" value={byId.get(detailEdge.source)?.label ?? detailEdge.source} />
              <Field term="to" value={byId.get(detailEdge.target)?.label ?? detailEdge.target} />
              {detailEdge.weight !== null ? (
                <Field term="similarity" value={detailEdge.weight.toFixed(4)} />
              ) : (
                <Field term="basis" value="Recorded fact, not a computed score" />
              )}
            </dl>
            {detailEdge.kind === "similar_to" ? (
              <p className="bb-body-small bb-graph-note">
                A computed relation, not a stored one. It says these two memories sit
                near each other in vector space — it does not mean either answers the
                other. Only a score above the cache threshold ({"0.95"} by default) lets
                a prior answer actually be served.
              </p>
            ) : null}
          </>
        ) : detailNode !== null ? (
          <>
            <span className="bb-label-medium bb-graph-detail-kind">
              {KIND_STYLE[detailNode.kind]?.label ?? detailNode.kind}
            </span>
            <p className="bb-body-medium" style={{ margin: "4px 0 0", overflowWrap: "anywhere" }}>
              {detailNode.label}
            </p>
            <dl className="bb-graph-dl">
              {Object.entries(detailNode.meta ?? {})
                .filter(
                  ([term, value]) =>
                    !PREVIEW_FIELDS.has(term) && value !== null && value !== undefined && value !== "",
                )
                .map(([term, value]) => (
                  <Field key={term} term={term.replace(/_/g, " ")} value={String(value)} />
                ))}
              <Field term="connections" value={String(highlighted?.size ?? 0)} />
            </dl>

            {Object.entries(detailNode.meta ?? {})
              .filter(([term, value]) => PREVIEW_FIELDS.has(term) && value)
              .map(([term, value]) => (
                <div key={term}>
                  <span className="bb-label-medium bb-graph-detail-kind">
                    {term === "answer_preview" ? "Stored answer" : "Chunk text"}
                  </span>
                  <p className="bb-body-small bb-graph-preview">{String(value)}</p>
                </div>
              ))}

            {expanding === detailNode.id ? (
              <p className="bb-body-small bb-graph-note">Asking the gateway for neighbours…</p>
            ) : null}
          </>
        ) : (
          <p className="bb-body-medium bb-graph-note" style={{ margin: 0 }}>
            Select a node or a connection. Clicking a node also asks the gateway for its
            nearest neighbours — for an exchange or a chunk that includes memories which
            merely <em>resemble</em> it, drawn as dashed lines you can click for the
            score.
          </p>
        )}
      </aside>
    </div>
  );
}

function Field({ term, value }: { term: string; value: string }) {
  return (
    <div className="bb-graph-field">
      <dt className="bb-body-small">{term}</dt>
      <dd className="bb-body-small">{value}</dd>
    </div>
  );
}
