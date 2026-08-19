// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentConfigBrowser } from "@/components/AgentConfigBrowser";
import type { AgentConfig, AgentInventory, AgentRevision } from "@/lib/api/schemas";

/**
 * Agent configuration browser (spec 008 §8.5).
 *
 * These pin the two states that are easy to render as a lie: a file whose content
 * was deliberately not kept must not look like an empty file, and a file that has
 * been removed from its machine must not look current. Both would be silent.
 */

function config(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    config_id: "a_1",
    machine: "laptop",
    scope: "project",
    project: "brownbear",
    label: "brownbear",
    tool: "claude",
    path: "settings.json",
    sha256: "a".repeat(64),
    size_bytes: 128,
    content_kind: "text",
    redactions: 0,
    status: "synced",
    revision: 1,
    first_seen_at: "2026-08-18T09:00:00+00:00",
    last_synced_at: "2026-08-18T09:00:00+00:00",
    changed_at: "2026-08-18T09:00:00+00:00",
    removed_at: null,
    ...overrides,
  };
}

function inventory(overrides: Partial<AgentInventory> = {}): AgentInventory {
  return {
    machines: [
      {
        machine: "laptop",
        files: 3,
        bytes: 300,
        removed: 0,
        redactions: 1,
        last_synced_at: "2026-08-18T09:00:00+00:00",
        scopes: [
          {
            scope: "global",
            project: "",
            label: "Global",
            files: 1,
            bytes: 100,
            tools: [
              {
                tool: "claude",
                files: 1,
                bytes: 100,
                removed: 0,
                redactions: 1,
                last_synced_at: "2026-08-18T09:00:00+00:00",
                changed_at: "2026-08-18T09:00:00+00:00",
              },
            ],
          },
          {
            scope: "project",
            project: "brownbear",
            label: "brownbear",
            files: 2,
            bytes: 200,
            tools: [
              {
                tool: "claude",
                files: 2,
                bytes: 200,
                removed: 0,
                redactions: 0,
                last_synced_at: "2026-08-18T09:00:00+00:00",
                changed_at: "2026-08-18T09:00:00+00:00",
              },
            ],
          },
        ],
      },
    ],
    totals: { machines: 1, files: 3, bytes: 300, removed: 0, redactions: 1 },
    tools: ["claude", "qwen"],
    stale_after_hours: 24,
    ...overrides,
  };
}

const SELECTION = { machine: "laptop", scope: "global", project: "", tool: "claude" };

function revision(overrides: Partial<AgentRevision> = {}): AgentRevision {
  return {
    config_id: "a_1",
    revision: 2,
    sha256: "a".repeat(64),
    size_bytes: 128,
    content_kind: "text",
    redactions: 0,
    created_at: "2026-08-19T09:00:00+00:00",
    replaced_at: null,
    current: true,
    restorable: true,
    reason: null,
    ...overrides,
  };
}

/** The component makes three different calls; route by URL so a test can say what
 * each one returns without caring about their order. */
function stubFetch(detail: AgentConfig, revisions: AgentRevision[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/revisions/")) {
        const number = Number(url.split("/revisions/")[1]);
        const found = revisions.find((r) => r.revision === number);
        return { ok: Boolean(found), json: async () => found };
      }
      if (url.endsWith("/revisions")) {
        return { ok: true, json: async () => ({ revisions, kept: 10 }) };
      }
      return { ok: true, json: async () => detail };
    }),
  );
}

beforeEach(() => {
  stubFetch(config({ content: '{"model": "claude-opus-5"}' }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the address is the navigation", () => {
  it("names all three levels", () => {
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[config()]}
        initialSelection={SELECTION}
      />,
    );
    expect(screen.getByText("Machine")).toBeTruthy();
    expect(screen.getByText("Global / project")).toBeTruthy();
    expect(screen.getByText("Tool")).toBeTruthy();
  });

  it("offers the machine's scopes with Global labelled as such", () => {
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[config()]}
        initialSelection={SELECTION}
      />,
    );
    expect(screen.getByText("Global")).toBeTruthy();
    expect(screen.getByText("brownbear")).toBeTruthy();
  });
});

