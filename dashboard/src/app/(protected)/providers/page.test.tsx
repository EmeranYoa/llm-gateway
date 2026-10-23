// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApiError, getTargets } from "@/api/client";
import { liveFixture, targetFixture, targetsFixture } from "@/test/fixtures";

import ProvidersPage from "./page";

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  getTargets: vi.fn(),
}));

// Times are shown in the browser's time zone: fix it, so the test runs anywhere.
vi.mock("@/lib/browser-hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/browser-hooks")>()),
  useBrowserTimeZone: () => "UTC",
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
  usePathname: () => "/providers",
  useSearchParams: () => new URLSearchParams(),
}));

async function renderPage(searchParams: Record<string, string> = {}) {
  render(
    await ProvidersPage({
      params: Promise.resolve({}),
      searchParams: Promise.resolve(searchParams),
    }),
  );
}

/** The card of a target, found by its provider/model name. */
function card(name: string): HTMLElement {
  return screen.getByRole("article", { name });
}

/** The texts of the status badges of a card. */
function badges(name: string): string[] {
  return within(within(card(name)).getByRole("list", { name: "Status" }))
    .getAllByRole("listitem")
    .map((item) => item.textContent ?? "");
}

/** The value of a statistic of the period on a card, found by its label. */
function figure(name: string, label: string): string {
  const statistics = within(card(name)).getByRole("region", {
    name: "Statistics of the period",
  });
  const term = within(statistics).getByText(label, { selector: "dt" });
  return term.nextElementSibling?.textContent ?? "";
}

const UNKNOWN_LIVE = liveFixture({
  status: "unknown",
  cooldown: null,
  breaker: null,
  rpm: { used: null, limit: 30 },
  tpm: { used: null, limit: 8000 },
  rpd: { used: null, limit: 1000, resets_at: "2026-10-24T00:00:00Z" },
});

beforeEach(() => {
  vi.mocked(getTargets).mockResolvedValue(
    targetsFixture({
      targets: [
        targetFixture(),
        targetFixture({
          provider: "gemini",
          model: "gemini-2.5-flash",
          live: liveFixture({
            cooldown: { active: true, until: "2026-10-23T12:01:30Z" },
            rpd: { used: 250, limit: 250, resets_at: "2026-10-24T07:00:00Z" },
          }),
        }),
        targetFixture({
          provider: "openrouter",
          model: "a:free",
          live: liveFixture({
            breaker: {
              state: "open",
              open_until: "2026-10-23T12:00:30Z",
              trial_running: false,
            },
          }),
        }),
        targetFixture({
          provider: "openrouter",
          model: "b:free",
          live: liveFixture({
            breaker: {
              state: "half_open",
              open_until: null,
              trial_running: true,
            },
          }),
        }),
        targetFixture({
          provider: "ollama",
          model: "llama3.2:3b",
          live: liveFixture({
            rpm: { used: null, limit: null },
            tpm: { used: null, limit: null },
            rpd: { used: null, limit: null, resets_at: "2026-10-24T00:00:00Z" },
          }),
        }),
        targetFixture({
          provider: "groq",
          model: "llama-3.1-8b-instant",
          configured: false,
          live: null,
        }),
      ],
    }),
  );
});

afterEach(cleanup);

