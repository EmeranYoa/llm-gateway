// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApiError, getOverview, listTenantNames } from "@/api/client";
import { overviewFixture } from "@/test/fixtures";

import OverviewPage from "./page";

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  getOverview: vi.fn(),
  listTenantNames: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

// Recharts measures its container; jsdom has no layout, so the charts have no
// size (Recharts warns about it) and only their titles render.
class FakeResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

async function renderPage(searchParams: Record<string, string> = {}) {
  render(
    await OverviewPage({
      params: Promise.resolve({}),
      searchParams: Promise.resolve(searchParams),
    }),
  );
}

/** The card of a figure, found by its label. */
function card(label: string): HTMLElement {
  const heading = screen.getByRole("heading", { name: label });
  return heading.closest("div.rounded-lg") as HTMLElement;
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  vi.spyOn(console, "warn").mockImplementation(() => {});
  vi.mocked(getOverview).mockResolvedValue(overviewFixture());
  vi.mocked(listTenantNames).mockResolvedValue(["acme", "beta & co"]);
});

afterEach(cleanup);

describe("OverviewPage", () => {
  it("asks the admin API for the default period and every tenant", async () => {
    await renderPage();

    expect(getOverview).toHaveBeenCalledWith("24h", null);
  });

  it("asks for the period and the tenant of the URL", async () => {
    await renderPage({ period: "7d", tenant: "acme" });

    expect(getOverview).toHaveBeenCalledWith("7d", "acme");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Overview: acme",
    );
    expect(screen.getByLabelText("Period")).toHaveValue("7d");
    expect(screen.getByLabelText("Tenant")).toHaveValue("acme");
  });

  it("renders the key figures of the overview", async () => {
    await renderPage();

    expect(within(card("Requests")).getByText("1,250")).toBeInTheDocument();
    const errorRate = card("Error rate");
    expect(within(errorRate).getByText("2%")).toBeInTheDocument();
    expect(errorRate).toHaveTextContent(
      "25 failed. Not counted: 20 client errors, 5 cancelled.",
    );
    expect(within(card("Fallback rate")).getByText("12.5%")).toBeVisible();
    const latency = card("Latency p50");
    expect(within(latency).getByText("850 ms")).toBeInTheDocument();
    expect(latency).toHaveTextContent("p95: 2.1 s");
    const firstToken = card("Time to first token p50");
    expect(within(firstToken).getByText("320 ms")).toBeInTheDocument();
    expect(firstToken).toHaveTextContent("p95: 900 ms");
    expect(
      within(card("Cache hit latency p50")).getByText("12 ms"),
    ).toBeInTheDocument();
    expect(within(card("Tokens")).getByText("345,678")).toBeInTheDocument();
    expect(within(card("Cost")).getByText("$1.50")).toBeInTheDocument();
    const hitRate = card("Cache hit rate");
    expect(within(hitRate).getByText("25%")).toBeInTheDocument();
    expect(hitRate).toHaveTextContent("100 hits of 400 cached requests");
    expect(within(card("Saved tokens")).getByText("23,456")).toBeVisible();
    expect(within(card("Saved cost")).getByText("$0.42")).toBeVisible();
  });

  it("gives every figure its definition", async () => {
    await renderPage();

    expect(
      screen.getByRole("button", { name: "Definition of Error rate" }),
    ).toHaveAccessibleDescription(/Failed requests \/ requests/);
  });

  it("shows no price warning when every request has a price", async () => {
    await renderPage();

    expect(card("Cost")).not.toHaveTextContent("requests without a price");
  });

  it("warns about requests without a price, never counted as free", async () => {
    vi.mocked(getOverview).mockResolvedValue(
      overviewFixture({ cost_usd: 0.8, unpriced_requests: 3 }),
    );

    await renderPage();

    const cost = card("Cost");
    expect(within(cost).getByText("$0.80")).toBeInTheDocument();
    expect(cost).toHaveTextContent("3 requests without a price, not included");
  });

  it("shows n/a for durations nothing measured", async () => {
    vi.mocked(getOverview).mockResolvedValue(
      overviewFixture({ time_to_first_token_ms: { p50: null, p95: null } }),
    );

    await renderPage();

    expect(
      within(card("Time to first token p50")).getByText("n/a"),
    ).toBeInTheDocument();
  });

  it("offers the tenants in the tenant filter", async () => {
    await renderPage();

    const options = within(screen.getByLabelText("Tenant"))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual(["All tenants", "acme", "beta & co"]);
  });

  it("titles the charts, and says the points of long periods are UTC days", async () => {
    await renderPage({ period: "30d" });

    expect(
      screen.getByText("Requests and failed requests"),
    ).toBeInTheDocument();
    expect(screen.getByText("Cost (USD)")).toBeInTheDocument();
    expect(screen.getAllByText("One bar per UTC day.")).toHaveLength(3);
  });

  it("shows the error of the admin API instead of the figures", async () => {
    vi.mocked(getOverview).mockRejectedValue(
      new AdminApiError("Unknown tenant 'nope'.", 404, "tenant_not_found"),
    );

    await renderPage({ tenant: "nope" });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Unknown tenant 'nope'.",
    );
    expect(
      screen.queryByRole("heading", { name: "Requests" }),
    ).not.toBeInTheDocument();
  });

  it("still shows the overview when the tenant names cannot be loaded", async () => {
    vi.mocked(listTenantNames).mockRejectedValue(
      new AdminApiError("boom", 500, null),
    );

    await renderPage();

    expect(within(card("Requests")).getByText("1,250")).toBeInTheDocument();
  });
});
