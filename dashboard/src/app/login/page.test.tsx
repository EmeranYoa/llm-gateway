// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminApiError } from "@/api/client";
import { getRecoveryStatus, getSetupStatus } from "@/api/operators";

import LoginPage from "./page";

vi.mock("@/api/operators", () => ({
  getSetupStatus: vi.fn(),
  getRecoveryStatus: vi.fn(),
}));

vi.mock("@/lib/auth-actions", () => ({ signInAction: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

async function renderPage(searchParams: Record<string, string> = {}) {
  render(
    await LoginPage({
      params: Promise.resolve({}),
      searchParams: Promise.resolve(searchParams),
    }),
  );
}

beforeEach(() => {
  vi.mocked(getSetupStatus).mockResolvedValue(false);
  vi.mocked(getRecoveryStatus).mockResolvedValue(false);
});

afterEach(cleanup);

describe("LoginPage", () => {
  it("asks for a username and a password", async () => {
    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByLabelText("Language")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("opens the setup while no account exists", async () => {
    vi.mocked(getSetupStatus).mockResolvedValue(true);

    await expect(renderPage()).rejects.toThrow("redirect:/setup");
  });

  it("links to the recovery while it is on", async () => {
    vi.mocked(getRecoveryStatus).mockResolvedValue(true);

    await renderPage();

    expect(
      screen.getByRole("link", {
        name: "Lost every password? Recover an account",
      }),
    ).toHaveAttribute("href", "/recovery");
  });

  it("says when the session has ended", async () => {
    await renderPage({ expired: "1" });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Your session has ended. Sign in again.",
    );
  });

  it("still shows the form when the admin API cannot say", async () => {
    const down = new AdminApiError("down", null, "admin_api_unreachable");
    vi.mocked(getSetupStatus).mockRejectedValue(down);
    vi.mocked(getRecoveryStatus).mockRejectedValue(down);

    await renderPage();

    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });
});
