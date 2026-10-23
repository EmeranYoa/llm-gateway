import { describe, expect, it } from "vitest";

import {
  formatAge,
  formatBucket,
  formatCount,
  formatDateTime,
  formatDuration,
  formatMoney,
  formatMoneyTick,
  formatQuota,
  formatRate,
  formatSimilarity,
} from "./format";

describe("formatMoney", () => {
  it("formats dollars with two decimals and separators", () => {
    expect(formatMoney(1234.5)).toBe("$1,234.50");
    expect(formatMoney(0)).toBe("$0.00");
  });

  it("keeps the significant decimals of amounts below one cent", () => {
    expect(formatMoney(0.0012)).toBe("$0.0012");
    expect(formatMoney(0.000004)).toBe("$0.000004");
    expect(formatMoney(0.0000001)).toBe("< $0.000001");
  });

  it("says unknown when there is no price, never $0.00", () => {
    expect(formatMoney(null)).toBe("unknown");
    expect(formatMoney(undefined)).toBe("unknown");
  });
});

describe("formatMoneyTick", () => {
  it("keeps three significant digits, so close ticks stay distinct", () => {
    expect(formatMoneyTick(0)).toBe("$0");
    expect(formatMoneyTick(0.015)).toBe("$0.015");
    expect(formatMoneyTick(0.02)).toBe("$0.02");
    expect(formatMoneyTick(1.25)).toBe("$1.25");
  });
});

describe("formatRate", () => {
  it("formats a share as a percentage with at most one decimal", () => {
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(0.125)).toBe("12.5%");
    expect(formatRate(1 / 3)).toBe("33.3%");
    expect(formatRate(1)).toBe("100%");
  });
});

describe("formatDuration", () => {
  it("uses milliseconds below one second", () => {
    expect(formatDuration(0)).toBe("0 ms");
    expect(formatDuration(849.6)).toBe("850 ms");
  });

  it("uses seconds with one decimal below one minute", () => {
    expect(formatDuration(2140)).toBe("2.1 s");
  });

  it("uses minutes and seconds above one minute", () => {
    expect(formatDuration(65_000)).toBe("1 min 5 s");
    expect(formatDuration(120_000)).toBe("2 min");
  });

  it("says n/a when nothing was measured", () => {
    expect(formatDuration(null)).toBe("n/a");
  });
});

describe("formatCount", () => {
  it("adds thousands separators", () => {
    expect(formatCount(1234567)).toBe("1,234,567");
  });
});

describe("formatAge", () => {
  it("counts seconds, then minutes, then hours", () => {
    expect(formatAge(0)).toBe("0 s ago");
    expect(formatAge(9.8)).toBe("9 s ago");
    expect(formatAge(125)).toBe("2 min ago");
    expect(formatAge(7300)).toBe("2 h ago");
  });

  it("never goes below zero when the clocks differ", () => {
    expect(formatAge(-3)).toBe("0 s ago");
  });
});

describe("formatDateTime", () => {
  it("shows a UTC moment in the given time zone", () => {
    const utc = "2026-10-23T13:05:00Z";

    expect(formatDateTime(utc, "UTC")).toBe("Oct 23, 2026, 13:05");
    expect(formatDateTime(utc, "Africa/Douala")).toBe("Oct 23, 2026, 14:05");
    expect(formatDateTime(utc, "America/Los_Angeles")).toBe(
      "Oct 23, 2026, 06:05",
    );
  });

  it("changes the day when the time zone does", () => {
    expect(formatDateTime("2026-10-23T23:30:00Z", "Africa/Douala")).toBe(
      "Oct 24, 2026, 00:30",
    );
  });

  it("adds the seconds when asked", () => {
    expect(
      formatDateTime("2026-10-23T13:05:09Z", "UTC", { seconds: true }),
    ).toBe("Oct 23, 2026, 13:05:09");
  });
});

describe("formatQuota", () => {
  it("shows the use against the limit", () => {
    expect(formatQuota(12, 30)).toBe("12 / 30");
    expect(formatQuota(1500, 8000)).toBe("1,500 / 8,000");
  });

  it("says when there is no limit, or when the use is unknown", () => {
    expect(formatQuota(null, null)).toBe("no limit");
    expect(formatQuota(null, 30)).toBe("unknown / 30");
  });
});

describe("formatSimilarity", () => {
  it("keeps up to three decimals", () => {
    expect(formatSimilarity(0.97345)).toBe("0.973");
    expect(formatSimilarity(1)).toBe("1");
    expect(formatSimilarity(null)).toBe("n/a");
  });
});

describe("formatBucket", () => {
  it("shows the hour in the given time zone for a 24h period", () => {
    expect(formatBucket("2026-10-23T13:00:00Z", "24h", "Africa/Douala")).toBe(
      "14:00",
    );
  });

  it("shows the UTC day for longer periods, whatever the time zone", () => {
    expect(
      formatBucket("2026-10-21T00:00:00Z", "7d", "America/Los_Angeles"),
    ).toBe("Oct 21");
    expect(formatBucket("2026-10-21T00:00:00Z", "30d", "Asia/Tokyo")).toBe(
      "Oct 21",
    );
  });
});
