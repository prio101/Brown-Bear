/**
 * @vitest-environment happy-dom
 */

/**
 * Realtime updates (BB-203).
 *
 * The bug was a value that should change and did not: `relativeAge()` ran once
 * server-side and its string was baked into the HTML, so a badge kept asserting
 * "just now" about data that was minutes old. A test that proves the age
 * *advances* is therefore the point of this file — asserting the initial render
 * would have passed against the bug.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { act } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AutoRefresh,
  DEFAULT_REFRESH_MS,
  SERVER_SAMPLE_INTERVAL_MS,
  STORAGE_KEY,
} from "../AutoRefresh";
import { RelativeTime } from "../RelativeTime";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

beforeEach(() => {
  vi.useFakeTimers();
  refresh.mockClear();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  // Not optional: the hidden-tab test spies on document.visibilityState, and
  // without a restore every later test silently runs against a hidden tab.
  vi.restoreAllMocks();
});

describe("RelativeTime", () => {
  it("advances instead of freezing — the actual bug", async () => {
    const start = new Date("2026-08-06T12:00:00Z");
    vi.setSystemTime(start);

    render(<RelativeTime iso={start.toISOString()} initial="just now" />);
    expect(screen.getByText("just now")).toBeDefined();

    // Five minutes pass with the page open and untouched.
    await act(async () => {
      vi.setSystemTime(new Date("2026-08-06T12:05:00Z"));
      vi.advanceTimersByTime(20_000);
    });

    expect(screen.getByText("5 min ago")).toBeDefined();
    expect(screen.queryByText("just now")).toBeNull();
  });

  it("emits the server string verbatim in the server markup", () => {
    // Asserted against renderToStaticMarkup rather than render(), because
    // testing-library flushes effects on mount and the timer has already
    // corrected the label by the time an assertion could see it. The server
    // markup is the thing hydration compares against, so it is also the thing
    // that has to match: computing on the client during render would use a
    // different clock and React would warn about a mismatch.
    vi.setSystemTime(new Date("2026-08-06T12:00:00Z"));

    const markup = renderToStaticMarkup(
      <RelativeTime iso="2026-08-06T11:00:00Z" initial="server said this" />,
    );

    expect(markup).toBe("server said this");
    // Emphatically not the client-computed value.
    expect(markup).not.toContain("1 hour ago");
  });

  it("keeps ticking across an hour boundary", async () => {
    const start = new Date("2026-08-06T12:00:00Z");
    vi.setSystemTime(start);
    render(<RelativeTime iso={start.toISOString()} initial="just now" />);

    await act(async () => {
      vi.setSystemTime(new Date("2026-08-06T13:30:00Z"));
      vi.advanceTimersByTime(20_000);
    });

    expect(screen.getByText("1 hour ago")).toBeDefined();
  });

  it("stops its timer on unmount", async () => {
    const spy = vi.spyOn(globalThis, "clearInterval");
    const { unmount } = render(<RelativeTime iso={new Date().toISOString()} initial="just now" />);

    unmount();

    expect(spy).toHaveBeenCalled();
  });
});

describe("AutoRefresh", () => {
  const renderedAt = "2026-08-06T12:00:00Z";

  it("does not refresh faster than the server samples", () => {
    // Polling faster than the data can change surfaces nothing new and only adds
    // load to a box that is also running a model server.
    expect(DEFAULT_REFRESH_MS).toBeGreaterThanOrEqual(SERVER_SAMPLE_INTERVAL_MS);
  });

  it("refreshes on the interval", async () => {
    vi.setSystemTime(new Date(renderedAt));
    render(<AutoRefresh renderedAt={renderedAt} intervalMs={1000} />);

    await act(async () => {
      vi.advanceTimersByTime(3_500);
    });

    expect(refresh).toHaveBeenCalledTimes(3);
  });

  it("does not refresh a hidden tab", async () => {
    vi.setSystemTime(new Date(renderedAt));
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");

    render(<AutoRefresh renderedAt={renderedAt} intervalMs={1000} />);
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });

    expect(refresh).not.toHaveBeenCalled();
  });

  it("honours a stored pause preference and stops refreshing", async () => {
    localStorage.setItem(STORAGE_KEY, "true");
    vi.setSystemTime(new Date(renderedAt));

    render(<AutoRefresh renderedAt={renderedAt} intervalMs={1000} />);
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });

    expect(refresh).not.toHaveBeenCalled();
    // Paused must be visible, not silent: a frozen page that looks live is the
    // failure this whole ticket is about.
    expect(screen.getByText(/Paused/)).toBeDefined();
  });

  it("offers a manual refresh even while paused", async () => {
    localStorage.setItem(STORAGE_KEY, "true");
    render(<AutoRefresh renderedAt={renderedAt} intervalMs={1000} />);

    await act(async () => {
      screen.getByRole("button", { name: /Refresh now/ }).click();
    });

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("survives localStorage being unavailable", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.setSystemTime(new Date(renderedAt));

    render(<AutoRefresh renderedAt={renderedAt} intervalMs={1000} />);
    await act(async () => {
      vi.advanceTimersByTime(2_000);
    });

    // Refreshing on is the safe default for an operations dashboard.
    expect(refresh).toHaveBeenCalled();
  });
});
