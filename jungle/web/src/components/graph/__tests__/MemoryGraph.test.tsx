// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryGraph } from "../MemoryGraph";

/**
 * Selection is the bug these exist for.
 *
 * The previous version implemented panning by calling setPointerCapture on the
 * <svg>. Pointer capture makes the browser dispatch `click` to the capture target
 * rather than to the element under the pointer, so every node click landed on the
 * canvas and the detail panel never populated — a silent failure that looked like
 * missing data rather than a broken handler. d3-zoom distinguishes drag from click
 * itself, and these assert the behaviour rather than the mechanism, so a future
 * change back to manual panning fails here.
 */

const NODES = [
  {
    id: "exchange:x_1",
    kind: "exchange",
    label: "Which database stores metadata?",
    degree: 3,
    meta: {
      project: "brownbear",
      model: "claude-opus-5",
      created_at: "2026-08-01T00:00:00+00:00",
      cacheable: true,
      answer_preview: "PostgreSQL holds VectorAdmin metadata and Brown Bear's own tables.",
    },
  },
  { id: "project:brownbear", kind: "project", label: "brownbear", degree: 1, meta: {} },
  { id: "model:claude-opus-5", kind: "model", label: "claude-opus-5", degree: 1, meta: {} },
  // The far end of the similarity edge. Without it that edge is correctly
  // filtered out — an edge to an absent node would draw a line to nowhere.
  { id: "exchange:x_2", kind: "exchange", label: "Where does metadata live?", degree: 1, meta: {} },
];

const EDGES = [
  { source: "exchange:x_1", target: "project:brownbear", kind: "belongs_to", weight: null },
  { source: "exchange:x_1", target: "model:claude-opus-5", kind: "answered_by", weight: null },
  { source: "exchange:x_1", target: "exchange:x_2", kind: "similar_to", weight: 0.6904 },
];

const PAYLOAD = { nodes: NODES, edges: EDGES.slice(0, 2), truncated: false };

function nodeHandle(name: RegExp) {
  return screen.getByRole("button", { name });
}

beforeEach(() => {
  // Expansion fires on selection; it must not reach the network in a unit test.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => ({ nodes: [], edges: [], truncated: false }) })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("selecting a node", () => {
  it("shows the node's stored fields in the detail panel", () => {
    render(<MemoryGraph initial={PAYLOAD} />);
    const panel = screen.getByLabelText("Detail");

    expect(within(panel).getByText(/Select a node or a connection/)).toBeTruthy();

    fireEvent.click(nodeHandle(/Which database stores metadata/));

    expect(within(panel).getByText("Exchange (a memory)")).toBeTruthy();
    expect(within(panel).getByText("brownbear")).toBeTruthy();
    expect(within(panel).getByText("claude-opus-5")).toBeTruthy();
  });

  it("renders the stored answer as a block, not a one-line field", () => {
    // The whole point of clicking a memory is reading what was remembered.
    render(<MemoryGraph initial={PAYLOAD} />);
    fireEvent.click(nodeHandle(/Which database stores metadata/));
    const panel = screen.getByLabelText("Detail");

    expect(within(panel).getByText("Stored answer")).toBeTruthy();
    expect(within(panel).getByText(/PostgreSQL holds VectorAdmin metadata/)).toBeTruthy();
  });

  it("reports how many things the node connects to", () => {
    render(<MemoryGraph initial={PAYLOAD} />);
    fireEvent.click(nodeHandle(/Which database stores metadata/));
    const panel = screen.getByLabelText("Detail");

    expect(within(panel).getByText("connections")).toBeTruthy();
    expect(within(panel).getByText("2")).toBeTruthy();
  });

  it("asks the gateway to expand the node it selected", () => {
    render(<MemoryGraph initial={PAYLOAD} />);
    fireEvent.click(nodeHandle(/Which database stores metadata/));

    expect(fetch).toHaveBeenCalledWith(
      "/api/graph/node?id=exchange%3Ax_1",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("is reachable by keyboard", () => {
    render(<MemoryGraph initial={PAYLOAD} />);
    fireEvent.keyDown(nodeHandle(/^Project: brownbear$/), { key: "Enter" });

    expect(within(screen.getByLabelText("Detail")).getByText("Project")).toBeTruthy();
  });

  it("marks the selected node pressed", () => {
    render(<MemoryGraph initial={PAYLOAD} />);
    const handle = nodeHandle(/^Project: brownbear$/);
    expect(handle.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(handle);
    expect(handle.getAttribute("aria-pressed")).toBe("true");
  });
});

describe("selecting an edge", () => {
  it("shows a similarity score for a computed relation", () => {
    render(<MemoryGraph initial={{ ...PAYLOAD, edges: EDGES }} />);
    // The clickable target is the wide transparent line beneath each edge.
    const hits = document.querySelectorAll('line[stroke="transparent"]');
    expect(hits.length).toBe(3);

    fireEvent.click(hits[2]!);
    const panel = screen.getByLabelText("Detail");

    expect(within(panel).getByText("Connection")).toBeTruthy();
    expect(within(panel).getByText("resembles")).toBeTruthy();
    expect(within(panel).getByText("0.6904")).toBeTruthy();
  });

  it("distinguishes a recorded fact from a computed score", () => {
    render(<MemoryGraph initial={{ ...PAYLOAD, edges: EDGES }} />);
    const hits = document.querySelectorAll('line[stroke="transparent"]');

    fireEvent.click(hits[0]!);
    const panel = screen.getByLabelText("Detail");

    expect(within(panel).getByText("belongs to")).toBeTruthy();
    expect(within(panel).getByText(/Recorded fact, not a computed score/)).toBeTruthy();
  });

  it("does not expand anything — an edge is not a node", () => {
    render(<MemoryGraph initial={{ ...PAYLOAD, edges: EDGES }} />);
    const hits = document.querySelectorAll('line[stroke="transparent"]');

    fireEvent.click(hits[0]!);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("clearing selection", () => {
  it("returns to the prompt when the background is clicked", () => {
    render(<MemoryGraph initial={PAYLOAD} />);
    fireEvent.click(nodeHandle(/Which database stores metadata/));
    const panel = screen.getByLabelText("Detail");
    expect(within(panel).queryByText(/Select a node or a connection/)).toBeNull();

    fireEvent.click(screen.getByRole("application"));

    expect(within(panel).getByText(/Select a node or a connection/)).toBeTruthy();
  });
});

describe("the legend filter", () => {
  it("removes a whole kind from the canvas", () => {
    render(<MemoryGraph initial={PAYLOAD} />);
    expect(nodeHandle(/^Model: claude-opus-5$/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^Model \(1\)$/ }));

    expect(screen.queryByRole("button", { name: /^Model: claude-opus-5$/ })).toBeNull();
  });
});
