import { describe, expect, it } from "vitest";

import type { ApiResult } from "../client";
import { relativeAge, staleness } from "../freshness";
import { toPanelState } from "../panel";
import { PROVENANCE_MARKER, provenanceOf, weakestProvenance } from "../provenance";

const ok = <T>(data: T): ApiResult<T> => ({
  ok: true,
  data,
  fetchedAt: new Date("2026-08-03T16:00:00Z"),
});

const failed: ApiResult<never> = {
  ok: false,
  error: {
    endpoint: "/api/cache",
    kind: "network",
    detail: "unreachable",
    at: new Date("2026-08-03T16:00:00Z"),
  },
};

describe("toPanelState", () => {
  it("distinguishes empty from error — the whole point of the union", () => {
    const empty = toPanelState(ok({ samples: 0 }), (d) => d.samples === 0, "No samples yet");
    const broken = toPanelState(failed, () => false, "unused");

    expect(empty.status).toBe("empty");
    expect(broken.status).toBe("error");
    // An empty panel still knows when it was checked; a broken one carries why.
    if (empty.status === "empty") expect(empty.reason).toBe("No samples yet");
    if (broken.status === "error") expect(broken.error.endpoint).toBe("/api/cache");
  });

  it("reports ready with data and the fetch time", () => {
    const state = toPanelState(ok({ samples: 12 }), (d) => d.samples === 0, "No samples yet");

    expect(state.status).toBe("ready");
    if (state.status !== "ready") return;
    expect(state.data.samples).toBe(12);
    expect(state.fetchedAt).toBeInstanceOf(Date);
  });
});

describe("provenance", () => {
  it("maps the backend's source values to trust kinds", () => {
    expect(provenanceOf("local_ollama")).toBe("measured");
    expect(provenanceOf("remote_api")).toBe("reported");
    expect(provenanceOf("token_events")).toBe("derived");
  });

  it("falls back to derived for an unrecognised source rather than claiming measured", () => {
    expect(provenanceOf("something_new")).toBe("derived");
  });

  it("a mixed total claims only the weakest kind present", () => {
    // Adding a remote client's claim to a local count is only as good as the claim.
    expect(weakestProvenance(["measured", "reported"])).toBe("reported");
    expect(weakestProvenance(["measured", "derived"])).toBe("derived");
    expect(weakestProvenance(["measured"])).toBe("measured");
    expect(weakestProvenance([])).toBe("derived");
  });

  it("gives every kind a marker, so none can render bare", () => {
    for (const kind of ["measured", "reported", "derived"] as const) {
      expect(PROVENANCE_MARKER[kind]).toBeTruthy();
    }
  });
});

describe("freshness", () => {
  const now = new Date("2026-08-03T16:00:00Z");

  it("formats coarsely — seconds on an operations dashboard read as noise", () => {
    expect(relativeAge(new Date("2026-08-03T15:59:30Z"), now)).toBe("just now");
    expect(relativeAge(new Date("2026-08-03T15:58:00Z"), now)).toBe("2 min ago");
    expect(relativeAge(new Date("2026-08-03T15:00:00Z"), now)).toBe("1 hour ago");
    expect(relativeAge(new Date("2026-08-01T16:00:00Z"), now)).toBe("2 days ago");
  });

  it("does not render clock skew as a negative age", () => {
    expect(relativeAge(new Date("2026-08-03T16:00:30Z"), now)).toBe("just now");
  });

  it("grades staleness against the expected sampling interval", () => {
    const interval = 30_000;
    expect(staleness(new Date("2026-08-03T15:59:45Z"), interval, now)).toBe("fresh");
    expect(staleness(new Date("2026-08-03T15:58:00Z"), interval, now)).toBe("stale");
    expect(staleness(new Date("2026-08-03T14:00:00Z"), interval, now)).toBe("very-stale");
  });
});
