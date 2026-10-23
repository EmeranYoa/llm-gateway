// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminApiError } from "@/api/client";
import { type AccountState, loadAccount } from "@/lib/account";

import ProtectedLayout from "./layout";

vi.mock("@/lib/account", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/account")>()),
  loadAccount: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

afterEach(cleanup);

function account(state: AccountState) {
  vi.mocked(loadAccount).mockResolvedValue(state);
}

const ALICE = { username: "alice", language: null };

async function renderLayout() {
  render(await ProtectedLayout({ children: <p>Screen</p> }));
}

describe("ProtectedLayout", () => {
  it("shows the screen to a signed-in operator", async () => {
    account({
      status: "signed-in",
      me: { ...ALICE, must_change_password: false },
    });

    await renderLayout();

    expect(screen.getByText("Screen")).toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });

  it("sends an operator who must change their password to the change page", async () => {
    account({
      status: "signed-in",
      me: { ...ALICE, must_change_password: true },
    });

    await expect(renderLayout()).rejects.toThrow("redirect:/change-password");
  });

  it("ends a session that the admin API refused", async () => {
    account({ status: "expired" });

    await expect(renderLayout()).rejects.toThrow("redirect:/session-expired");
  });

  it("sends a visitor without a session to the sign-in page", async () => {
    account({ status: "signed-out" });

    await expect(renderLayout()).rejects.toThrow("redirect:/login");
  });

  it("still shows the screen when the account cannot be read: its calls show the error", async () => {
    account({
      status: "unavailable",
      error: new AdminApiError("down", 503, "database_unavailable"),
    });

    await renderLayout();

    expect(screen.getByText("Screen")).toBeInTheDocument();
  });
});
