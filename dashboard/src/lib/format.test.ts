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
  noValue,
} from "./format";

// French typography of `Intl` (fr-FR): a narrow no-break space groups the
// thousands, a no-break space comes before `%`, `$` and units.
const NNBSP = " ";
const NBSP = " ";

describe("formatMoney", () => {
  it("formats dollars with two decimals and separators", () => {
    expect(formatMoney("en", 1234.5)).toBe("$1,234.50");
    expect(formatMoney("en", 0)).toBe("$0.00");
    expect(formatMoney("fr", 1234.5)).toBe(`1${NNBSP}234,50${NBSP}$`);
    expect(formatMoney("fr", 0)).toBe(`0,00${NBSP}$`);
  });

  it("keeps the significant decimals of amounts below one cent", () => {
    expect(formatMoney("en", 0.0012)).toBe("$0.0012");
    expect(formatMoney("en", 0.000004)).toBe("$0.000004");
    expect(formatMoney("en", 0.0000001)).toBe("< $0.000001");
    expect(formatMoney("fr", 0.0012)).toBe(`0,0012${NBSP}$`);
    expect(formatMoney("fr", 0.0000001)).toBe(`<${NBSP}0,000001${NBSP}$`);
  });

  it("says unknown when there is no price, never $0.00", () => {
    expect(formatMoney("en", null)).toBe("unknown");
    expect(formatMoney("en", undefined)).toBe("unknown");
    expect(formatMoney("fr", null)).toBe("inconnu");
  });
});

describe("formatMoneyTick", () => {
  it("keeps three significant digits, so close ticks stay distinct", () => {
    expect(formatMoneyTick("en", 0)).toBe("$0");
    expect(formatMoneyTick("en", 0.015)).toBe("$0.015");
    expect(formatMoneyTick("en", 0.02)).toBe("$0.02");
    expect(formatMoneyTick("en", 1.25)).toBe("$1.25");
    expect(formatMoneyTick("fr", 0)).toBe(`0${NBSP}$`);
    expect(formatMoneyTick("fr", 0.015)).toBe(`0,015${NBSP}$`);
  });
});

describe("formatRate", () => {
  it("formats a share as a percentage with at most one decimal", () => {
    expect(formatRate("en", 0)).toBe("0%");
    expect(formatRate("en", 0.125)).toBe("12.5%");
    expect(formatRate("en", 1 / 3)).toBe("33.3%");
    expect(formatRate("en", 1)).toBe("100%");
  });

  it("puts a no-break space before % in French", () => {
    expect(formatRate("fr", 0.125)).toBe(`12,5${NBSP}%`);
  });
});

describe("formatDuration", () => {
  it("uses milliseconds below one second", () => {
    expect(formatDuration("en", 0)).toBe("0 ms");
    expect(formatDuration("en", 849.6)).toBe("850 ms");
    expect(formatDuration("fr", 849.6)).toBe(`850${NBSP}ms`);
  });

  it("uses seconds with one decimal below one minute", () => {
    expect(formatDuration("en", 2140)).toBe("2.1 s");
    expect(formatDuration("en", 2000)).toBe("2.0 s");
    expect(formatDuration("fr", 2140)).toBe(`2,1${NBSP}s`);
  });

  it("uses minutes and seconds above one minute", () => {
    expect(formatDuration("en", 65_000)).toBe("1 min 5 s");
    expect(formatDuration("en", 120_000)).toBe("2 min");
    expect(formatDuration("fr", 65_000)).toBe(`1${NBSP}min 5${NBSP}s`);
  });

  it("says n/a when nothing was measured", () => {
    expect(formatDuration("en", null)).toBe("n/a");
    expect(formatDuration("fr", null)).toBe("n.d.");
  });
});

describe("formatCount", () => {
  it("adds thousands separators", () => {
    expect(formatCount("en", 1234567)).toBe("1,234,567");
    expect(formatCount("fr", 1234567)).toBe(`1${NNBSP}234${NNBSP}567`);
    expect(formatCount("fr", 1250.5)).toBe(`1${NNBSP}250,5`);
  });
});