describe("ProvidersPage", () => {
  it("asks for the period of the URL, 24h by default", async () => {
    await renderPage();
    expect(getTargets).toHaveBeenLastCalledWith("24h");

    cleanup();
    await renderPage({ period: "7d" });
    expect(getTargets).toHaveBeenLastCalledWith("7d");
    expect(screen.getByLabelText("Period")).toHaveValue("7d");
  });

  it("shows one card per target, in the order of the report", async () => {
    await renderPage();

    const names = screen
      .getAllByRole("article")
      .map((article) => article.getAttribute("aria-label"));
    expect(names).toEqual([
      "groq/openai/gpt-oss-20b",
      "gemini/gemini-2.5-flash",
      "openrouter/a:free",
      "openrouter/b:free",
      "ollama/llama3.2:3b",
      "groq/llama-3.1-8b-instant",
    ]);
  });

  it("says why traffic goes to each target or elsewhere", async () => {
    await renderPage();

    expect(badges("groq/openai/gpt-oss-20b")).toEqual(["Healthy"]);
    expect(badges("gemini/gemini-2.5-flash")).toEqual([
      "Cooling down",
      "Quota full",
    ]);
    expect(badges("openrouter/a:free")).toEqual(["Breaker open"]);
    expect(badges("openrouter/b:free")).toEqual(["Breaker half-open"]);
    expect(badges("ollama/llama3.2:3b")).toEqual(["Healthy"]);
    expect(badges("groq/llama-3.1-8b-instant")).toEqual([
      "No longer configured",
    ]);
  });

  it("counts the targets by status", async () => {
    await renderPage();

    const summary = within(
      screen.getByRole("list", { name: "Targets by status" }),
    )
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(summary).toEqual([
      "Healthy: 2",
      "Cooling down: 1",
      "Breaker open: 1",
      "Breaker half-open: 1",
      "No longer configured: 1",
    ]);
  });

  it("shows the statistics of the period", async () => {
    await renderPage();

    const name = "groq/openai/gpt-oss-20b";
    expect(figure(name, "Calls")).toBe("200");
    expect(figure(name, "Success rate")).toBe("90%");
    expect(figure(name, "Latency p50 / p95")).toBe("640 ms / 1.8 s");
    expect(figure(name, "Rate limited (429)")).toBe("10");
    expect(figure(name, "Timeouts")).toBe("3");
    expect(figure(name, "Unavailable")).toBe("4");
    expect(figure(name, "Misconfigured")).toBe("0");
    expect(figure(name, "Interrupted streams")).toBe("1");
    expect(figure(name, "Cancelled by the client")).toBe("2");
    expect(figure(name, "Cooldown")).toBe("25");
    expect(figure(name, "Breaker open")).toBe("5");
    expect(figure(name, "Quota full")).toBe("7");
    expect(within(card(name)).getByText("Last 24 hours")).toBeInTheDocument();
  });

  it("shows the live state: cooldown, breaker and quotas", async () => {
    await renderPage();

    const healthy = "groq/openai/gpt-oss-20b";
    const liveOf = (name: string) =>
      within(card(name)).getByRole("region", { name: "Live state" });
    expect(liveOf(healthy)).toHaveTextContent("CooldownNone");
    expect(liveOf(healthy)).toHaveTextContent("Circuit breakerClosed");
    expect(liveOf(healthy)).toHaveTextContent("Requests per minute12 / 30");
    expect(liveOf(healthy)).toHaveTextContent("Tokens per minute1,500 / 8,000");
    expect(liveOf(healthy)).toHaveTextContent("Requests per day400 / 1,000");
    expect(liveOf(healthy)).toHaveTextContent("Daily resetOct 24, 2026, 00:00");

    expect(liveOf("gemini/gemini-2.5-flash")).toHaveTextContent(
      "Active until Oct 23, 2026, 12:01:30",
    );
    expect(liveOf("openrouter/a:free")).toHaveTextContent(
      "Open until Oct 23, 2026, 12:00:30",
    );
    expect(liveOf("openrouter/b:free")).toHaveTextContent(
      "Half-open, trial call running",
    );
    expect(liveOf("ollama/llama3.2:3b")).toHaveTextContent(
      "Requests per minuteno limit",
    );
  });

  it("says clearly when the live state is unknown", async () => {
    vi.mocked(getTargets).mockResolvedValue(
      targetsFixture({ targets: [targetFixture({ live: UNKNOWN_LIVE })] }),
    );

    await renderPage();

    const name = "groq/openai/gpt-oss-20b";
    expect(badges(name)).toEqual(["Live state unavailable (Redis)"]);
    const live = within(card(name)).getByRole("region", { name: "Live state" });
    expect(live).toHaveTextContent("Live state unavailable (Redis)");
    expect(live).toHaveTextContent("Requests per minuteunknown / 30");
    expect(live).not.toHaveTextContent("Cooldown");
  });

  it("marks a target that is in no route any more", async () => {
    await renderPage();

    const name = "groq/llama-3.1-8b-instant";
    expect(
      within(card(name)).getByRole("region", { name: "Live state" }),
    ).toHaveTextContent("in no route any more");
    expect(figure(name, "Calls")).toBe("200");
  });

  it("says when no target is configured", async () => {
    vi.mocked(getTargets).mockResolvedValue(targetsFixture({ targets: [] }));

    await renderPage();

    expect(screen.getByText(/No target is configured/)).toBeInTheDocument();
  });

  it("shows the error of the admin API", async () => {
    vi.mocked(getTargets).mockRejectedValue(
      new AdminApiError("The database is unavailable.", 503, null),
    );

    await renderPage();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The database is unavailable.",
    );
  });
});
