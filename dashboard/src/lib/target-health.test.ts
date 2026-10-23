import { describe, expect, it } from "vitest";

import { liveFixture, targetFixture } from "@/test/fixtures";

import { fullQuotas, targetHealth } from "./target-health";

describe("fullQuotas", () => {
  it("names the quotas used up, never those without a limit", () => {
    expect(fullQuotas(liveFixture())).toEqual([]);
    expect(
      fullQuotas(
        liveFixture({
          rpm: { used: 30, limit: 30 },
          tpm: { used: 9000, limit: null },
          rpd: { used: 1000, limit: 1000, resets_at: "2026-10-24T00:00:00Z" },
        }),
      ),
    ).toEqual(["RPM", "RPD"]);
  });
});

describe("targetHealth", () => {
  it("is healthy when nothing keeps traffic away", () => {
    expect(targetHealth(targetFixture())).toEqual(["healthy"]);
  });

  it("lists every reason, most blocking first", () => {
    const target = targetFixture({
      live: liveFixture({
        cooldown: { active: true, until: "2026-10-23T12:01:00Z" },
        breaker: { state: "open", open_until: null, trial_running: false },
        tpm: { used: 8000, limit: 8000 },
      }),
    });

    expect(targetHealth(target)).toEqual([
      "cooling_down",
      "breaker_open",
      "quota_full",
    ]);
  });

  it("does not guess when the live state is unknown or the target removed", () => {
    expect(
      targetHealth(targetFixture({ live: liveFixture({ status: "unknown" }) })),
    ).toEqual(["live_unknown"]);
    expect(
      targetHealth(targetFixture({ configured: false, live: null })),
    ).toEqual(["removed"]);
  });
});
