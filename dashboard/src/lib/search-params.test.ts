import { describe, expect, it } from "vitest";

import { parsePeriod, parseTenant } from "./period";
import { overviewHref, withSearchParam } from "./search-params";

describe("withSearchParam", () => {
  it("sets a param and keeps the others", () => {
    expect(withSearchParam("period=7d&tenant=acme", "period", "30d")).toBe(
      "?period=30d&tenant=acme",
    );
  });

  it("removes a param set to null or empty", () => {
    expect(withSearchParam("period=7d&tenant=acme", "tenant", null)).toBe(
      "?period=7d",
    );
    expect(withSearchParam("tenant=acme", "tenant", "")).toBe("");
  });
});

describe("overviewHref", () => {
  it("links to the overview of a period and a tenant", () => {
    expect(overviewHref("7d", "acme & co")).toBe(
      "/?period=7d&tenant=acme+%26+co",
    );
    expect(overviewHref("24h", null)).toBe("/?period=24h");
  });
});

describe("parsePeriod", () => {
  it("reads a known period", () => {
    expect(parsePeriod("7d")).toBe("7d");
    expect(parsePeriod(["30d", "7d"])).toBe("30d");
  });

  it("falls back to 24h when the period is missing or unknown", () => {
    expect(parsePeriod(undefined)).toBe("24h");
    expect(parsePeriod("1y")).toBe("24h");
  });
});

describe("parseTenant", () => {
  it("reads a tenant name, or null for every tenant", () => {
    expect(parseTenant("acme")).toBe("acme");
    expect(parseTenant(undefined)).toBeNull();
    expect(parseTenant("")).toBeNull();
  });
});
