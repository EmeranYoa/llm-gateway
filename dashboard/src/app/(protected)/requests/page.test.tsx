// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApiError, listRequests, listTenantNames } from "@/api/client";
import { requestPageFixture } from "@/test/fixtures";

import RequestsPage from "./page";

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  listRequests: vi.fn(),
  listTenantNames: vi.fn(),
}));

// Times are shown in the browser's time zone: fix it, so the test runs anywhere.
vi.mock("@/lib/browser-hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/browser-hooks")>()),
  useBrowserTimeZone: () => "UTC",
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
  usePathname: () => "/requests",
  useSearchParams: () => new URLSearchParams(),
}));

async function renderPage(searchParams: Record<string, string> = {}) {
  render(
    await RequestsPage({
      params: Promise.resolve({}),
      searchParams: Promise.resolve(searchParams),
    }),
  );
}

function cellsOf(row: HTMLElement): string[] {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent ?? "");
}

beforeEach(() => {
  vi.mocked(listRequests).mockResolvedValue(requestPageFixture());
  vi.mocked(listTenantNames).mockResolvedValue(["acme", "beta"]);
});

afterEach(cleanup);

describe("RequestsPage", () => {
  it("asks for the first page of the last 24 hours by default", async () => {
    await renderPage();

    expect(listRequests).toHaveBeenCalledWith(
      { period: "24h", tenant: null, alias: null, status: null },
      null,
    );
  });

  it("asks for the filters and the page of the URL, and shows them", async () => {
    await renderPage({
      period: "7d",
      tenant: "acme",
      alias: "chat-fast",
      status: "failed",
      cursor: "abc",
    });

    expect(listRequests).toHaveBeenCalledWith(
      { period: "7d", tenant: "acme", alias: "chat-fast", status: "failed" },
      "abc",
    );
    expect(screen.getByLabelText("Period")).toHaveValue("7d");
    expect(screen.getByLabelText("Tenant")).toHaveValue("acme");
    expect(screen.getByLabelText("Alias")).toHaveValue("chat-fast");
    expect(screen.getByLabelText("Status")).toHaveValue("failed");
  });

  it("renders one row per request", async () => {
    await renderPage();

    const headers = screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual([
      "Time",
      "Tenant",
      "Alias",
      "Status",
      "HTTP",
      "Answered by",
      "Attempts",
      "Stream",
      "Latency",
      "Cost",
      "Cache",
    ]);
    const [answered, failed] = screen.getAllByRole("row").slice(1);
    expect(within(answered).getByRole("rowheader")).toHaveTextContent(
      "Oct 23, 2026, 11:59:30",
    );
    expect(cellsOf(answered)).toEqual([
      "acme",
      "chat-fast",
      "Answered",
      "200",
      "gemini/gemini-2.5-flash",
      "3",
      "yes",
      "1.3 s",
      "$0.0012",
      "miss",
    ]);
    expect(cellsOf(failed)).toEqual([
      "n/a",
      "chat-fast",
      "Failed",
      "503",
      "not answered",
      "2",
      "no",
      "n/a",
      "unknown",
      "off",
    ]);
  });

  it("explains each status in a tooltip", async () => {
    await renderPage();

    expect(
      within(screen.getByRole("table")).getByText("Failed"),
    ).toHaveAttribute(
      "title",
      expect.stringMatching(/every target failed or was skipped/),
    );
  });

  it("links each request to its detail, with the filters and page of the list", async () => {
    await renderPage({ period: "7d", status: "answered", cursor: "abc" });

    expect(
      screen.getByRole("link", { name: "Details of request req-1" }),
    ).toHaveAttribute(
      "href",
      "/requests/req-1?period=7d&status=answered&cursor=abc",
    );
  });

  it("links to older requests with the filters and the next cursor", async () => {
    vi.mocked(listRequests).mockResolvedValue(
      requestPageFixture({ next_cursor: "next==" }),
    );

    await renderPage({ period: "30d", tenant: "beta & co" });

    expect(
      screen.getByRole("link", { name: "Older requests" }),
    ).toHaveAttribute(
      "href",
      "/requests?period=30d&tenant=beta+%26+co&cursor=next%3D%3D",
    );
    expect(
      screen.queryByRole("link", { name: "Newest requests" }),
    ).not.toBeInTheDocument();
  });

  it("offers the way back to the newest requests on an older page", async () => {
    await renderPage({ alias: "chat-fast", cursor: "abc" });

    expect(
      screen.getByRole("link", { name: "Newest requests" }),
    ).toHaveAttribute("href", "/requests?period=24h&alias=chat-fast");
    expect(
      screen.queryByRole("link", { name: "Older requests" }),
    ).not.toBeInTheDocument();
  });

  it("refreshes the first page only", async () => {
    await renderPage();
    expect(
      screen.getByRole("button", { name: "Pause auto-refresh" }),
    ).toBeInTheDocument();

    cleanup();
    await renderPage({ cursor: "abc" });
    expect(
      screen.queryByRole("button", { name: "Pause auto-refresh" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/auto-refresh is off/)).toBeInTheDocument();
  });

  it("offers the tenants in the tenant filter", async () => {
    await renderPage();

    const options = within(screen.getByLabelText("Tenant"))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual(["All tenants", "acme", "beta"]);
  });

  it("says when no request matches", async () => {
    vi.mocked(listRequests).mockResolvedValue(
      requestPageFixture({ items: [] }),
    );

    await renderPage({ status: "cancelled" });

    expect(screen.getByText(/No request matches/)).toBeInTheDocument();
  });

  it("shows the error of the admin API", async () => {
    vi.mocked(listRequests).mockRejectedValue(
      new AdminApiError("Invalid cursor.", 400, "invalid_cursor"),
    );

    await renderPage({ cursor: "broken" });

    expect(screen.getByRole("alert")).toHaveTextContent("Invalid cursor.");
  });

  it("still shows the requests when the tenant names cannot be loaded", async () => {
    vi.mocked(listTenantNames).mockRejectedValue(
      new AdminApiError("boom", 500, null),
    );

    await renderPage();

    expect(
      screen.getByRole("link", { name: "Details of request req-1" }),
    ).toBeInTheDocument();
  });
});
