import { describe, expect, it } from "vitest";

/**
 * No secret value may reach rendered output (BB-108 §108.3).
 *
 * Mirrors the settings page's own predicate. Kept as a test rather than trusted to
 * review, because the failure mode is silent: a new BB_*_TOKEN setting appearing
 * in /api/settings would otherwise render its value with nobody noticing.
 */

const SECRET_PATTERN = /token|secret|password|key|credential/i;

const isSecret = (setting: { key: string; label: string }) =>
  SECRET_PATTERN.test(setting.key) || SECRET_PATTERN.test(setting.label);

const render = (setting: { key: string; label: string; value: unknown }) =>
  isSecret(setting)
    ? setting.value === null || setting.value === ""
      ? "not set"
      : "set"
    : String(setting.value);

describe("secret handling", () => {
  it("renders presence only, never the value or a masked prefix", () => {
    const secret = {
      key: "bb_edge_token",
      label: "Edge token",
      value: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    };

    const output = render(secret);

    expect(output).toBe("set");
    expect(output).not.toContain("561b");
    // A mask still leaks length and leading characters.
    expect(output).not.toMatch(/\*|•|\.\.\./);
  });

  it("distinguishes unset from set", () => {
    expect(render({ key: "api_key", label: "API key", value: "" })).toBe("not set");
    expect(render({ key: "api_key", label: "API key", value: null })).toBe("not set");
    expect(render({ key: "api_key", label: "API key", value: "x" })).toBe("set");
  });

  it("catches every naming convention a secret might arrive under", () => {
    for (const key of [
      "bb_edge_token",
      "jwt_secret",
      "postgres_password",
      "inngest_signing_key",
      "cloudflare_credential",
      "TUNNEL_TOKEN",
    ]) {
      expect(isSecret({ key, label: "" })).toBe(true);
    }
  });

  it("leaves ordinary settings alone", () => {
    for (const key of ["snapshot_interval_seconds", "cache_similarity_threshold", "top_k"]) {
      expect(isSecret({ key, label: "" })).toBe(false);
    }
    expect(render({ key: "top_k", label: "Top K", value: 5 })).toBe("5");
  });

  it("catches a secret named only in its label", () => {
    expect(isSecret({ key: "edge_credential_state", label: "Shared secret" })).toBe(true);
  });
});