describe("formatAge", () => {
  it("counts seconds, then minutes, then hours", () => {
    expect(formatAge("en", 0)).toBe("0 s ago");
    expect(formatAge("en", 9.8)).toBe("9 s ago");
    expect(formatAge("en", 125)).toBe("2 min ago");
    expect(formatAge("en", 7300)).toBe("2 h ago");
  });

  it("says il y a in French", () => {
    expect(formatAge("fr", 9.8)).toBe(`il y a 9${NBSP}s`);
    expect(formatAge("fr", 7300)).toBe(`il y a 2${NBSP}h`);
  });

  it("never goes below zero when the clocks differ", () => {
    expect(formatAge("en", -3)).toBe("0 s ago");
  });
});

describe("formatDateTime", () => {
  it("shows a UTC moment in the given time zone", () => {
    const utc = "2026-10-23T13:05:00Z";

    expect(formatDateTime("en", utc, "UTC")).toBe("Oct 23, 2026, 13:05");
    expect(formatDateTime("en", utc, "Africa/Douala")).toBe(
      "Oct 23, 2026, 14:05",
    );
    expect(formatDateTime("en", utc, "America/Los_Angeles")).toBe(
      "Oct 23, 2026, 06:05",
    );
  });

  it("writes the date the French way", () => {
    expect(
      formatDateTime("fr", "2026-10-23T13:05:00Z", "Africa/Douala"),
    ).toMatch(/^23 oct\. 2026.* 14:05$/);
  });

  it("changes the day when the time zone does", () => {
    expect(formatDateTime("en", "2026-10-23T23:30:00Z", "Africa/Douala")).toBe(
      "Oct 24, 2026, 00:30",
    );
  });

  it("adds the seconds when asked", () => {
    expect(
      formatDateTime("en", "2026-10-23T13:05:09Z", "UTC", { seconds: true }),
    ).toBe("Oct 23, 2026, 13:05:09");
    expect(
      formatDateTime("fr", "2026-10-23T13:05:09Z", "UTC", { seconds: true }),
    ).toMatch(/13:05:09$/);
  });
});

describe("formatQuota", () => {
  it("shows the use against the limit", () => {
    expect(formatQuota("en", 12, 30)).toBe("12 / 30");
    expect(formatQuota("en", 1500, 8000)).toBe("1,500 / 8,000");
    expect(formatQuota("fr", 1500, 8000)).toBe(`1${NNBSP}500 / 8${NNBSP}000`);
  });

  it("says when there is no limit, or when the use is unknown", () => {
    expect(formatQuota("en", null, null)).toBe("no limit");
    expect(formatQuota("en", null, 30)).toBe("unknown / 30");
    expect(formatQuota("fr", null, null)).toBe("sans limite");
    expect(formatQuota("fr", null, 30)).toBe("inconnu / 30");
  });
});

describe("formatSimilarity", () => {
  it("keeps up to three decimals", () => {
    expect(formatSimilarity("en", 0.97345)).toBe("0.973");
    expect(formatSimilarity("en", 1)).toBe("1");
    expect(formatSimilarity("en", null)).toBe("n/a");
    expect(formatSimilarity("fr", 0.97345)).toBe("0,973");
  });
});

describe("noValue", () => {
  it("says the value is missing in each language", () => {
    expect(noValue("en")).toBe("n/a");
    expect(noValue("fr")).toBe("n.d.");
  });
});

describe("formatBucket", () => {
  it("shows the hour in the given time zone for a 24h period", () => {
    expect(
      formatBucket("en", "2026-10-23T13:00:00Z", "24h", "Africa/Douala"),
    ).toBe("14:00");
    expect(
      formatBucket("fr", "2026-10-23T13:00:00Z", "24h", "Africa/Douala"),
    ).toBe("14:00");
  });

  it("shows the UTC day for longer periods, whatever the time zone", () => {
    expect(
      formatBucket("en", "2026-10-21T00:00:00Z", "7d", "America/Los_Angeles"),
    ).toBe("Oct 21");
    expect(
      formatBucket("en", "2026-10-21T00:00:00Z", "30d", "Asia/Tokyo"),
    ).toBe("Oct 21");
    expect(
      formatBucket("fr", "2026-10-21T00:00:00Z", "7d", "America/Los_Angeles"),
    ).toBe("21 oct.");
  });
});
