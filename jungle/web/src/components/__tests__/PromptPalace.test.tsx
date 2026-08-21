// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PromptPalace } from "@/components/PromptPalace";
import type { Prompt, PromptRelated } from "@/lib/api/schemas";

/**
 * Prompt Palace (spec 012).
 *
 * The assertions worth having are the honesty ones. Every failure mode here is
 * silent — a 0 where a score could not be computed still looks like a score, a
 * hostname invented for an unattributed prompt still looks like attribution, and a
 * failed similarity lookup that blanks the answer looks like an empty answer.
 */

function prompt(overrides: Partial<Prompt> = {}): Prompt {
  return {
    id: "x_one",
    prompt: "how do I rotate the edge token?",
    project: "brownbear",
    model: "claude-opus-5",
    machine: "mac-studio",
    created_at: "2026-08-20T09:00:00+00:00",
    cacheable: true,
    ...overrides,
  };
}

function related(overrides: Partial<PromptRelated> = {}): PromptRelated {
  return {
    id: "x_one",
    prompts: [],
    chunks: [],
    space: "cosine",
    scorable: true,
    threshold: 0.95,
    min_similarity: 0.6,
    ...overrides,
  };
}

/** Routes the two requests a selection makes: the answer, then the neighbours. */
function stubFetch({
  detail,
  neighbours,
  failRelated = false,
}: {
  detail?: Prompt;
  neighbours?: PromptRelated;
  failRelated?: boolean;
}) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      if (url.endsWith("/related")) {
        if (failRelated) return { ok: false, status: 503, json: async () => ({}) };
        return { ok: true, json: async () => neighbours ?? related() };
      }
      return { ok: true, json: async () => detail ?? prompt({ response: "an answer" }) };
    }),
  );
  return calls;
}

beforeEach(() => stubFetch({}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("attribution", () => {
  it("names the machine a client claimed", () => {
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);
    expect(screen.getAllByText("mac-studio").length).toBeGreaterThan(0);
  });

  it("says 'not recorded' rather than inventing a machine", () => {
    // The failure this guards: attributing an unattributed prompt to the host that
    // happens to be serving the page. Nothing here knows where it ran.
    render(<PromptPalace initial={[prompt({ machine: null })]} threshold={0.95} scorable />);

    expect(screen.getAllByText("not recorded").length).toBeGreaterThan(0);
    expect(screen.queryByText(/localhost|unknown/i)).toBeNull();
  });

  it("flags a prompt that will never be served from the cache", () => {
    render(<PromptPalace initial={[prompt({ cacheable: false })]} threshold={0.95} scorable />);
    expect(screen.getByText(/not cacheable/)).toBeTruthy();
  });
});

describe("the response", () => {
  it("fetches the answer and the neighbours as two separate requests", async () => {
    // The answer is a row lookup; the neighbours are two vector searches. One
    // combined request would make reading an answer wait on a query.
    const calls = stubFetch({});
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);

    await waitFor(() => expect(calls).toContain("/api/prompts/x_one/related"));
    expect(calls).toContain("/api/prompts/x_one");
  });

  it("shows the answer once it arrives", async () => {
    stubFetch({ detail: prompt({ response: "Edit .env and restart the edge." }) });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);

    expect(await screen.findByText("Edit .env and restart the edge.")).toBeTruthy();
  });

  it("does not call an answer empty before it has loaded", () => {
    // The listing carries no response, so "empty" is not knowable on first paint.
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);
    expect(screen.getByText(/Loading/)).toBeTruthy();
  });
});

describe("scores", () => {
  it("shows every neighbour's score against the cutoff", async () => {
    stubFetch({
      neighbours: related({
        prompts: [prompt({ id: "x_two", prompt: "rotating BB_EDGE_TOKEN", score: 0.91 })],
      }),
    });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);

    expect(await screen.findByText("0.910")).toBeTruthy();
    // The cutoff is stated, not implied: a score with no cutoff beside it is
    // unfalsifiable by the reader.
    expect(screen.getByText(/0\.95/)).toBeTruthy();
  });

  it("marks which neighbour would actually have been served", async () => {
    stubFetch({
      neighbours: related({
        prompts: [
          prompt({ id: "x_two", score: 0.98, would_hit: true }),
          prompt({ id: "x_three", score: 0.97, would_hit: false, cacheable: false }),
        ],
      }),
    });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);

    // One badge, not two: the second is above the cutoff but not cacheable.
    expect(await screen.findByText(/would hit/)).toBeTruthy();
    expect(screen.getAllByText(/would hit/)).toHaveLength(1);
  });

  it("renders an unscoreable similarity as 'cannot be scored', never as zero", async () => {
    // DESIGN-GUIDE Part 3 rule 2. A 0 would assert the two memories are unrelated,
    // which is a claim nobody made — only cosine converts to the cutoff at all.
    stubFetch({
      neighbours: related({
        space: "l2",
        scorable: false,
        prompts: [prompt({ id: "x_two", score: null })],
      }),
    });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable={false} />);

    expect(await screen.findByText("cannot be scored")).toBeTruthy();
    expect(screen.queryByText("0.000")).toBeNull();
    expect(screen.getByText(/not in cosine space/)).toBeTruthy();
  });
});