describe("content that was deliberately not kept", () => {
  it("explains a binary file instead of showing an empty pane", async () => {
    stubFetch(config({ content_kind: "binary", content: null }));
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[config({ content_kind: "binary" })]}
        initialSelection={SELECTION}
      />,
    );
    await waitFor(() => expect(screen.getByText(/Not UTF-8/)).toBeTruthy());
  });

  it("says an oversized file was not truncated", async () => {
    stubFetch(config({ content_kind: "too_large", content: null }));
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[config({ content_kind: "too_large" })]}
        initialSelection={SELECTION}
      />,
    );
    await waitFor(() => expect(screen.getByText(/not truncated/)).toBeTruthy());
  });
});

describe("what the reader is not seeing", () => {
  it("states the masked count and that the original was never stored", async () => {
    stubFetch(config({ redactions: 2, content: '{"apiKey": "«redacted»"}' }));
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[config({ redactions: 2 })]}
        initialSelection={SELECTION}
      />,
    );
    await waitFor(() => expect(screen.getByText(/never stored/)).toBeTruthy());
    expect(screen.getByText(/2 values replaced/)).toBeTruthy();
  });

  it("marks a file that is no longer on the machine", async () => {
    const removed = config({ status: "removed", removed_at: "2026-08-18T10:00:00+00:00" });
    stubFetch(removed);
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[removed]}
        initialSelection={SELECTION}
      />,
    );
    expect(screen.getByText("Removed")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByText(/no longer on the machine/)).toBeTruthy(),
    );
  });
});

describe("empty is not broken", () => {
  it("names the command that would populate it", () => {
    render(
      <AgentConfigBrowser
        inventory={inventory({ machines: [], totals: { machines: 0, files: 0, bytes: 0, removed: 0, redactions: 0 } })}
        initial={[]}
        initialSelection={null}
      />,
    );
    expect(screen.getByText(/No machine has synced/)).toBeTruthy();
    expect(screen.getByText("python3 bb_sync.py")).toBeTruthy();
  });

  it("distinguishes an empty branch from a failure", () => {
    render(
      <AgentConfigBrowser inventory={inventory()} initial={[]} initialSelection={SELECTION} />,
    );
    expect(screen.getByText(/empty branch, not a/)).toBeTruthy();
  });
});


describe("revision history", () => {
  it("lists what is kept, and says how many the server keeps", async () => {
    stubFetch(config({ revision: 2, content: "current" }), [
      revision({ revision: 2, current: true }),
      revision({ revision: 1, current: false, replaced_at: "2026-08-19T09:00:00+00:00" }),
    ]);
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[config({ revision: 2 })]}
        initialSelection={SELECTION}
      />,
    );

    await waitFor(() => expect(screen.getByText(/History — 2 of the last 10 kept/)).toBeTruthy());
    const list = screen.getByLabelText("Revision history");
    expect(within(list).getByText(/rev 2 · current/)).toBeTruthy();
  });

  it("says which revisions cannot be written back", async () => {
    stubFetch(config({ content: "current" }), [
      revision({ revision: 2, current: true }),
      revision({ revision: 1, current: false, redactions: 1, restorable: false,
                 reason: "1 value(s) were masked before storage" }),
    ]);
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[config()]}
        initialSelection={SELECTION}
      />,
    );

    await waitFor(() => expect(screen.getAllByText(/cannot be restored/).length).toBe(1));
    expect(screen.getAllByText(/can be restored/).length).toBeGreaterThan(0);
  });

  it("never shows a past revision as though it were current", async () => {
    stubFetch(config({ content: "current text" }), [
      revision({ revision: 2, current: true }),
      revision({
        revision: 1,
        current: false,
        replaced_at: "2026-08-19T09:00:00+00:00",
        content: "old text",
      }),
    ]);
    render(
      <AgentConfigBrowser
        inventory={inventory()}
        initial={[config()]}
        initialSelection={SELECTION}
      />,
    );

    const list = await screen.findByLabelText("Revision history");
    fireEvent.click(within(list).getByText(/rev 1/));

    await waitFor(() => expect(screen.getByText("old text")).toBeTruthy());
    expect(screen.getByText(/Revision 1 \(not current\)/)).toBeTruthy();
    expect(screen.getByText(/not what the machine is running/)).toBeTruthy();
  });
});
