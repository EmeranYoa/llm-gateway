import { describe, expect, it } from "vitest";

import {
  parseRequestFilters,
  parseRequestStatus,
  type RequestFilters,
  requestHref,
  requestsHref,
} from "./request-filters";

const ALL: RequestFilters = {
  period: "24h",
  tenant: null,
  alias: null,
  status: null,
};

describe("parseRequestStatus", () => {
  it("reads a known status, or null for every status", () => {
    expect(parseRequestStatus("failed")).toBe("failed");
    expect(parseRequestStatus(["client_error"])).toBe("client_error");
    expect(parseRequestStatus("broken")).toBeNull();
    expect(parseRequestStatus(undefined)).toBeNull();
  });
});

describe("parseRequestFilters", () => {
  it("applies the defaults when the URL has no filter", () => {
    expect(parseRequestFilters({})).toEqual({ filters: ALL, cursor: null });
  });

  it("reads every filter and the cursor", () => {
    expect(
      parseRequestFilters({
        period: "7d",
        tenant: "acme",
        alias: " chat-fast ",
        status: "answered",
        cursor: "abc",
      }),
    ).toEqual({
      filters: {
        period: "7d",
        tenant: "acme",
        alias: "chat-fast",
        status: "answered",
      },
      cursor: "abc",
    });
  });

  it("ignores empty values", () => {
    expect(
      parseRequestFilters({ tenant: "", alias: "  ", cursor: "" }),
    ).toEqual({ filters: ALL, cursor: null });
  });
});

describe("requestsHref", () => {
  it("links to the first page with the filters", () => {
    expect(requestsHref(ALL)).toBe("/requests?period=24h");
    expect(
      requestsHref({
        period: "7d",
        tenant: "acme & co",
        alias: "chat-fast",
        status: "failed",
      }),
    ).toBe(
      "/requests?period=7d&tenant=acme+%26+co&alias=chat-fast&status=failed",
    );
  });

  it("carries the cursor of an older page", () => {
    expect(requestsHref({ ...ALL, status: "failed" }, "ab==")).toBe(
      "/requests?period=24h&status=failed&cursor=ab%3D%3D",
    );
  });
});

describe("requestHref", () => {
  it("links to the detail with the filters and page of the list", () => {
    expect(requestHref("req/1", { ...ALL, tenant: "acme" }, "ab")).toBe(
      "/requests/req%2F1?period=24h&tenant=acme&cursor=ab",
    );
  });
});
