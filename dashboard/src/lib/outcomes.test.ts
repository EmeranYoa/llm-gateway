import { describe, expect, it } from "vitest";

import { describeOutcome } from "./outcomes";

describe("describeOutcome", () => {
  it("gives the kind of each outcome", () => {
    const kind = (outcome: string) =>
      describeOutcome({ outcome, latency_ms: 100 }, "en").kind;

    expect(kind("success")).toBe("success");
    expect(kind("cache_hit")).toBe("success");
    expect(kind("rate_limited")).toBe("error");
    expect(kind("timeout")).toBe("error");
    expect(kind("interrupted")).toBe("error");
    expect(kind("skipped_quota")).toBe("skipped");
    expect(kind("invalid_request")).toBe("client_error");
    expect(kind("rejected_tenant_quota")).toBe("client_error");
    expect(kind("cancelled")).toBe("client_error");
  });

  it("tells a too large request skipped by the gateway from one refused by the provider", () => {
    expect(
      describeOutcome({ outcome: "context_too_large", latency_ms: null }, "en"),
    ).toEqual({ kind: "skipped", label: "Too large for this target" });
    expect(
      describeOutcome({ outcome: "context_too_large", latency_ms: 300 }, "en")
        .kind,
    ).toBe("error");
  });

  it("names the outcome in the language of the page", () => {
    expect(
      describeOutcome({ outcome: "rate_limited", latency_ms: 100 }, "fr"),
    ).toEqual({ kind: "error", label: "Limite de débit (429)" });
  });

  it("shows an outcome it does not know as it is", () => {
    expect(
      describeOutcome({ outcome: "something_new", latency_ms: null }, "fr"),
    ).toEqual({ kind: "error", label: "something_new" });
    expect(
      describeOutcome({ outcome: "toString", latency_ms: null }, "en").label,
    ).toBe("toString");
  });
});
