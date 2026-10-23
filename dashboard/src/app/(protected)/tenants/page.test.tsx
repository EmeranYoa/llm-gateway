// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApiError, getTenantStatistics } from "@/api/client";
import { tenantsFixture } from "@/test/fixtures";

import TenantsPage from "./page";

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  getTenantStatistics: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
  usePathname: () => "/tenants",
  useSearchParams: () => new URLSearchParams(),
}));

async function renderPage(searchParams: Record<string, string> = {}) {
  render(
    await TenantsPage({
      params: Promise.resolve({}),
      searchParams: Promise.resolve(searchParams),
    }),
  );
}

beforeEach(() => {
  vi.mocked(getTenantStatistics).mockResolvedValue(tenantsFixture());
});

afterEach(cleanup);

describe("TenantsPage", () => {
  it("says how many answers of a tenant have no price", async () => {
    const fixture = tenantsFixture();
    fixture.tenants[0] = { ...fixture.tenants[0], unpriced_requests: 2 };
    vi.mocked(getTenantStatistics).mockResolvedValue(fixture);

    await renderPage();

    expect(screen.getByText(/2 without a price/)).toBeInTheDocument();
  });

  it("asks for the period of the URL, 24h by default", async () => {
    await renderPage();
    expect(getTenantStatistics).toHaveBeenLastCalledWith("24h");

    cleanup();
    await renderPage({ period: "30d" });
    expect(getTenantStatistics).toHaveBeenLastCalledWith("30d");
    expect(screen.getByLabelText("Period")).toHaveValue("30d");
  });

  it("renders one row per tenant with its figures", async () => {
    await renderPage();

    const headers = screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual([
      "Tenant",
      "Requests",
      "Tokens",
      "Cost",
      "Error rate",
      "Cache hits",
      "Saved cost",
      "Quota refusals",
    ]);
    const acme = screen.getByRole("row", { name: /acme/ });
    const cells = within(acme)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(cells).toEqual([
      "1,000",
      "300,000",
      "$1.25",
      "1.5%",
      "80",
      "$0.40",
      "3",
    ]);
  });

  it("links each row to the overview of the tenant, with the period", async () => {
    await renderPage({ period: "7d" });

    expect(screen.getByRole("link", { name: "acme" })).toHaveAttribute(
      "href",
      "/?period=7d&tenant=acme",
    );
    expect(screen.getByRole("link", { name: "beta & co" })).toHaveAttribute(
      "href",
      "/?period=7d&tenant=beta+%26+co",
    );
  });

  it("says when there is no tenant", async () => {
    vi.mocked(getTenantStatistics).mockResolvedValue(
      tenantsFixture({ tenants: [] }),
    );

    await renderPage();

    expect(screen.getByText(/No tenant yet/)).toBeInTheDocument();
  });

  it("shows the error of the admin API", async () => {
    vi.mocked(getTenantStatistics).mockRejectedValue(
      new AdminApiError("The database is unavailable.", 503, null),
    );

    await renderPage();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The database is unavailable.",
    );
  });
});
