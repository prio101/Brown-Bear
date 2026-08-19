import { describe, expect, it } from "vitest";

import { reportingHealth } from "../reporting";

/**
 * BB-205. The incident these exist for: usage reporting was rejected at the edge
 * for eighteen hours, every token number sat at zero, and the dashboard showed
 * healthy — because the only liveness signal on the page measured a collector
 * that was running perfectly well inside the container.
 *
 * So what is asserted is the *distinction*: a quiet day and a dead feed must not
 * produce the same output, and "never reported" must not look like either.
 */

const NOW = new Date("2026-08-19T08:48:00Z");

const summary = (overrides: Partial<Parameters<typeof reportingHealth>[0]> = {}) => ({
  last_event_at: new Date("2026-08-19T08:30:00Z"),
  last_event_source: "remote_api",
  stale_after_hours: 24,
  ...overrides,
});

describe("reportingHealth", () => {
  it("is healthy while reports keep arriving", () => {
    const health = reportingHealth(summary(), NOW);

    expect(health.state).toBe("healthy");
    expect(health.affected).toBe("");
    // Healthy still carries the age: the note is what makes a zero readable, and
    // a zero is just as unreadable on a healthy day.
    expect(health.note).toContain("18 min ago");
  });

  it("goes stale once nothing has arrived for longer than the declared window", () => {
    const health = reportingHealth(
      summary({ last_event_at: new Date("2026-08-18T02:00:00Z") }),
      NOW,
    );

    expect(health.state).toBe("stale");
    expect(health.affected).toContain("24h");
  });

  it("carries the incident's own silence in the note, below the banner's threshold", () => {
    // The real failure ran ~18h: inside a 24h window, so the banner stays quiet
    // and the NOTE is what makes it visible. That is the deliberate split — the
    // banner is for silence long enough to be suspicious on its own, the note is
    // for every zero, and a threshold tight enough to fire overnight would be
    // ignored by the second week.
    const health = reportingHealth(
      summary({ last_event_at: new Date("2026-08-18T15:01:00Z") }),
      NOW,
    );

    expect(health.state).toBe("healthy");
    expect(health.note).toBe("Last report 17 hours ago from remote_api.");
  });

  it("says look rather than broken, because a quiet weekend produces this too", () => {
    const health = reportingHealth(
      summary({ last_event_at: new Date("2026-08-01T00:00:00Z") }),
      NOW,
    );

    expect(health.affected).toContain("either nobody has run a prompt");
    // And the one next step names where the silence is actually produced.
    expect(health.nextStep).toContain("/ext/exchange");
  });

  it("treats never-reported as its own state, not as stale", () => {
    const health = reportingHealth(
      summary({ last_event_at: null, last_event_source: null }),
      NOW,
    );

    expect(health.state).toBe("unknown");
    expect(health.lastWorked).toBeNull();
    expect(health.note).toBe("No usage has ever been reported.");
  });

  it("honours the server's window rather than a threshold of its own", () => {
    const stale = new Date("2026-08-19T06:00:00Z"); // not quite 3h before NOW

    expect(reportingHealth(summary({ last_event_at: stale, stale_after_hours: 24 }), NOW).state)
      .toBe("healthy");
    expect(reportingHealth(summary({ last_event_at: stale, stale_after_hours: 1 }), NOW).state)
      .toBe("stale");
  });

  it("names where the last report came from, so a local proxy is not mistaken for a hook", () => {
    const health = reportingHealth(summary({ last_event_source: "local_ollama" }), NOW);

    expect(health.note).toContain("local_ollama");
  });
});
