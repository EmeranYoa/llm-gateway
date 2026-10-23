// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getSetupStatus } from "@/api/operators";

import SetupPage from "./page";

vi.mock("@/api/operators", () => ({ getSetupStatus: vi.fn() }));

vi.mock("@/lib/auth-actions", () => ({ setUpAction: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  redirect: vi.fn((url: string) => {
    throw new Error(`redirect:${url}`);
  }),
}));

afterEach(cleanup);

describe("SetupPage", () => {
  it("asks for the setup token, a username and the password twice", async () => {
    vi.mocked(getSetupStatus).mockResolvedValue(true);

    render(await SetupPage());

    expect(
      screen.getByRole("heading", { name: "Create the first account" }),
    ).toBeInTheDocument();
    for (const label of [
      "Setup token",
      "Username",
      "Password",
      "Password again",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it("opens the sign-in once an account exists", async () => {
    vi.mocked(getSetupStatus).mockResolvedValue(false);

    await expect(SetupPage()).rejects.toThrow("redirect:/login");
  });
});