describe("what a prompt sits near", () => {
  it("keeps prior prompts and knowledge chunks in separate panes", async () => {
    stubFetch({
      neighbours: related({
        prompts: [prompt({ id: "x_two", prompt: "a prior question", score: 0.8 })],
        chunks: [
          {
            id: "c_1",
            score: 0.68,
            source: "REMOTE-SETUP.md",
            project: "brownbear",
            chunk_index: 2,
            chunk_count: 9,
            file_id: "f_abc",
            text: "Set BB_EDGE_TOKEN in .env.",
          },
        ],
      }),
    });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);

    // Prompts pane first; the chunk is not visible until its tab is chosen.
    expect(await screen.findByText("a prior question")).toBeTruthy();
    expect(screen.queryByText(/Set BB_EDGE_TOKEN/)).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: /Knowledge chunks/ }));

    expect(screen.getByText(/Set BB_EDGE_TOKEN/)).toBeTruthy();
    expect(screen.getByText(/REMOTE-SETUP\.md/)).toBeTruthy();
  });

  it("quotes a retrieved passage instead of presenting it as an answer", async () => {
    stubFetch({
      neighbours: related({
        chunks: [
          {
            id: "c_1",
            score: 0.68,
            source: "DESIGN-BOOK.md",
            project: "brownbear",
            chunk_index: 0,
            chunk_count: 3,
            file_id: null,
            text: "a retrieved passage",
          },
        ],
      }),
    });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);
    fireEvent.click(await screen.findByRole("tab", { name: /Knowledge chunks/ }));

    // A <blockquote>, and not a button: it is supporting context, and the visual
    // distinction from an answer is the guardrail rather than decoration.
    const passage = screen.getByText("a retrieved passage");
    expect(passage.tagName).toBe("BLOCKQUOTE");
    expect(screen.getByLabelText("Knowledge chunks").querySelector("button")).toBeNull();
  });

  it("says so plainly when nothing in the corpus resembles the prompt", async () => {
    stubFetch({ neighbours: related({ prompts: [], chunks: [] }) });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);

    expect(await screen.findByText(/Nothing else in the corpus resembles/)).toBeTruthy();
  });

  it("explains itself when a prompt has no vector to compare", async () => {
    stubFetch({
      neighbours: related({ unavailable: "this exchange has no stored embedding, so it cannot be compared" }),
    });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);

    expect(await screen.findByText(/no stored embedding/)).toBeTruthy();
  });

  it("navigates to a neighbour when it is clicked", async () => {
    const calls = stubFetch({
      neighbours: related({ prompts: [prompt({ id: "x_two", prompt: "a prior question", score: 0.8 })] }),
    });
    render(<PromptPalace initial={[prompt(), prompt({ id: "x_two", prompt: "a prior question" })]} threshold={0.95} scorable />);

    fireEvent.click(await screen.findByRole("button", { name: /a prior question/ }));

    await waitFor(() => expect(calls).toContain("/api/prompts/x_two"));
  });
});

describe("independent failure", () => {
  it("keeps the answer when the similarity lookup fails", async () => {
    // Panels fail independently (Part 3 rule 8). A dead vector query must not
    // present as a missing answer.
    stubFetch({ detail: prompt({ response: "the answer survived" }), failRelated: true });
    render(<PromptPalace initial={[prompt()]} threshold={0.95} scorable />);

    expect(await screen.findByText("the answer survived")).toBeTruthy();
    expect(screen.getByText(/response above is unaffected/)).toBeTruthy();
  });
});

describe("empty", () => {
  it("explains how a prompt gets here", () => {
    render(<PromptPalace initial={[]} threshold={0.95} scorable />);
    const note = screen.getByText(/POST \/ext\/exchange/);
    expect(within(note.parentElement!).getByText(/only party that saw the response/)).toBeTruthy();
  });
});
