// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type AccountState, loadAccount } from "@/lib/account";

import ChangePasswordPage from "./page";

vi.mock("@/lib/account", () => ({ loadAccount: vi.fn() }));

vi.mock("@/lib/auth-actions", () => ({
  changePasswordAction: vi.fn(),
  signOutAction: vi.fn(),
}));

vi.mock("@/lib/language-actions", () => ({ saveLanguageAction: vi.fn() }));

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

describe("ChangePasswordPage", () => {
  it("says the password must be changed, and offers to sign out", async () => {
    account({
      status: "signed-in",
      me: { username: "alice", must_change_password: true, language: null },
    });

    render(await ChangePasswordPage());

    expect(
      screen.getByRole("heading", { name: "Change your password" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Choose a new password before you continue."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Current password")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Sign out" }),
    ).toBeInTheDocument();
  });

  it("ends a session that the admin API refused", async () => {
    account({ status: "expired" });

    await expect(ChangePasswordPage()).rejects.toThrow(
      "redirect:/session-expired",
    );
  });
});
