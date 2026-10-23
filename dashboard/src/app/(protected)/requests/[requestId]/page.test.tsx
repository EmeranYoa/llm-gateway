// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApiError, getRequest } from "@/api/client";
import {
  requestDetailFixture,
  requestSummaryFixture,
  routingStepFixture,
} from "@/test/fixtures";

import RequestDetailPage from "./page";

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  getRequest: vi.fn(),
}));

// Times are shown in the browser's time zone: fix it, so the test runs anywhere.
vi.mock("@/lib/browser-hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/browser-hooks")>()),
  useBrowserTimeZone: () => "UTC",
}));

async function renderPage(
  requestId = "req-1",
  searchParams: Record<string, string> = {},
) {
  render(
    await RequestDetailPage({
      params: Promise.resolve({ requestId }),
      searchParams: Promise.resolve(searchParams),
    }),
  );
}

/** The steps of the routing path, in order. */
function steps(): HTMLElement[] {
  return within(
    screen.getByRole("list", { name: "Routing path" }),
  ).getAllByRole("listitem");
}

/** The value of a detail of a step, found by its label. */
function detail(step: HTMLElement, label: string): string | null {
  const term = within(step).queryByText(label, { selector: "dt" });
  return term?.nextElementSibling?.textContent ?? null;
}

beforeEach(() => {
  vi.mocked(getRequest).mockResolvedValue(requestDetailFixture());
});

afterEach(cleanup);

describe("RequestDetailPage", () => {
  it("asks for the request of the URL", async () => {
    await renderPage("req-42");

    expect(getRequest).toHaveBeenCalledWith("req-42");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Request req-42",
    );
  });

  it("shows the summary of the request", async () => {
    await renderPage();

    const text = screen.getByLabelText("Summary").textContent;
    expect(text).toContain("ReceivedOct 23, 2026, 11:59:30");
    expect(text).toContain("Tenantacme");
    expect(text).toContain("Aliaschat-fast");
    expect(text).toContain("StatusAnswered");
    expect(text).toContain("HTTP status200");
    expect(text).toContain("Answered bygemini/gemini-2.5-flash");
    expect(text).toContain("Attempts3");
    expect(text).toContain("Streamyes");
    expect(text).toContain("Latency1.3 s");
    expect(text).toContain("Cost$0.0012");
    expect(text).toContain("Cachemiss");
  });

  it("shows a failover with a skip as an ordered routing path", async () => {
    await renderPage();

    const [skip, limited, answer] = steps();
    expect(skip).toHaveAccessibleName("Step 1");
    expect(skip).toHaveTextContent("groq/openai/gpt-oss-20b");
    expect(skip).toHaveTextContent("SkippedCooldown active");
    expect(skip).toHaveTextContent("Cooldown active for 42 s");
    expect(detail(skip, "Latency")).toBeNull();
    expect(detail(skip, "Cost")).toBeNull();

    expect(limited).toHaveTextContent("ErrorRate limited (429)");
    expect(detail(limited, "HTTP status")).toBe("429");
    expect(detail(limited, "Latency")).toBe("150 ms");
    expect(detail(limited, "Cost")).toBe("unknown");

    expect(answer).toHaveTextContent("gemini/gemini-2.5-flash");
    expect(answer).toHaveTextContent("SuccessAnswered");
    expect(detail(answer, "HTTP status")).toBe("200");
    expect(detail(answer, "Latency")).toBe("1.1 s");
    expect(detail(answer, "First token")).toBe("420 ms");
    expect(detail(answer, "Tokens")).toBe(
      "120 prompt · 80 completion · 600 estimated",
    );
    expect(detail(answer, "Cost")).toBe("$0.0012");
    expect(detail(answer, "Cache")).toBe("miss");
  });

  it("shows a cache hit with its similarity and saved cost", async () => {
    vi.mocked(getRequest).mockResolvedValue(
      requestDetailFixture({
        ...requestSummaryFixture({ attempts: 1, cache: "hit", cost_usd: null }),
        routing_path: [
          routingStepFixture({
            outcome: "cache_hit",
            status_code: 200,
            latency_ms: 12,
            estimated_tokens: null,
            cost_usd: null,
            saved_cost_usd: 0.0008,
            cache: "hit",
            cache_similarity: 0.97312,
          }),
        ],
      }),
    );

    await renderPage();

    const [hit] = steps();
    expect(hit).toHaveTextContent("SuccessAnswered from the cache");
    expect(detail(hit, "Similarity")).toBe("0.973");
    expect(detail(hit, "Saved cost")).toBe("$0.0008");
    expect(detail(hit, "Cache")).toBe("hit");
    expect(detail(hit, "Cost")).toBeNull();
  });

  it("marks a step routed in degraded mode, and a client error", async () => {
    vi.mocked(getRequest).mockResolvedValue(
      requestDetailFixture({
        routing_path: [
          routingStepFixture({
            outcome: "invalid_request",
            status_code: 400,
            degraded: true,
            error_message: "groq/openai/gpt-oss-20b: unknown field",
          }),
        ],
      }),
    );

    await renderPage();

    const [step] = steps();
    expect(step).toHaveTextContent("Client errorInvalid request (4xx)");
    expect(step).toHaveTextContent("Degraded mode");
  });

  it("links back to the list with its filters and page", async () => {
    await renderPage("req-1", {
      period: "7d",
      tenant: "acme",
      status: "failed",
      cursor: "abc",
    });

    expect(
      screen.getByRole("link", { name: /Back to the requests/ }),
    ).toHaveAttribute(
      "href",
      "/requests?period=7d&tenant=acme&status=failed&cursor=abc",
    );
  });

  it("says when the request does not exist", async () => {
    vi.mocked(getRequest).mockRejectedValue(
      new AdminApiError("No request with this id.", 404, "request_not_found"),
    );

    await renderPage("nope");

    expect(screen.getByRole("alert")).toHaveTextContent(
      "No request with this id.",
    );
    expect(
      screen.queryByRole("list", { name: "Routing path" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Back to the requests/ }),
    ).toHaveAttribute("href", "/requests?period=24h");
  });

  it("shows other errors of the admin API", async () => {
    vi.mocked(getRequest).mockRejectedValue(
      new AdminApiError("The database is unavailable.", 503, null),
    );

    await renderPage();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The database is unavailable.",
    );
  });
});
